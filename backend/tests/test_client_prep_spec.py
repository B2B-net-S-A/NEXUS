"""„Specyfika na prep” w karcie klienta (F2, decyzje Artura z 24.11.2026).

Kontrakty: lustro migracji 0768 w ``entrypoint.sh``, normalizacja pól, treść
zasiewu zgodna z rozstrzygnięciami (Nordea, Tauron, Bank Pocztowy), PUT bez
klucza nie czyści zapisanej specyfiki (stary front) i jednorazowy zasiew na bazie.
"""

from __future__ import annotations

import importlib.util
import re
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.services.client_prep_spec import (
    MAX_LINES,
    PREP_SPEC_KEYS,
    PrepSpec,
    normalize_prep_spec,
)
from app.services.client_prep_spec_data import (
    BANK_POCZTOWY,
    NORDEA,
    PREP_SPECS,
    TAURON,
)
from app.services.client_prep_spec_seed import _tauron_about
from tests.test_client_playbooks_api import _headers_for

BACKEND = Path(__file__).resolve().parents[1]
URL = "/api/clients/{cid}/playbook"

# „Co powiedzieć kandydatowi” Tauronu w kopii produkcji z 24.11.2026 (bez osób).
TAURON_ABOUT_2026_11_24 = (
    "TAURON to jedna z największych grup energetycznych w Polsce. Firma realizuje "
    "strategiczne projekty związane z transformacją energetyczną, cyfryzacją oraz "
    "rozwojem nowoczesnych usług dla klientów. Praca odbywa się w środowisku Agile.\n"
    "Lokalizacja biur: \nWrocław, pl. Powstańców Śląskich 20\n"
    "Katowice al. Walentego Roździeńskiego 1B (KTW II)\n"
    "Długoterminowe projekty – współpraca na lata\n"
    "Interview odbywa się w języku polskim\n"
    "Konsultanci w trakcie świadczenia usług dla Tauron muszą być zlokalizowani "
    "w Polsce. Praca zza granicy nie jest możliwa. \n"
    "Zwrot kosztów dojazdów do biura nie przysługuje. \n"
    "W Tauron obowiązuje sztywny limit godzin przepracowanych w miesiącu, który "
    "wynosi 165h."
)


def _migration():
    path = BACKEND / "alembic/versions/0768_client_playbook_prep_spec.py"
    spec = importlib.util.spec_from_file_location("m0768", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_entrypoint_mirrors_the_migration() -> None:
    module = _migration()
    assert module.revision == "0768_client_playbook_prep_spec"
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert f'"{module.UPGRADE_SQL}",' in entrypoint
    assert 'run_unless_marked "client_prep_spec_seed_2026_11_24"' in entrypoint


def test_normalize_strips_drops_blank_lines_and_fills_every_key() -> None:
    out = normalize_prep_spec({"language": ["  Polski ", "", "   "], "focus": []})
    assert out is not None
    assert set(out) == set(PREP_SPEC_KEYS)
    assert out["language"] == ["Polski"]
    assert out["focus"] == []


def test_normalize_all_empty_is_none() -> None:
    assert normalize_prep_spec(None) is None
    assert normalize_prep_spec({key: [" "] for key in PREP_SPEC_KEYS}) is None


def test_spec_limits_and_unknown_key() -> None:
    with pytest.raises(ValidationError):
        PrepSpec.model_validate({"focus": ["x"] * (MAX_LINES + 1)})
    with pytest.raises(ValidationError):
        PrepSpec.model_validate({"focus": ["x" * 301]})
    # Nieznane pole nie przechodzi po cichu do bazy.
    assert "salary" not in (normalize_prep_spec({"salary": ["10 tys."]}) or {})


def test_seed_covers_the_twelve_clients_and_validates() -> None:
    assert len(PREP_SPECS) == 12
    for client_id, spec in PREP_SPECS.items():
        assert set(spec) == set(PREP_SPEC_KEYS), client_id
        assert normalize_prep_spec(spec) is not None, client_id


def test_seed_text_follows_the_decisions_of_2026_11_24() -> None:
    nordea = PREP_SPECS[NORDEA]
    assert any(
        "Collaboration, Ownership, Passion, Courage" in line
        for line in nordea["highlights"]
    )
    assert any("dobrze wypada" in line for line in nordea["focus"])
    tauron = PREP_SPECS[TAURON]
    assert any("umowa o pracę" in line for line in tauron["cooperation"])
    assert not any("165" in line for lines in tauron.values() for line in lines)
    assert any("Warszawa" in line for line in tauron["work_mode"])


_TEAM_ONLY = re.compile(r"tylko dla zespołu|\bnie mów", re.IGNORECASE)


def test_seed_has_no_team_only_notes() -> None:
    # Repo jest publiczne: uwagi, których kandydat (i klient) ma nie usłyszeć,
    # wpisuje DL w karcie, nie zasiew.
    for lines in PREP_SPECS.values():
        for line in (line for values in lines.values() for line in values):
            assert not _TEAM_ONLY.search(line), line


def test_seed_text_uses_brand_spelling() -> None:
    text = repr(PREP_SPECS)
    assert "B2B.net" not in text and "B2B Network" not in text


def test_tauron_about_rewrite_only_on_the_known_text() -> None:
    new = _tauron_about(TAURON_ABOUT_2026_11_24)
    assert new is not None
    assert "165" not in new
    assert "według zlecenia rekrutacyjnego" in new
    assert "(KTW II)\nWarszawa\nDługoterminowe" in new
    # Ktoś już poprawił kartę → krok jej nie rusza.
    assert _tauron_about(new) is None
    assert _tauron_about(None) is None


# ── Na bazie ────────────────────────────────────────────────────────────────


async def _client_with_card(**card) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client, ClientStatus
    from app.models.client_playbook import ClientPlaybook

    async with AsyncSessionLocal() as db:
        client = Client(
            name=f"Prep spec {uuid.uuid4().hex[:6]}", status=ClientStatus.active
        )
        db.add(client)
        await db.flush()
        db.add(ClientPlaybook(client_id=client.id, version=1, **card))
        await db.commit()
        return client.id


async def _cleanup(client_ids: list[int], marker: str) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting
    from app.models.client import Client
    from app.models.client_playbook import ClientPlaybook
    from app.models.client_playbook_event import ClientPlaybookEvent

    async with AsyncSessionLocal() as db:
        for model in (ClientPlaybookEvent, ClientPlaybook):
            await db.execute(delete(model).where(model.client_id.in_(client_ids)))
        await db.execute(delete(Client).where(Client.id.in_(client_ids)))
        await db.execute(delete(AppSetting).where(AppSetting.key == marker))
        await db.commit()


@pytest.mark.asyncio
async def test_seed_fills_empty_cards_and_fixes_tauron_once() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client_playbook import ClientPlaybook
    from app.models.client_playbook_event import ClientPlaybookEvent
    from app.services.client_prep_spec_seed import run_client_prep_spec_seed

    marker = f"test_prep_spec_seed_{uuid.uuid4().hex[:6]}"
    kept_spec = normalize_prep_spec({"language": ["Wpisane przez DL-a"]})
    plain = await _client_with_card()
    tauron = await _client_with_card(about_for_candidate=TAURON_ABOUT_2026_11_24)
    bp = await _client_with_card(process_rules_md="- OFFLIMIT - TAK")
    kept = await _client_with_card(prep_spec=kept_spec)
    missing = 999_999_123
    specs = {
        plain: PREP_SPECS[NORDEA],
        tauron: PREP_SPECS[TAURON],
        bp: PREP_SPECS[BANK_POCZTOWY],
        kept: PREP_SPECS[NORDEA],
        missing: PREP_SPECS[NORDEA],
    }
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_client_prep_spec_seed(
                db, marker=marker, specs=specs, tauron_id=tauron
            )
            await db.commit()
        assert summary is not None
        assert summary["changed"] == 3
        skipped = {r["client_id"]: r["skipped"] for r in summary["results"]}
        assert skipped[kept] == "nothing_to_change"
        assert skipped[missing] == "no_card"

        async with AsyncSessionLocal() as db:
            rows = {
                r.client_id: r
                for r in (
                    await db.execute(
                        select(ClientPlaybook).where(
                            ClientPlaybook.client_id.in_([plain, tauron, bp, kept])
                        )
                    )
                ).scalars()
            }
            events = (
                (
                    await db.execute(
                        select(ClientPlaybookEvent).where(
                            ClientPlaybookEvent.client_id.in_([plain, tauron, bp, kept])
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert rows[plain].prep_spec == normalize_prep_spec(PREP_SPECS[NORDEA])
        assert rows[plain].version == 2
        assert "165" not in rows[tauron].about_for_candidate
        # Zasady procesu bez zmian: uwag tylko dla zespołu krok nie wpisuje.
        assert rows[bp].process_rules_md == "- OFFLIMIT - TAK"
        assert rows[kept].prep_spec == kept_spec and rows[kept].version == 1
        by_client = {e.client_id: e for e in events}
        assert set(by_client) == {plain, tauron, bp}
        assert set(by_client[tauron].changes) == {"prep_spec", "about_for_candidate"}
        assert by_client[bp].playbook_version == 2 and by_client[bp].action == "saved"

        async with AsyncSessionLocal() as db:
            again = await run_client_prep_spec_seed(
                db, marker=marker, specs=specs, tauron_id=tauron
            )
            await db.commit()
        assert again is None
    finally:
        await _cleanup([plain, tauron, bp, kept], marker)


@pytest.mark.asyncio
async def test_put_without_prep_spec_keeps_it_and_null_clears_it(
    app_client: AsyncClient,
) -> None:
    spec = normalize_prep_spec({"work_mode": ["Hybryda"], "cooperation": ["B2B"]})
    cid = await _client_with_card(about_for_candidate="Bank.", prep_spec=spec)
    try:
        headers = await _headers_for(app_client, "delivery_lead")
        # Front sprzed 0768 wysyła kartę bez klucza — specyfika zostaje.
        old_front = await app_client.put(
            URL.format(cid=cid),
            json={"about_for_candidate": "Bank z oddziałami."},
            headers=headers,
        )
        assert old_front.status_code == 200, old_front.text
        assert old_front.json()["prep_spec"] == spec

        edited = await app_client.put(
            URL.format(cid=cid),
            json={
                "about_for_candidate": "Bank z oddziałami.",
                "prep_spec": {"work_mode": ["Zdalnie", " "], "language": ["Polski"]},
            },
            headers=headers,
        )
        assert edited.status_code == 200, edited.text
        body = edited.json()
        assert body["prep_spec"]["work_mode"] == ["Zdalnie"]
        assert body["prep_spec"]["cooperation"] == []
        history = await app_client.get(
            URL.format(cid=cid) + "/history", headers=headers
        )
        assert "prep_spec" in history.json()[0]["changes"]

        cleared = await app_client.put(
            URL.format(cid=cid),
            json={"about_for_candidate": "Bank z oddziałami.", "prep_spec": None},
            headers=headers,
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["prep_spec"] is None

        too_long = await app_client.put(
            URL.format(cid=cid),
            json={"prep_spec": {"focus": ["x" * 301]}},
            headers=headers,
        )
        assert too_long.status_code == 422
    finally:
        await _cleanup([cid], "unused-marker")
