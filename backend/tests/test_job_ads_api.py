"""Ogłoszenie na portale (0430) — trasy z bazą.

Kontrakt ``docs/claude/rekrutacja-tworzenie/ogloszenie-na-portale-kopiuj-wklej.md``:

- odpowiedź nigdy nie niesie klienta ani stawki (test na KSZTAŁT odpowiedzi);
- pierwsze ogłoszenie bez modelu = złożenie oznaczone ``template``; awaria
  modelu przy istniejącym ogłoszeniu = 503 i treść bez zmian; wersja
  angielska bez modelu nie powstaje;
- kontrola widzi pola ogłoszenia, miasto rekrutacji i stałe bloki;
- zapis poprawki ze starą wersją = 409; ponowne przygotowanie nie zastępuje
  poprawki zapisanej, kiedy model układał treść; stałe bloki zapisuje admin
  i HoR;
- oznaczenie publikacji (0432): link tylko do portalu, „do aktualizacji” po
  zmianie treści, zdjęcie z portalu zostawia ślad, lista rekrutacji niesie
  tylko aktywne ogłoszenia.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.job import Job
from app.models.job_ad import JobAd
from app.models.job_public_profile import JobPublicProfile
from app.models.user import User, UserRole
from app.services.job_ad import career, fixed_blocks, generate, prepare
from app.services.job_ad_schema import SOURCE_AI, SOURCE_TEMPLATE
from tests.test_career_links_api import _login, _owner_with_job

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def api() -> AsyncClient:
    from app.core.rate_limit import limiter
    from app.main import app

    limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client


_MODEL_REPLY = {
    "lead": "Szukamy osoby do zespołu rozliczeń.",
    "about": "Zespół rozwija system rozliczeń w sektorze bankowym.",
    "responsibilities": ["rozwój mikroserwisów w Javie", "przeglądy kodu"],
    "requirements": ["praktyczna znajomość Javy 17 w projektach produkcyjnych"],
    "nice_to_have": ["doświadczenie z Apache Kafka"],
    "offer": [],
}


def _model(monkeypatch, *, reply: dict | None = None, error: Exception | None = None):
    calls: list[dict] = []

    class _Block:
        type = "text"
        text = json.dumps(reply if reply is not None else _MODEL_REPLY)

    class _Message:
        content = [_Block()]

    def fake_call_claude(**kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return _Message()

    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda model: True
    )
    monkeypatch.setattr("app.services.claude_client.call_claude", fake_call_claude)
    return calls


def _no_model(monkeypatch):
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda model: False
    )


async def _seed_role_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"jobad-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Ad"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Osoba Testowa{unique}",
                role=role,
                is_active=True,
            )
        )
        await db.commit()
    return email, password


async def _client_name(job_id: int) -> str:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        client = await db.get(Client, job.client_id)
        return client.name


@pytest_asyncio.fixture(autouse=True)
async def _default_fixed_blocks():
    """Stałe bloki są globalne — każdy test startuje od domyślnych."""
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AppSetting).where(AppSetting.key == fixed_blocks.BLOCKS_KEY)
        )
        await db.commit()


# ── Odczyt i pierwsze przygotowanie ─────────────────────────────────────────


async def test_job_without_an_ad_returns_facts_and_no_content(api: AsyncClient):
    _, headers, job_id = await _owner_with_job(api)
    resp = await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ad"] is None and body["rendered"] is None
    assert body["can_copy"] is False
    assert {"key": "city", "label": "Miasto", "value": "Warszawa"} in body["facts"]
    ready = {r["key"]: r["present"] for r in body["readiness"]}
    assert ready["must"] is True and ready["about"] is False


async def test_generate_saves_the_model_content_without_client_or_rate(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    calls = _model(monkeypatch)
    resp = await api.post(
        f"/api/jobs/{job_id}/portal-ad/generate", json={"lang": "pl"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ad"]["source"] == "ai" and body["ad"]["stale"] is False
    assert body["ad"]["content"]["about"] == _MODEL_REPLY["about"]
    # Tytuł i warunki idą z rekrutacji, nie z modelu.
    assert body["ad"]["content"]["start"] == "10.2026"
    assert body["rendered"]["title"].endswith("(k/m/x)")
    assert body["can_copy"] is True
    assert len(calls) == 1

    # KSZTAŁT odpowiedzi: ani prompt, ani żadne pole nie niesie klienta i stawki.
    # Znaczniki czasu odpadają — mikrosekundy mogłyby przypadkiem dać „175”.
    # Imiona w kanałach przypomnień (0526) też: konta testowe mają losowy
    # przyrostek szesnastkowy („Opiekun 8175231e” w CI 27.10.2026).
    reminders = body["reminders"]
    shape = {
        **body,
        "ad": {**body["ad"], "generated_at": None, "updated_at": None},
        "reminders": {
            **reminders,
            "recruiter_names": ["osoba"] * len(reminders["recruiter_names"]),
            "channels": [
                {**c, "owner_names": ["osoba"] * len(c["owner_names"])}
                for c in reminders["channels"]
            ],
        },
    }
    client_name = await _client_name(job_id)
    for text in (
        json.dumps(shape, ensure_ascii=False),
        json.dumps(calls[0]["messages"], ensure_ascii=False),
    ):
        assert client_name not in text and "sekretny opis" not in text
        assert "175" not in text and "180" not in text

    again = await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)
    assert again.json()["ad"]["content"] == body["ad"]["content"]


async def test_first_ad_without_a_model_is_a_labelled_template(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    _no_model(monkeypatch)
    resp = await api.post(
        f"/api/jobs/{job_id}/portal-ad/generate", json={"lang": "pl"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    ad = resp.json()["ad"]
    assert ad["source"] == "template"
    assert ad["content"]["requirements"] == ["Java 17"]
    assert ad["content"]["lead"] == ""
    # Złożenie nie zostawia „[uzupełnij]” w tym, co idzie do schowka
    # (komunikaty kontroli mogą radzić „uzupełnij Profil Championa”).
    body = resp.json()
    copied = json.dumps([ad["content"], body["rendered"]], ensure_ascii=False)
    assert "uzupełnij" not in copied.lower()


async def test_model_failure_never_replaces_a_saved_ad(api: AsyncClient, monkeypatch):
    _, headers, job_id = await _owner_with_job(api)
    _model(monkeypatch)
    first = await api.post(
        f"/api/jobs/{job_id}/portal-ad/generate", json={"lang": "pl"}, headers=headers
    )
    saved = first.json()["ad"]

    _model(monkeypatch, error=RuntimeError("529 overloaded_error"))
    failed = await api.post(
        f"/api/jobs/{job_id}/portal-ad/generate",
        json={"lang": "pl", "expected_updated_at": saved["updated_at"]},
        headers=headers,
    )
    assert failed.status_code == 503, failed.text
    assert "bez zmian" in failed.json()["detail"]

    after = await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)
    assert after.json()["ad"]["content"] == saved["content"]
    assert after.json()["ad"]["source"] == "ai"


async def test_english_ad_is_not_assembled_without_a_model(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    _no_model(monkeypatch)
    resp = await api.post(
        f"/api/jobs/{job_id}/portal-ad/generate", json={"lang": "en"}, headers=headers
    )
    assert resp.status_code == 503, resp.text
    async with AsyncSessionLocal() as db:
        assert await db.get(JobAd, job_id) is None


async def test_english_ad_takes_translated_terms_from_the_model(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    _model(
        monkeypatch,
        reply={
            **_MODEL_REPLY,
            "start": "October 2026",
            "duration": "12+ months",
            "language": "English",
        },
    )
    resp = await api.post(
        f"/api/jobs/{job_id}/portal-ad/generate", json={"lang": "en"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    content = resp.json()["ad"]["content"]
    assert (content["start"], content["duration"]) == ("October 2026", "12+ months")
    # Rekrutacja nie ma języka pracy — model nie może go dopisać.
    assert content["language"] == ""
    assert resp.json()["rendered"]["title"].endswith("(f/m/x)")


# ── Poprawki rekrutera i kontrola ───────────────────────────────────────────


async def _generated(api: AsyncClient, headers, job_id: int, monkeypatch) -> dict:
    _model(monkeypatch)
    resp = await api.post(
        f"/api/jobs/{job_id}/portal-ad/generate", json={"lang": "pl"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["ad"]


async def test_edit_before_generate_is_404(api: AsyncClient):
    _, headers, job_id = await _owner_with_job(api)
    resp = await api.put(
        f"/api/jobs/{job_id}/portal-ad",
        json={"content": {"about": "Opis."}, "tech": []},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_edit_reruns_the_check_and_blocks_on_the_client_name(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    ad = await _generated(api, headers, job_id, monkeypatch)
    client_name = await _client_name(job_id)
    content = {**ad["content"], "about": f"System rozliczeń klienta {client_name}."}
    resp = await api.put(
        f"/api/jobs/{job_id}/portal-ad",
        json={
            "content": content,
            "tech": ad["tech"],
            "expected_updated_at": ad["updated_at"],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["can_copy"] is False
    assert [(f["code"], f["severity"], f["field"]) for f in body["findings"]][0] == (
        "client_name",
        "block",
        "about",
    )
    # Poprawka usuwa blokadę.
    fixed = await api.put(
        f"/api/jobs/{job_id}/portal-ad",
        json={
            "content": {**content, "about": "System rozliczeń w sektorze bankowym."},
            "tech": ad["tech"],
            "expected_updated_at": body["ad"]["updated_at"],
        },
        headers=headers,
    )
    assert fixed.status_code == 200 and fixed.json()["can_copy"] is True


async def test_display_and_legal_client_names_block_too(api: AsyncClient, monkeypatch):
    _, headers, job_id = await _owner_with_job(api)
    ad = await _generated(api, headers, job_id, monkeypatch)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        client = await db.get(Client, job.client_id)
        client.display_name = "Granitowy Dom Maklerski"
        client.legal_name = "Granitowy Holding Spółka Akcyjna"
        await db.commit()
    for name in ("Granitowy Dom Maklerski", "Granitowy Holding"):
        resp = await api.put(
            f"/api/jobs/{job_id}/portal-ad",
            json={
                "content": {**ad["content"], "lead": f"Projekt dla {name}."},
                "tech": ad["tech"],
            },
            headers=headers,
        )
        codes = [(f["code"], f["field"]) for f in resp.json()["findings"]]
        assert ("client_name", "lead") in codes, name


async def test_city_from_the_recruitment_is_checked(api: AsyncClient, monkeypatch):
    _, headers, job_id = await _owner_with_job(api)
    await _generated(api, headers, job_id, monkeypatch)
    client_name = await _client_name(job_id)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.location = f"Warszawa, biuro {client_name}"
        await db.commit()
    body = (await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)).json()
    assert ("client_name", "terms") in [
        (f["code"], f["field"]) for f in body["findings"]
    ]
    assert body["can_copy"] is False
    # Zmiana rekrutacji po przygotowaniu ogłoszenia jest widoczna.
    assert body["ad"]["stale"] is True


async def test_stale_edit_is_409(api: AsyncClient, monkeypatch):
    _, headers, job_id = await _owner_with_job(api)
    ad = await _generated(api, headers, job_id, monkeypatch)
    payload = {"content": ad["content"], "tech": ad["tech"]}
    first = await api.put(
        f"/api/jobs/{job_id}/portal-ad",
        json={**payload, "expected_updated_at": ad["updated_at"]},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    second = await api.put(
        f"/api/jobs/{job_id}/portal-ad",
        json={**payload, "expected_updated_at": ad["updated_at"]},
        headers=headers,
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "job_ad_changed"


def _slow_model(monkeypatch, meanwhile, *, source: str = SOURCE_AI):
    """Model „liczy”, a w tym czasie ktoś inny zapisuje ogłoszenie
    (``meanwhile`` — osobna sesja, zatwierdzona przed odpowiedzią modelu)."""

    async def fake_generate_content(db, mat, **kwargs):
        await meanwhile()
        return (
            generate.clean_content({"about": "Treść z modelu."}, title=mat.title),
            source,
        )

    monkeypatch.setattr(generate, "generate_content", fake_generate_content)


async def test_regenerate_keeps_an_edit_saved_while_the_model_was_working(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    ad = await _generated(api, headers, job_id, monkeypatch)

    async def someone_edits():
        async with AsyncSessionLocal() as db:
            row = await db.get(JobAd, job_id)
            row.content = {**row.content, "about": "Poprawka innej osoby."}
            row.updated_at = datetime.now(timezone.utc)
            await db.commit()

    _slow_model(monkeypatch, someone_edits)
    resp = await api.post(
        f"/api/jobs/{job_id}/portal-ad/generate",
        json={"lang": "pl", "expected_updated_at": ad["updated_at"]},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "job_ad_changed"
    after = await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)
    assert after.json()["ad"]["content"]["about"] == "Poprawka innej osoby."


async def test_template_never_replaces_an_ad_created_while_the_model_was_failing(
    api: AsyncClient, monkeypatch
):
    """Rekrutacja bez ogłoszenia: A klika „Przygotuj”, model pada, a B w tym
    czasie przygotowuje ogłoszenie. Złożenie A nie może go zastąpić."""
    owner_id, headers, job_id = await _owner_with_job(api)

    async def someone_generates():
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            db.add(
                JobAd(
                    job_id=job_id,
                    lang="pl",
                    content=generate.clean_content(
                        {"about": "Ogłoszenie innej osoby."}, title="Java Developer"
                    ),
                    tech=[],
                    source=SOURCE_AI,
                    material_hash="x",
                    generated_by=owner_id,
                    generated_at=now,
                    updated_by=owner_id,
                    updated_at=now,
                )
            )
            await db.commit()

    _slow_model(monkeypatch, someone_generates, source=SOURCE_TEMPLATE)
    resp = await api.post(
        f"/api/jobs/{job_id}/portal-ad/generate", json={"lang": "pl"}, headers=headers
    )
    assert resp.status_code == 409, resp.text
    after = (await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)).json()
    assert after["ad"]["source"] == "ai"
    assert after["ad"]["content"]["about"] == "Ogłoszenie innej osoby."


async def test_regenerate_from_a_stale_window_is_409_before_the_model_is_called(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    ad = await _generated(api, headers, job_id, monkeypatch)
    edited = await api.put(
        f"/api/jobs/{job_id}/portal-ad",
        json={"content": ad["content"], "tech": ad["tech"]},
        headers=headers,
    )
    assert edited.status_code == 200, edited.text

    calls = _model(monkeypatch)
    resp = await api.post(
        f"/api/jobs/{job_id}/portal-ad/generate",
        json={"lang": "pl", "expected_updated_at": ad["updated_at"]},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert calls == []


async def test_edit_rejects_too_many_items_instead_of_trimming(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    ad = await _generated(api, headers, job_id, monkeypatch)
    resp = await api.put(
        f"/api/jobs/{job_id}/portal-ad",
        json={
            "content": {**ad["content"], "offer": [f"punkt {i}" for i in range(7)]},
            "tech": ad["tech"],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert "najwyżej 6" in resp.json()["detail"]


async def test_pasted_offer_list_keeps_only_the_own_points(
    api: AsyncClient, monkeypatch
):
    """Zgłoszenie 28.10.2026: wklejona cała lista z karty (warunki + stały blok
    + własny punkt) dawała 422 po angielsku. Kopie tego, co ogłoszenie dokłada
    samo, nie liczą się do limitu i nie zapisują się drugi raz."""
    _, headers, job_id = await _owner_with_job(api)
    ad = await _generated(api, headers, job_id, monkeypatch)
    blocks = fixed_blocks.DEFAULTS
    card = next(
        f
        for f in (
            await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)
        ).json()["rendered"]["pracuj"]["fields"]
        if f["key"] == "offer"
    )
    pasted = [*card["items"], "praca przy dużym projekcie"]
    assert len(pasted) > 6
    resp = await api.put(
        f"/api/jobs/{job_id}/portal-ad",
        json={
            "content": {
                **ad["content"],
                "offer": pasted,
                "offer_hidden": [blocks.pl.offer[0]],
            },
            "tech": ad["tech"],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ad"]["content"]["offer"] == ["praca przy dużym projekcie"]
    offer = next(f for f in body["rendered"]["pracuj"]["fields"] if f["key"] == "offer")
    assert offer["hidden_fixed"] == [blocks.pl.offer[0]]
    assert blocks.pl.offer[0] not in offer["items"]


# ── Oznaczenie publikacji (0432) ────────────────────────────────────────────

_PRACUJ_URL = "https://www.pracuj.pl/praca/java-developer-warszawa,oferta,1004"


def _publication(body: dict, portal: str) -> dict | None:
    return next((p for p in body["publications"] if p["portal"] == portal), None)


async def test_marking_published_keeps_the_link_and_who_did_it(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    await _generated(api, headers, job_id, monkeypatch)
    before = await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)
    assert before.json()["publications"] == []

    resp = await api.put(
        f"/api/jobs/{job_id}/portal-ad/publications/pracuj",
        json={"url": _PRACUJ_URL},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    pracuj = _publication(resp.json(), "pracuj")
    assert pracuj["url"] == _PRACUJ_URL
    assert pracuj["outdated"] is False
    assert pracuj["removed_at"] is None
    assert pracuj["published_by_name"]
    assert _publication(resp.json(), "jjit") is None


async def test_an_edit_after_publication_marks_it_outdated_until_marked_again(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    ad = await _generated(api, headers, job_id, monkeypatch)
    base = f"/api/jobs/{job_id}/portal-ad"
    marked = await api.put(f"{base}/publications/jjit", json={}, headers=headers)
    assert marked.status_code == 200, marked.text
    assert _publication(marked.json(), "jjit")["url"] is None

    edited = await api.put(
        base,
        json={
            "content": {**ad["content"], "about": "Opis po poprawce."},
            "tech": ad["tech"],
        },
        headers=headers,
    )
    assert _publication(edited.json(), "jjit")["outdated"] is True

    again = await api.put(
        f"{base}/publications/jjit", json={"content_updated": True}, headers=headers
    )
    assert _publication(again.json(), "jjit")["outdated"] is False


async def test_adding_a_link_does_not_confirm_the_content_or_change_who_published(
    api: AsyncClient, monkeypatch
):
    """Ogłoszenie na Pracuj.pl bywa widoczne po moderacji: rekruter oznacza
    publikację bez linku, a link dopisuje później. To nie jest potwierdzenie,
    że treść na portalu jest aktualna."""
    _, headers, job_id = await _owner_with_job(api)
    ad = await _generated(api, headers, job_id, monkeypatch)
    base = f"/api/jobs/{job_id}/portal-ad"
    first = _publication(
        (await api.put(f"{base}/publications/jjit", json={}, headers=headers)).json(),
        "jjit",
    )
    await api.put(
        base,
        json={
            "content": {**ad["content"], "about": "Opis po poprawce."},
            "tech": ad["tech"],
        },
        headers=headers,
    )

    link = "https://justjoin.it/job-offer/przyklad-java-developer"
    linked = await api.put(
        f"{base}/publications/jjit", json={"url": link}, headers=headers
    )
    assert linked.status_code == 200, linked.text
    after = _publication(linked.json(), "jjit")
    assert after["url"] == link
    assert after["outdated"] is True
    assert after["published_at"] == first["published_at"]
    assert after["published_by_name"] == first["published_by_name"]

    confirmed = await api.put(
        f"{base}/publications/jjit",
        json={"url": link, "content_updated": True},
        headers=headers,
    )
    done = _publication(confirmed.json(), "jjit")
    assert done["outdated"] is False
    # Ogłoszenie wisi od pierwszego oznaczenia — aktualizacja tej daty nie rusza.
    assert done["published_at"] == first["published_at"]


async def test_removed_publication_leaves_a_trace_and_can_come_back(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    await _generated(api, headers, job_id, monkeypatch)
    url = f"/api/jobs/{job_id}/portal-ad/publications/pracuj"
    assert (await api.delete(url, headers=headers)).status_code == 404
    await api.put(url, json={"url": _PRACUJ_URL}, headers=headers)

    removed = await api.delete(url, headers=headers)
    assert removed.status_code == 200, removed.text
    pracuj = _publication(removed.json(), "pracuj")
    assert pracuj["removed_at"] is not None
    assert pracuj["outdated"] is False
    # Drugi raz nie ma czego zdejmować.
    assert (await api.delete(url, headers=headers)).status_code == 404

    back = await api.put(url, json={"url": _PRACUJ_URL}, headers=headers)
    assert _publication(back.json(), "pracuj")["removed_at"] is None


async def test_publication_needs_an_ad_a_portal_link_and_clean_content(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    base = f"/api/jobs/{job_id}/portal-ad"
    no_ad = await api.put(f"{base}/publications/pracuj", json={}, headers=headers)
    assert no_ad.status_code == 404

    ad = await _generated(api, headers, job_id, monkeypatch)
    for portal, url in (
        ("pracuj", "https://justjoin.it/job-offer/x"),
        ("jjit", "https://justjoin.it.przyklad.example/x"),
    ):
        wrong = await api.put(
            f"{base}/publications/{portal}", json={"url": url}, headers=headers
        )
        assert wrong.status_code == 422, wrong.text
    unknown = await api.put(f"{base}/publications/olx", json={}, headers=headers)
    assert unknown.status_code == 422

    client_name = await _client_name(job_id)
    await api.put(
        base,
        json={
            "content": {**ad["content"], "about": f"Projekt dla {client_name}."},
            "tech": ad["tech"],
        },
        headers=headers,
    )
    blocked = await api.put(f"{base}/publications/pracuj", json={}, headers=headers)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["code"] == "job_ad_blocked"


async def test_blocked_content_cannot_be_confirmed_but_the_link_can_change(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    ad = await _generated(api, headers, job_id, monkeypatch)
    base = f"/api/jobs/{job_id}/portal-ad"
    await api.put(f"{base}/publications/pracuj", json={}, headers=headers)
    client_name = await _client_name(job_id)
    await api.put(
        base,
        json={
            "content": {**ad["content"], "about": f"Projekt dla {client_name}."},
            "tech": ad["tech"],
        },
        headers=headers,
    )

    confirm = await api.put(
        f"{base}/publications/pracuj", json={"content_updated": True}, headers=headers
    )
    assert confirm.status_code == 409, confirm.text
    linked = await api.put(
        f"{base}/publications/pracuj", json={"url": _PRACUJ_URL}, headers=headers
    )
    assert linked.status_code == 200, linked.text
    assert _publication(linked.json(), "pracuj")["outdated"] is True


async def test_jobs_list_and_detail_carry_only_active_publications(
    api: AsyncClient, monkeypatch
):
    owner_id, headers, job_id = await _owner_with_job(api)
    await _generated(api, headers, job_id, monkeypatch)
    base = f"/api/jobs/{job_id}/portal-ad/publications"
    await api.put(f"{base}/pracuj", json={"url": _PRACUJ_URL}, headers=headers)
    await api.put(f"{base}/jjit", json={}, headers=headers)
    await api.delete(f"{base}/jjit", headers=headers)

    detail = await api.get(f"/api/jobs/{job_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    expected = [{"portal": "pracuj", "url": _PRACUJ_URL, "outdated": False}]
    assert detail.json()["ad_publications"] == expected

    listing = await api.get(
        "/api/jobs", params={"owner_id": owner_id, "page_size": 100}, headers=headers
    )
    assert listing.status_code == 200, listing.text
    rows = {row["id"]: row for row in listing.json()["items"]}
    assert rows[job_id]["ad_publications"] == expected


# ── Strona kariery z ogłoszenia (21.10.2026) ────────────────────────────────


async def test_publish_career_page_from_the_ad_goes_live_with_own_link(
    api: AsyncClient, monkeypatch
):
    owner_id, headers, job_id = await _owner_with_job(api)
    ad = await _generated(api, headers, job_id, monkeypatch)
    base = f"/api/jobs/{job_id}/portal-ad"
    before = await api.get(base, headers=headers)
    assert before.json()["career"] == {
        "status": "none",
        "url": None,
        "published_at": None,
        "published_by_name": None,
    }

    resp = await api.post(
        f"{base}/career",
        json={"expected_updated_at": ad["updated_at"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    career = resp.json()["career"]
    assert career["status"] == "live"
    assert career["published_by_name"]
    slug = career["url"].rstrip("/").rsplit("/", 1)[-1]

    page = await api.get(f"/api/public/career/r/{slug}")
    assert page.status_code == 200, page.text
    job = page.json()["job"]
    assert job["subtitle"] == _MODEL_REPLY["lead"].rstrip(".")
    assert job["about"].startswith(_MODEL_REPLY["about"])
    assert (
        "Czym się zajmiesz: rozwój mikroserwisów w Javie; przeglądy kodu."
        in job["about"]
    )
    # „Wymagane” = punkty ogłoszenia, nie słowa do szukania (29.10.2026).
    assert job["must"] == [{"name": _MODEL_REPLY["requirements"][0], "note": None}]
    assert job["nice"] == _MODEL_REPLY["nice_to_have"]

    # Opis w oknie „Udostępnij” to ta sama treść — zatwierdzona.
    profile = await api.get(f"/api/jobs/{job_id}/public-profile", headers=headers)
    assert profile.json()["status"] == "approved"

    listing = await api.get(
        "/api/jobs", params={"owner_id": owner_id, "page_size": 100}, headers=headers
    )
    rows = {row["id"]: row for row in listing.json()["items"]}
    assert rows[job_id]["career_page"] is True


async def test_changed_ad_marks_the_career_page_outdated_until_republished(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    ad = await _generated(api, headers, job_id, monkeypatch)
    base = f"/api/jobs/{job_id}/portal-ad"
    await api.post(f"{base}/career", json={}, headers=headers)

    edited = await api.put(
        base,
        json={
            "content": {**ad["content"], "lead": "Nowy wstęp do ogłoszenia."},
            "tech": ad["tech"],
        },
        headers=headers,
    )
    assert edited.json()["career"]["status"] == "outdated"
    url = edited.json()["career"]["url"]
    # Strona dalej pokazuje opublikowaną wersję — nikt nie dostaje 404.
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    page = await api.get(f"/api/public/career/r/{slug}")
    assert page.json()["job"]["subtitle"] == _MODEL_REPLY["lead"].rstrip(".")

    again = await api.post(f"{base}/career", json={}, headers=headers)
    assert again.status_code == 200, again.text
    assert again.json()["career"]["status"] == "live"
    assert again.json()["career"]["url"] == url
    page = await api.get(f"/api/public/career/r/{slug}")
    assert page.json()["job"]["subtitle"] == "Nowy wstęp do ogłoszenia"


async def test_changed_ad_requirements_mark_the_career_page_outdated(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    ad = await _generated(api, headers, job_id, monkeypatch)
    base = f"/api/jobs/{job_id}/portal-ad"
    published = await api.post(f"{base}/career", json={}, headers=headers)
    slug = published.json()["career"]["url"].rstrip("/").rsplit("/", 1)[-1]

    point = "Doświadczenie w zarządzaniu projektami w sektorze bankowym"
    edited = await api.put(
        base,
        json={
            "content": {**ad["content"], "requirements": [point]},
            "tech": ad["tech"],
        },
        headers=headers,
    )
    assert edited.json()["career"]["status"] == "outdated"

    again = await api.post(f"{base}/career", json={}, headers=headers)
    assert again.json()["career"]["status"] == "live"
    page = await api.get(f"/api/public/career/r/{slug}")
    assert page.json()["job"]["must"] == [{"name": point, "note": None}]


async def test_career_page_refuses_internal_code_in_ad_requirements(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    ad = await _generated(api, headers, job_id, monkeypatch)
    base = f"/api/jobs/{job_id}/portal-ad"
    await api.put(
        base,
        json={
            "content": {
                **ad["content"],
                "requirements": ["Doświadczenie z RITM0866775"],
            },
            "tech": ad["tech"],
        },
        headers=headers,
    )
    internal = await api.post(f"{base}/career", json={}, headers=headers)
    assert internal.status_code == 422, internal.text
    assert internal.json()["detail"]["code"] == "PUBLIC_PROFILE_FINDINGS"


async def test_career_page_refuses_blocked_stale_or_internal_content(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    base = f"/api/jobs/{job_id}/portal-ad"
    no_ad = await api.post(f"{base}/career", json={}, headers=headers)
    assert no_ad.status_code == 404

    ad = await _generated(api, headers, job_id, monkeypatch)
    stale = await api.post(
        f"{base}/career",
        json={"expected_updated_at": "2020-01-01T00:00:00+00:00"},
        headers=headers,
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "job_ad_changed"

    client_name = await _client_name(job_id)
    await api.put(
        base,
        json={
            "content": {**ad["content"], "about": f"Projekt dla {client_name}."},
            "tech": ad["tech"],
        },
        headers=headers,
    )
    blocked = await api.post(f"{base}/career", json={}, headers=headers)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["code"] == "job_ad_blocked"

    # Numer zgłoszenia ogłoszenie tylko odradza, strona kariery odmawia.
    await api.put(
        base,
        json={
            "content": {
                **ad["content"],
                "about": "Zgłoszenie RITM0866775 dla zespołu.",
            },
            "tech": ad["tech"],
        },
        headers=headers,
    )
    internal = await api.post(f"{base}/career", json={}, headers=headers)
    assert internal.status_code == 422, internal.text
    assert internal.json()["detail"]["code"] == "PUBLIC_PROFILE_FINDINGS"
    profile = await api.get(f"/api/jobs/{job_id}/public-profile", headers=headers)
    assert profile.json()["status"] == "none"


async def test_career_publish_keeps_section_toggles_saved_meanwhile(
    api: AsyncClient, monkeypatch
):
    """Opis wczytany przed blokadą wiersza nie może nadpisać przełączników,
    które ktoś zapisał w oknie „Udostępnij” w tym samym czasie."""
    owner_id, headers, job_id = await _owner_with_job(api)
    await _generated(api, headers, job_id, monkeypatch)
    sections = {"must": True, "nice": True, "params": True, "process": True}
    first = await api.put(
        f"/api/jobs/{job_id}/public-profile",
        json={"subtitle": "Stary podtytuł", "sections": sections},
        headers=headers,
    )
    assert first.status_code == 200, first.text

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        ad = await db.get(JobAd, job_id)
        # Ta sesja widzi opis sprzed zmiany drugiej osoby.
        assert await db.get(JobPublicProfile, job_id) is not None
        toggled = await api.put(
            f"/api/jobs/{job_id}/public-profile",
            json={"sections": {**sections, "nice": False}},
            headers=headers,
        )
        assert toggled.status_code == 200, toggled.text
        await career.publish(db, job, ad, user_id=owner_id)
        await db.commit()

    profile = await api.get(f"/api/jobs/{job_id}/public-profile", headers=headers)
    body = profile.json()
    assert body["sections"]["nice"] is False
    assert body["status"] == "approved"


# ── Zaległe: kolejka i nocne przygotowanie (21.10.2026) ─────────────────────


async def _queue(api: AsyncClient, headers, scope: str = "mine") -> dict:
    resp = await api.get(
        "/api/job-ads/career-queue", params={"scope": scope}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_career_queue_lists_open_jobs_without_a_page_until_published(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    body = await _queue(api, headers)
    items = {item["job_id"]: item for item in body["items"]}
    assert items[job_id]["ad"] == "missing"
    assert items[job_id]["city"] == "Warszawa"
    assert body["mine_count"] >= 1 and body["all_count"] >= body["mine_count"]
    # Kształt wiersza jest zamknięty — nowe pole = świadoma decyzja.
    assert set(items[job_id]) == {
        "job_id",
        "title",
        "city",
        "remote_policy",
        "delivery_lead_name",
        "opened_at",
        "ad",
    }

    await _generated(api, headers, job_id, monkeypatch)
    items = {item["job_id"]: item for item in (await _queue(api, headers))["items"]}
    assert items[job_id]["ad"] == "ready"

    published = await api.post(
        f"/api/jobs/{job_id}/portal-ad/career", json={}, headers=headers
    )
    assert published.status_code == 200, published.text
    after = await _queue(api, headers, "all")
    assert job_id not in {item["job_id"] for item in after["items"]}


async def test_nightly_prepare_writes_a_first_version_and_never_replaces_one(
    api: AsyncClient, monkeypatch
):
    _, headers, job_id = await _owner_with_job(api)
    _no_model(monkeypatch)
    async with AsyncSessionLocal() as db:
        assert job_id in await prepare.missing_job_ids(db, limit=10_000)
        assert await prepare.prepare_one(db, job_id) is True
        await db.commit()

    ad = (await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)).json()
    assert ad["ad"]["source"] == "template"
    items = {item["job_id"]: item for item in (await _queue(api, headers))["items"]}
    assert items[job_id]["ad"] == "template"

    async with AsyncSessionLocal() as db:
        assert await prepare.prepare_one(db, job_id) is False
        assert job_id not in await prepare.missing_job_ids(db, limit=10_000)
    again = (await api.get(f"/api/jobs/{job_id}/portal-ad", headers=headers)).json()
    assert again["ad"]["updated_at"] == ad["ad"]["updated_at"]


# ── Dostęp ──────────────────────────────────────────────────────────────────


async def test_missing_job_is_404_and_viewer_is_denied(api: AsyncClient):
    _, headers, job_id = await _owner_with_job(api)
    assert (
        await api.get("/api/jobs/999999999/portal-ad", headers=headers)
    ).status_code == 404
    email, password = await _seed_role_user(UserRole.user)
    viewer = await _login(api, email, password)
    assert (
        await api.get(f"/api/jobs/{job_id}/portal-ad", headers=viewer)
    ).status_code == 403
    assert (await api.get(f"/api/jobs/{job_id}/portal-ad")).status_code == 401
    publication = f"/api/jobs/{job_id}/portal-ad/publications/pracuj"
    assert (await api.put(publication, json={}, headers=viewer)).status_code == 403
    assert (await api.delete(publication, headers=viewer)).status_code == 403


# ── Stałe części ogłoszenia ─────────────────────────────────────────────────


async def test_fixed_blocks_are_for_admin_and_head_of_recruitment(api: AsyncClient):
    _, recruiter, _job_id = await _owner_with_job(api)
    assert (
        await api.get("/api/job-ads/fixed-blocks", headers=recruiter)
    ).status_code == 403
    for role in (UserRole.admin, UserRole.head_of_recruitment):
        headers = await _login(api, *await _seed_role_user(role))
        resp = await api.get("/api/job-ads/fixed-blocks", headers=headers)
        assert resp.status_code == 200, (role, resp.text)
        assert resp.json() == fixed_blocks.DEFAULTS.as_dict()


async def test_saved_fixed_blocks_reach_every_ad(api: AsyncClient, monkeypatch):
    _, recruiter, job_id = await _owner_with_job(api)
    await _generated(api, recruiter, job_id, monkeypatch)
    admin = await _login(api, *await _seed_role_user(UserRole.admin))
    blocks = {
        "title_suffix": "km",
        "pl": {
            "offer": ["karta sportowa"],
            "process": ["Rozmowa z rekruterem"],
            "about": "Łączymy specjalistów z projektami.",
        },
        "en": {"offer": [], "process": [], "about": ""},
    }
    saved = await api.put("/api/job-ads/fixed-blocks", json=blocks, headers=admin)
    assert saved.status_code == 200, saved.text

    body = (await api.get(f"/api/jobs/{job_id}/portal-ad", headers=recruiter)).json()
    assert body["rendered"]["title"].endswith("(k/m)")
    offer = next(f for f in body["rendered"]["pracuj"]["fields"] if f["key"] == "offer")
    assert offer["items"][-1] == "karta sportowa" and offer["fixed_count"] == 1
    assert "Łączymy specjalistów z projektami." in body["rendered"]["jjit"]["body_text"]


async def test_fixed_blocks_refuse_amounts_and_contacts(api: AsyncClient):
    admin = await _login(api, *await _seed_role_user(UserRole.admin))
    base = fixed_blocks.DEFAULTS.as_dict()
    for bad in ("premia 500 zł za polecenie", "pisz na rekrutacja@example.com"):
        resp = await api.put(
            "/api/job-ads/fixed-blocks",
            json={**base, "pl": {**base["pl"], "offer": [bad]}},
            headers=admin,
        )
        assert resp.status_code == 422, bad
    unchanged = await api.get("/api/job-ads/fixed-blocks", headers=admin)
    assert unchanged.json() == base
