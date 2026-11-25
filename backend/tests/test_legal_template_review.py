"""„Przejrzyj wzór” (asystent prawny, część H): cytaty wzorów, dopasowanie, zadania.

Bez bazy: wyciąganie cytatów z szablonów repo i fikcyjnych wzorów, dopasowanie
do zmian wersji aktu, teksty zadań i brak powtórek. Zapis do ``law_changes``
(drugi przebieg bez duplikatów, zamknięta zmiana nietknięta) sprawdza test
z Postgresem na końcu pliku — lokalnie bez bazy pada na połączeniu, w CI
biegnie na bazie testowej.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from app.services.legal import template_review as tr
from app.services.legal.corpus import VersionChange

NOW = datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc)


def _change(act_key: str = "kc", **lists: list[str]) -> VersionChange:
    return VersionChange(
        act_key=act_key,
        version_id=lists.pop("version_id", 101),  # type: ignore[arg-type]
        version_ident="DU/2099/1234",
        previous_ident="DU/2098/77",
        valid_from=date(2099, 1, 15),
        created_at=NOW,
        added=lists.get("added", []),
        removed=lists.get("removed", []),
        changed=lists.get("changed", []),
    )


FICTIONAL = tr.TemplateSource(
    "custom/1",
    "Umowa testowa o szkolenie (wzór własny)",
    "Zgodnie z art. 61 § 1 KC oświadczenie dochodzi do adresata. Partner nie "
    "pozostaje w stosunku pracy w rozumieniu art. 22.§ 1 Kodeksu pracy. "
    "Ponownie art. 61 § 1 KC. Dane przetwarzamy na podstawie art. 6 ust. 1 lit. b RODO "
    "oraz art. 32 RODO. Odwołanie bez aktu: art. 5.",
)


def _cited(*sources: tr.TemplateSource) -> list[tr.TemplateCitation]:
    return tr.template_citations(sources or (FICTIONAL,))


# ── cytaty wzorów ───────────────────────────────────────────────────────────


def test_fictional_template_citations_are_mapped_once_per_template() -> None:
    found = {(c.act_key, c.key, c.ref) for c in _cited()}
    assert found == {
        ("kc", "61 §1", "art. 61 § 1"),
        # „22.§ 1” z kropką (jak w umowie B2B) też jest odwołaniem do KP.
        ("kp", "22 §1", "art. 22 § 1"),
        ("rodo", "6 ust.1 lit.b", "art. 6 ust. 1 lit. b"),
        ("rodo", "32", "art. 32"),
    }
    assert len(_cited()) == 4  # art. 61 § 1 KC dwa razy = jeden cytat


def test_repo_templates_and_clauses_feed_the_review() -> None:
    repo = tr.repo_template_sources()
    keys = {s.key for s in repo}
    assert "contract/umowa_b2b_pl" in keys
    assert "documents/annex_rate_change_pl" in keys
    # Rewizja sprzed obecnej (plik zostaje dla wydanych dokumentów) nie wchodzi.
    assert "documents/preliminary_cez_pl" not in keys
    assert all("<" not in s.text for s in repo)
    cited = {(c.template_key, c.act_key, c.key) for c in tr.template_citations(repo)}
    assert ("contract/umowa_b2b_pl", "kp", "22 §1") in cited
    assert ("contract/umowa_b2b_pl", "kc", "78^1 §1") in cited
    assert ("documents/annex_rate_change_pl", "kc", "78^1 §1") in cited
    clauses = tr.clause_sources()
    assert clauses and all(s.key.startswith("clauses/") and s.text for s in clauses)


def test_plain_text_drops_tags_styles_and_entities() -> None:
    raw = "<style>p{}</style><p>art.&nbsp;22.§&nbsp;1 <b>Kodeksu pracy</b></p>"
    assert tr.plain_text(raw) == "art. 22 § 1 Kodeksu pracy"


# ── dopasowanie do zmian wersji ─────────────────────────────────────────────


def test_changed_cited_provision_gives_a_plan_with_hits() -> None:
    plan = tr.plan_for_change(
        _change(changed=["61 §1", "700"]),
        _cited(),
        {"url": "https://eli.example/DU/2099/1234", "title": "Kodeks cywilny"},
    )
    assert plan is not None
    assert [(h.act_key, h.ref) for h in plan.hits] == [("kc", "art. 61 § 1")]
    assert plan.act_short == "KC" and plan.url.endswith("1234")


def test_no_plan_when_the_cited_provision_did_not_change() -> None:
    # Inny paragraf tego samego artykułu, artykuł nadrzędny i inny akt.
    assert tr.plan_for_change(_change(changed=["61 §2"]), _cited(), {}) is None
    assert tr.plan_for_change(_change(changed=["61"]), _cited(), {}) is None
    assert tr.plan_for_change(_change("kp", changed=["23 §1"]), _cited(), {}) is None
    assert tr.plan_for_change(_change(), _cited(), {}) is None  # pusta lista zmian


def test_descendants_removed_and_ust_paragraph_variants_count() -> None:
    added = tr.plan_for_change(_change("rodo", added=["32 ust.5"]), _cited(), {})
    assert added is not None and [h.ref for h in added.hits] == ["art. 32"]
    removed = tr.plan_for_change(_change("kp", removed=["22 §1"]), _cited(), {})
    assert removed is not None and [h.ref for h in removed.hits] == ["art. 22 § 1"]
    variant = tr.plan_for_change(_change("rodo", changed=["6 §1 lit.b"]), _cited(), {})
    assert variant is not None


# ── teksty i brak powtórek ──────────────────────────────────────────────────


def _plan(**over) -> tr.ReviewPlan:
    plan = tr.plan_for_change(
        _change(changed=["61 §1"]), _cited(), {"url": "https://x"}
    )
    assert plan is not None
    return plan


def test_task_and_change_texts() -> None:
    plan = _plan()
    assert tr.task_texts(plan) == [
        "Przejrzyj wzór „Umowa testowa o szkolenie (wzór własny)” — zmienił się art. 61 § 1 KC"
    ]
    values = tr.change_values(plan)
    assert values["title"] == "Przejrzyj wzory — nowy tekst KC (DU/2099/1234)"
    assert values["roles"] == ["contracts"] and values["stage"] == "in_force"
    assert values["legal_ref"] == "art. 61 § 1 KC"
    long = tr.TemplateCitation("custom/2", "W" * 400, "kc", "art. 61 § 1", "61 §1")
    text = tr.task_text(long, plan)
    assert len(text) <= 200 and text.endswith("zmienił się art. 61 § 1 KC")


def test_second_run_adds_no_duplicate_tasks() -> None:
    planned = tr.task_texts(_plan())
    assert tr.missing_tasks([], planned) == planned
    assert tr.missing_tasks([t.upper() for t in planned], planned) == []
    assert tr.missing_tasks(
        planned, [*planned, "Przejrzyj wzór „Nowy” — zmienił się art. 1 KC"]
    ) == ["Przejrzyj wzór „Nowy” — zmienił się art. 1 KC"]


def test_item_for_the_version_never_goes_to_the_analyst() -> None:
    values = tr.item_values(_plan(), change_id=7, now=NOW)
    assert values["analyzed_at"] == NOW and values["gate"] == "verified"
    assert values["klass"] == "official" and values["act_ref"] == "DU/2099/1234"
    assert values["fingerprint"] == tr.corpus_fingerprint(101)
    assert len(values["fingerprint"]) == 64


def test_script_refuses_future_since() -> None:
    from scripts import legal_template_review

    assert legal_template_review.main(["--since", "2999-01-01"]) == 2


@pytest.mark.asyncio
async def test_loop_review_failure_does_not_stop_the_corpus_loop(monkeypatch) -> None:
    from app.tasks import legal_corpus as loop

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("brak bazy")

    monkeypatch.setattr(tr, "run", _boom)
    assert await loop.review_templates(NOW) == {"review_tasks": 0}


# ── z bazą (CI) ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_twice_creates_one_change_and_respects_closed_status() -> None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.law_radar import LawChange, LawChangeTask, LawRadarItem

    version_id = 900_000_000 + uuid.uuid4().int % 90_000_000
    plan = tr.plan_for_change(
        _change(changed=["61 §1"], version_id=version_id),  # type: ignore[arg-type]
        _cited(),
        {"url": "https://eli.example/DU/2099/1234", "title": "Kodeks cywilny"},
    )
    assert plan is not None
    async with AsyncSessionLocal() as db:
        first = await tr.apply(db, [plan], now=NOW)
        await db.commit()
    async with AsyncSessionLocal() as db:
        second = await tr.apply(db, [plan], now=NOW)
        await db.commit()
    assert (first.changes_created, first.tasks_added) == (1, 1)
    assert (second.changes_created, second.tasks_added) == (0, 0)
    async with AsyncSessionLocal() as db:
        item = await db.scalar(
            select(LawRadarItem).where(
                LawRadarItem.fingerprint == tr.corpus_fingerprint(version_id)
            )
        )
        assert item is not None and item.analyzed_at is not None
        change = await db.get(LawChange, item.change_id)
        assert change is not None and change.roles == ["contracts"]
        tasks = (
            (
                await db.execute(
                    select(LawChangeTask).where(LawChangeTask.change_id == change.id)
                )
            )
            .scalars()
            .all()
        )
        assert [t.role for t in tasks] == ["contracts"]
        change.status = "done"
        await db.commit()
    wider = tr.ReviewPlan(**{**plan.__dict__, "hits": (*plan.hits, *_cited()[1:2])})
    async with AsyncSessionLocal() as db:
        closed = await tr.apply(db, [wider], now=NOW)
        await db.commit()
    assert (closed.skipped_closed, closed.tasks_added) == (1, 0)
