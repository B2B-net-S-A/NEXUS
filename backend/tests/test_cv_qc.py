"""QC CV (Rekrutacja v5, 0361): automatyczna kontrola CV firmowego.

Decyzje Artura 23.09.2026: ręczny przegląd DZ zastępuje kontrola liczona
przez kod; AI proponuje poprawki (wyłącznie z faktów oryginału i notatek),
rekruter je akceptuje; QC jest twardą bramką przed „CV wysłane”/Cpro,
obejście — Delivery Lead albo admin z powodem.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_qc_run import CvQcRun
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import UserRole
from app.services import cv_qc as qc
from app.services import dz_review as dz
from tests.test_board_tasks import (
    _cleanup,
    _login,
    _move,
    _seed_user,
    _seed_world,
    clear_cpro_sender,
    restore_cpro_sender,
)
from tests.test_dz_review import (
    BRANDED_HTML,
    EXPERIENCE,
    ORIGINAL,
    _cleanup_review,
    _client_docx,
    _seed_review,
)


@pytest_asyncio.fixture
async def api_client():
    from httpx import ASGITransport

    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


def _reqs(*names: str) -> list[dz.Requirement]:
    return [dz.Requirement(label=n, alternatives=(n,), terms=(n,)) for n in names]


def _blocks(html: str) -> list[dz.Block]:
    return dz.html_blocks(html)


def _qc_input(html: str, **extra) -> qc.QcInput:
    base = dict(
        must=_reqs("Java", "Kubernetes"),
        nice=[],
        blocks=_blocks(html),
        has_cv=True,
        bold_known=True,
        original_text=ORIGINAL,
        experience=EXPERIENCE,
        job_title="Senior Java Developer",
    )
    base.update(extra)
    return qc.QcInput(**base)


def _by_key(checks: list[dict]) -> dict[str, dict]:
    return {c["key"]: c for c in checks}


# ── Heurystyka „opis w roli” ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "tech_list"),
    [
        ("Technologie: Java, Spring, Kafka", True),
        ("Stack: Java", True),
        ("Java, Spring Boot, Kafka, Docker, PostgreSQL", True),
        (
            "Rozwijała moduł SEPA w Java 11, Spring Boot i Kafka dla 2 mln klientów",
            False,
        ),
        ("Rozwój usług w Java i Spring.", False),
    ],
)
def test_tech_list_heuristic(text: str, tech_list: bool) -> None:
    assert qc.is_tech_list(text) is tech_list


def test_term_only_in_a_technology_tail_is_not_a_description() -> None:
    req = _reqs("Kafka")[0]
    tail_only = _blocks(
        "<ul><li>Utrzymanie systemu płatności dla banku. Technologie: Kafka, Java</li></ul>"
    )
    sentence = _blocks(
        "<ul><li>Zaprojektował przetwarzanie zdarzeń na Kafka dla systemu płatności.</li></ul>"
    )
    short = _blocks("<ul><li>Kafka i Java.</li></ul>")
    assert not qc.described_in_blocks(req, tail_only)
    assert qc.described_in_blocks(req, sentence)
    assert not qc.described_in_blocks(req, short)


def test_must_in_roles_needs_a_sentence_in_every_role_from_the_original() -> None:
    checks = _by_key(qc.compute_checks(_qc_input(BRANDED_HTML)))
    roles = checks["must_in_roles"]
    assert roles["status"] == "fail"
    missing = {(i["requirement"], i["role"]) for i in roles["items"]}
    # Java opisana zdaniem w Acme, brak w Globex; Kubernetes brak w Acme.
    # Initech wypadł z CV — rola pominięta nie jest brakiem.
    assert missing == {
        ("Java", "Developer · Globex"),
        ("Kubernetes", "Senior Developer · Acme Bank"),
    }
    assert all(i["fix"] == "ai" for i in roles["items"])


def test_technology_list_alone_does_not_satisfy_a_role() -> None:
    html = (
        '<h2 data-cv-section="experience">Doświadczenie</h2>'
        '<p data-cv-section="role"><b>Senior Developer</b> 2021–obecnie</p>'
        '<p data-cv-section="employer">Acme Bank</p>'
        "<ul><li>Utrzymanie aplikacji dla działu płatności.</li></ul>"
        '<p data-cv-section="technologies">Technologie <span>Java, Kubernetes</span></p>'
    )
    checks = _by_key(
        qc.compute_checks(
            _qc_input(html, experience=EXPERIENCE[:1], must=_reqs("Java"))
        )
    )
    item = checks["must_in_roles"]["items"][0]
    assert item["requirement"] == "Java"
    assert "liście technologii" in item["detail"]


# ── Pełna lista sprawdzeń ───────────────────────────────────────────────────


def test_checks_follow_the_contract_order_and_severity() -> None:
    checks = qc.compute_checks(_qc_input(BRANDED_HTML))
    assert [c["key"] for c in checks] == [*qc.BLOCKING_KEYS, *qc.WARNING_KEYS]
    assert {c["severity"] for c in checks[:7]} == {"blocking"}
    assert {c["severity"] for c in checks[7:]} == {"warning"}
    by = _by_key(checks)
    assert by["must_in_cv"]["status"] == "fail"
    assert by["must_in_cv"]["summary"] == "1/2"
    # Kubernetes jest w oryginale — poprawka AI, nie pytanie do kandydata.
    assert by["must_in_cv"]["items"][0]["fix"] == "ai"
    assert by["must_bolded"]["status"] == "pass"
    assert by["dates"]["status"] == "pass"
    assert by["no_unsupported"]["status"] == "pass"
    passed, blocking, warnings = qc.summarize(checks)
    assert not passed and blocking == 2


def test_without_company_cv_only_generate_cv_is_asked_for() -> None:
    checks = qc.compute_checks(_qc_input("", blocks=[], has_cv=False))
    by = _by_key(checks)
    assert by["must_in_cv"]["status"] == "fail"
    assert by["must_in_cv"]["items"][0]["fix"] == "generate_cv"
    assert all(c["status"] == "skip" for c in checks[1:])


def test_pdf_cv_cannot_prove_bolding_so_it_is_manual_not_a_block() -> None:
    by = _by_key(qc.compute_checks(_qc_input(BRANDED_HTML, bold_known=False)))
    assert by["must_bolded"]["status"] == "manual"


def test_claim_missing_from_original_and_notes_is_unsupported() -> None:
    html = (
        "<p>Programista <b>Java</b> i <b>Terraform</b>.</p>"
        '<h2 data-cv-section="experience">Doświadczenie</h2>'
    )
    by = _by_key(
        qc.compute_checks(_qc_input(html, must=_reqs("Java"), nice=_reqs("Terraform")))
    )
    item = by["no_unsupported"]["items"][0]
    assert item["term"] == "Terraform" and item["fix"] == "remove_term"
    # Ta sama technologia w notatkach rekrutera = jest pokrycie.
    by = _by_key(
        qc.compute_checks(
            _qc_input(
                html,
                must=_reqs("Java"),
                nice=_reqs("Terraform"),
                notes_text="Kandydat: Terraform w prywatnych projektach.",
            )
        )
    )
    assert by["no_unsupported"]["status"] == "pass"


def test_unsupported_must_have_asks_the_candidate() -> None:
    html = "<p>Programista <b>Java</b> i <b>Scala</b>.</p>"
    by = _by_key(qc.compute_checks(_qc_input(html, must=_reqs("Java", "Scala"))))
    item = next(i for i in by["no_unsupported"]["items"] if i["term"] == "Scala")
    assert item["fix"] == "ask_candidate"


def test_bolded_phrase_outside_the_original_is_a_warning_not_a_block() -> None:
    # CV po angielsku z polskiego oryginału pogrubia tłumaczenia — to uwaga.
    html = "<p>Programista <b>Java</b>, <b>team leadership</b>.</p>"
    checks = qc.compute_checks(_qc_input(html, must=_reqs("Java")))
    by = _by_key(checks)
    assert by["no_unsupported"]["status"] == "pass"
    assert by["bold_unsupported"]["status"] == "fail"
    assert by["bold_unsupported"]["severity"] == "warning"


# ── Lata, daty, reguły klienta ──────────────────────────────────────────────


def test_years_from_history_merge_overlaps() -> None:
    history = [
        {"company": "A", "start": "2016-01", "end": "2019-12"},
        {"company": "B", "start": "2019-06", "end": "2021-12"},
        {"company": "C", "start": "2022-01", "end": "obecnie"},
    ]
    years = qc.experience_years(history, today=date(2026, 1, 15))
    assert years is not None and int(years) == 10
    assert qc.experience_years([{"company": "X"}]) is None


def test_years_header_tolerates_one_year() -> None:
    blocks = _blocks("<ul><li>Ponad 8 lat doświadczenia komercyjnego w IT.</li></ul>")
    claim = qc.header_years(blocks)
    assert claim is not None and claim[0] == 8 and claim[1] is True
    assert qc.years_consistent(8, True, 7.4)
    assert not qc.years_consistent(8, True, 5.9)
    assert qc.years_consistent(10, False, 9.2)
    assert not qc.years_consistent(12, False, 9.2)
    # Lata w jednej technologii to nie łączny staż.
    assert qc.header_years(_blocks("<ul><li>5 lat w Java i Spring.</li></ul>")) is None


def test_years_header_mismatch_blocks() -> None:
    html = "<ul><li>15 lat doświadczenia w bankowości.</li></ul>" + BRANDED_HTML
    history = [{"company": "A", "start": "2020-01", "end": "2025-12"}]
    by = _by_key(qc.compute_checks(_qc_input(html, experience=history)))
    assert by["years_header"]["status"] == "fail"


def test_role_without_dates_is_reported() -> None:
    html = (
        '<h2 data-cv-section="experience">Doświadczenie</h2>'
        '<p data-cv-section="role"><b>Senior Developer</b></p>'
        '<p data-cv-section="employer">Acme Bank</p>'
        "<ul><li>Rozwój usług w Java dla bankowości detalicznej.</li></ul>"
    )
    by = _by_key(qc.compute_checks(_qc_input(html, must=_reqs("Java"))))
    assert by["dates"]["status"] == "fail"
    assert by["dates"]["items"][0]["role"] == "Senior Developer · Acme Bank"


def test_rates_and_candidate_contact_break_client_rules() -> None:
    html = (
        "<p>Stawka: 160 zł/h netto B2B.</p>"
        "<p>Kontakt: ewa.nowak@example.com, tel. +48 600 100 200</p>" + BRANDED_HTML
    )
    by = _by_key(
        qc.compute_checks(
            _qc_input(
                html,
                candidate_email="Ewa.Nowak@example.com",
                candidate_phone="600-100-200",
            )
        )
    )
    details = " ".join(i["detail"] for i in by["client_rules"]["items"])
    assert by["client_rules"]["status"] == "fail"
    assert "Stawka" in details and "e-mail" in details and "telefon" in details


def test_missing_rodo_consent_asks_for_upload() -> None:
    by = _by_key(qc.compute_checks(_qc_input(BRANDED_HTML, consent="missing")))
    assert by["client_rules"]["items"][0]["fix"] == "upload_consent"
    by = _by_key(qc.compute_checks(_qc_input(BRANDED_HTML, consent="manual")))
    assert by["client_rules"]["status"] == "manual"


# ── Uwagi ───────────────────────────────────────────────────────────────────


def test_spelling_variants_are_warnings_outside_urls() -> None:
    issues = dict(
        qc.spelling_issues(
            "Javascript, Typescript, Postgres i Nodejs. JavaScript jest OK. "
            "Repo: https://github.com/ewa, mail ewa@gitlab.com"
        )
    )
    assert issues == {
        "Javascript": "JavaScript",
        "Typescript": "TypeScript",
        "Postgres": "PostgreSQL",
        "Nodejs": "Node.js",
    }
    fixed, n = qc.fix_spelling("Javascript i Postgres; https://github.com/x")
    assert fixed == "JavaScript i PostgreSQL; https://github.com/x" and n == 2
    html = "<p>Programista <b>Java</b>, Javascript.</p>"
    by = _by_key(qc.compute_checks(_qc_input(html, must=_reqs("Java"))))
    assert by["spelling"]["severity"] == "warning"
    assert by["spelling"]["status"] == "fail"


def test_title_check_ignores_seniority() -> None:
    assert qc.core_title("Senior Java Developer (B2B)") == "Java Developer"
    html = "<h1>Java Developer – Ewa N.</h1>" + BRANDED_HTML
    by = _by_key(qc.compute_checks(_qc_input(html)))
    assert by["title_matches_role"]["status"] == "pass"
    by = _by_key(qc.compute_checks(_qc_input(BRANDED_HTML)))
    assert by["title_matches_role"]["status"] == "fail"
    assert by["title_matches_role"]["severity"] == "warning"


def test_gate_covers_columns_before_cv_sent_only() -> None:
    for column in ("new", "screening", "verified", "cv_qc"):
        assert qc.gate_applies(column, "cv_sent", False)
        assert qc.gate_applies(column, "cv_qc", True)
    assert not qc.gate_applies("client_interview", "cv_sent", False)
    assert not qc.gate_applies("verified", "cv_qc", False)
    assert not qc.gate_applies("verified", "closed", False)


# ── Poprawki AI: walidacja ──────────────────────────────────────────────────


def _material() -> dict:
    return {
        "items": [
            {
                "requirement": "Kubernetes",
                "terms": ["Kubernetes"],
                "role": "Senior Developer · Acme Bank",
                "role_index": 0,
                "cv_role_label": "Senior Developer · Acme Bank",
                "cv_points": ["Rozwój usług w Java i Spring."],
                "original_role": "Mikroserwisy Java, Kubernetes, Kafka",
            }
        ],
        "original": ORIGINAL,
        "notes": "Kandydat wdrażał Helm na Kubernetes w Acme.",
        "cv": "",
    }


def test_parse_fixes_drops_quotes_outside_sources() -> None:
    raw = json.dumps(
        {
            "fixes": [
                {
                    "requirement": "Kubernetes",
                    "role": "Senior Developer · Acme Bank",
                    "current_text": "Rozwój usług w Java i Spring.",
                    "proposed_text": "Rozwój usług **Java** na **Kubernetes**.",
                    "source": "original",
                    "source_quote": "Senior Developer Java Kubernetes Kafka",
                },
                {
                    "requirement": "Kubernetes",
                    "role": "Senior Developer · Acme Bank",
                    "current_text": None,
                    "proposed_text": "Migracja 40 usług na **Kubernetes** w AWS.",
                    "source": "original",
                    "source_quote": "Migracja 40 usług na Kubernetes w AWS",
                },
            ]
        }
    )
    fixes = qc.parse_fixes(raw, _material(), "a" * 64)
    assert len(fixes) == 1
    assert fixes[0]["id"] == "f1-" + "a" * 12
    assert fixes[0]["source"] == "original"
    assert fixes[0]["current_text"] == "Rozwój usług w Java i Spring."


def test_parse_fixes_quote_from_notes_and_unknown_current_text() -> None:
    raw = json.dumps(
        {
            "fixes": [
                {
                    "requirement": "Kubernetes",
                    "role": "Senior Developer · Acme Bank",
                    "current_text": "Tekst, którego nie ma w CV.",
                    "proposed_text": "Wdrażał Helm na **Kubernetes** w zespole platformy.",
                    "source": "notes",
                    "source_quote": "wdrażał Helm na Kubernetes",
                },
                {
                    "requirement": "Docker",
                    "role": "Senior Developer · Acme Bank",
                    "current_text": None,
                    "proposed_text": "Konteneryzacja w **Docker**.",
                    "source": "original",
                    "source_quote": "Java React Docker",
                },
            ]
        }
    )
    fixes = qc.parse_fixes(raw, _material(), "b" * 64)
    # Docker nie jest brakiem z listy — model nie dopisuje nowych wymagań.
    assert [f["requirement"] for f in fixes] == ["Kubernetes"]
    assert fixes[0]["source"] == "notes" and fixes[0]["current_text"] is None


def test_parse_fixes_proposal_must_contain_the_requirement() -> None:
    raw = json.dumps(
        {
            "fixes": [
                {
                    "requirement": "Kubernetes",
                    "role": "Senior Developer · Acme Bank",
                    "current_text": None,
                    "proposed_text": "Rozwój mikroserwisów w **Java**.",
                    "source": "original",
                    "source_quote": "Senior Developer Java Kubernetes Kafka",
                }
            ]
        }
    )
    assert qc.parse_fixes(raw, _material(), "c" * 64) == []


# ── Edycja HTML ─────────────────────────────────────────────────────────────


def test_editable_parser_sees_the_same_blocks_as_the_review() -> None:
    doc = qc.EditableCv.parse(BRANDED_HTML)
    assert [b.text for b in doc.blocks] == [b.text for b in _blocks(BRANDED_HTML)]
    assert [b.text for b in _blocks(doc.html())] == [
        b.text for b in _blocks(BRANDED_HTML)
    ]


def test_bold_all_skips_headings_role_headers_and_existing_bold() -> None:
    html = (
        '<h2 data-cv-section="experience">Doświadczenie Java</h2>'
        '<p data-cv-section="role"><b>Java Developer</b> 2020</p>'
        "<ul><li>Budował usługi w Java i Kafka &amp; Spring.</li>"
        "<li>Już <b>Java</b>.</li></ul>"
    )
    out, count = qc.bold_all(html, _reqs("Java"))
    assert count == 1
    assert "<li>Budował usługi w <b>Java</b> i Kafka &amp; Spring.</li>" in out
    assert '<h2 data-cv-section="experience">Doświadczenie Java</h2>' in out
    assert "<b><b>" not in out


def test_ai_fix_replaces_a_point_or_appends_one_to_the_role() -> None:
    fix = {
        "role_index": 0,
        "cv_role_label": "Senior Developer 2021–obecnie · Acme Bank",
        "current_text": "Rozwój usług w Java i Spring.",
    }
    out = qc.apply_ai_fix(
        BRANDED_HTML,
        fix,
        "Rozwój usług **Java** na **Kubernetes** <script>",
        original_text=ORIGINAL,
        experience=EXPERIENCE,
    )
    assert (
        "<li>Rozwój usług <b>Java</b> na <b>Kubernetes</b> &lt;script&gt;</li>" in out
    )
    assert "Rozwój usług w Java i Spring." not in out

    appended = qc.apply_ai_fix(
        BRANDED_HTML,
        {
            "role_index": 1,
            # Etykieta roli CV = nagłówek generatora (stanowisko z datami).
            "cv_role_label": "Developer 2018–2021 · Globex",
            "current_text": None,
        },
        "Aplikacje webowe w **Java** i React dla klientów sklepu.",
        original_text=ORIGINAL,
        experience=EXPERIENCE,
    )
    texts = [b.text for b in _blocks(appended)]
    at = texts.index("Aplikacje webowe, React.")
    assert texts[at + 1] == "Aplikacje webowe w Java i React dla klientów sklepu."

    with pytest.raises(qc.ApplyError):
        qc.apply_ai_fix(
            BRANDED_HTML,
            {**fix, "current_text": "Punkt, którego już nie ma."},
            "x **Java**",
            original_text=ORIGINAL,
            experience=EXPERIENCE,
        )


def test_remove_term_takes_it_off_technology_lists_only() -> None:
    html = (
        '<p data-cv-section="technologies">Technologie '
        '<span class="tech">Java, Docker, Kafka</span></p>'
        "<ul><li>Docker</li><li>Wdrożył Docker w zespole platformy.</li></ul>"
    )
    out, count = qc.remove_term(html, "Docker")
    texts = [b.text for b in _blocks(out)]
    assert count == 2
    assert texts[0] == "Technologie Java, Kafka"
    assert "Docker" not in texts
    # Zdanie opisujące pracę zostaje — przeredagowuje je człowiek.
    assert "Wdrożył Docker w zespole platformy." in texts


def test_spelling_fix_in_html() -> None:
    out, count = qc.fix_spelling_html("<p>Javascript &amp; Postgres</p>")
    assert count == 2 and out == "<p>JavaScript &amp; PostgreSQL</p>"


def test_migration_is_mirrored_in_entrypoint() -> None:
    root = Path(__file__).resolve().parents[1]
    entry = (root / "entrypoint.sh").read_text()
    migration = (root / "alembic/versions/0361_cv_qc.py").read_text()
    squash = lambda t: re.sub(r"\s+", " ", t)  # noqa: E731
    for fragment in (
        "CREATE TABLE IF NOT EXISTS cv_qc_runs (",
        "candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE",
        "override_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS ix_cv_qc_runs_pair_created",
        "0361_dz_stage_renamed_qc_cv",
        "UPDATE pipeline_stage_defs SET name = 'QC CV'",
    ):
        assert fragment in squash(migration), fragment
        assert fragment in squash(entry), fragment
    assert 'down_revision = "0357_contract_orders_card_dismissed"' in migration


# ── Integracyjne ─────────────────────────────────────────────────────────────


async def _cleanup_qc(world: dict, stage_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CvQcRun).where(CvQcRun.candidate_id == world["candidate_id"])
        )
        await db.commit()
    await _cleanup_review(world, stage_id)


async def _runs(world: dict) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count(CvQcRun.id)).where(
                CvQcRun.candidate_id == world["candidate_id"],
                CvQcRun.job_id == world["job_id"],
            )
        )


@pytest.mark.asyncio
async def test_qc_is_computed_persisted_once_and_readable_by_team(
    api_client: AsyncClient,
) -> None:
    world = await _seed_world()
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    hor = await _login(api_client, hor_creds)
    stage_id = await _seed_review(world, hor, api_client)
    try:
        resp = await api_client.get(f"/api/pipeline/stages/{stage_id}/qc", headers=hor)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [c["key"] for c in body["checks"]] == [
            *qc.BLOCKING_KEYS,
            *qc.WARNING_KEYS,
        ]
        assert body["passed"] is False and body["blocking_failed"] == 2
        assert body["cv"]["source"] == "branded_draft" and body["cv"]["editable"]
        assert body["client_request"]["must"] == ["Java", "Kubernetes"]
        assert body["override"] is None and body["run_id"]
        # Treść CV idzie jako bloki tekstu — skrypt z edytora odpada.
        assert "alert" not in json.dumps(body["cv"]["blocks"])

        again = (
            await api_client.get(f"/api/pipeline/stages/{stage_id}/qc", headers=hor)
        ).json()
        assert again["run_id"] == body["run_id"]
        assert await _runs(world) == 1

        missing = await api_client.get("/api/pipeline/stages/999999999/qc", headers=hor)
        assert missing.status_code == 404
    finally:
        await _cleanup_qc(world, stage_id)
        await _cleanup(world, [hor_id])


@pytest.mark.asyncio
async def test_gate_blocks_cv_sent_until_qc_passes_or_dl_overrides(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", True)
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    world = await _seed_world()
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    hor = await _login(api_client, hor_creds)
    dl = await _login(api_client, dl_creds)
    rec = await _login(api_client, rec_creds)
    stage_id = await _seed_review(world, hor, api_client)
    send = {
        "candidate_id": world["candidate_id"],
        "job_id": world["job_id"],
        "stage_def_id": world["defs"]["cv_sent"],
        "client_rate_value": "180",
        "client_rate_unit": "hourly",
        "client_rate_currency": "PLN",
    }
    try:
        refused = await api_client.post("/api/pipeline/move", headers=dl, json=send)
        assert refused.status_code == 409, refused.text
        detail = refused.json()["detail"]
        assert detail["code"] == "CV_QC_FAILED"
        assert detail["blocking_failed"] == 2
        assert detail["stage_id"] == stage_id
        assert detail["message"] == "CV nie przeszło QC: 2 sprawdzenia do poprawy."
        # Przebieg odmowy zostaje — tablica pokazuje ten sam stan.
        assert await _runs(world) == 1
        board = (
            await api_client.get(f"/api/pipeline/kanban/{world['job_id']}", headers=hor)
        ).json()
        cards = [
            c
            for col in board["columns"]
            for c in col["items"]
            if c["candidate_id"] == world["candidate_id"]
        ]
        assert cards and cards[0]["qc"] == {"status": "failed", "blocking_failed": 2}

        denied = await api_client.post(
            f"/api/pipeline/stages/{stage_id}/qc/override",
            headers=rec,
            json={"reason": "Klient zna kandydata z poprzedniego projektu."},
        )
        assert denied.status_code == 403
        short = await api_client.post(
            f"/api/pipeline/stages/{stage_id}/qc/override",
            headers=dl,
            json={"reason": "bo tak"},
        )
        assert short.status_code == 422
        ok = await api_client.post(
            f"/api/pipeline/stages/{stage_id}/qc/override",
            headers=dl,
            json={"reason": "Klient zna kandydata z poprzedniego projektu."},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["override"]["reason"].startswith("Klient zna")
        async with AsyncSessionLocal() as db:
            assert await db.scalar(
                select(Activity.id).where(
                    Activity.action == "cv_qc_override",
                    Activity.entity_id == stage_id,
                )
            )
            status = await qc.pair_statuses(
                db, [(world["candidate_id"], world["job_id"])]
            )
        assert (
            status[(world["candidate_id"], world["job_id"])]["status"] == "overridden"
        )

        moved = await api_client.post("/api/pipeline/move", headers=dl, json=send)
        assert moved.status_code == 200, moved.text
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Activity).where(
                    Activity.entity_type == "candidate_stage",
                    Activity.entity_id == stage_id,
                    Activity.action == "cv_qc_override",
                )
            )
            await db.commit()
        await _cleanup_qc(world, stage_id)
        await _cleanup(world, [hor_id, dl_id, rec_id])


@pytest.mark.asyncio
async def test_leaving_the_cpro_queue_does_not_repeat_qc(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """„✓ Wrzucone” nie liczy QC drugi raz — osoba w kolejce Cpro przeszła
    bramkę przy wejściu (albo sprzed v5 ręczny przegląd DZ). Zostaje
    zastrzeżenie: wrzuca osoba od Cpro albo admin/DL/HoR."""

    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    hor = await _login(api_client, hor_creds)
    rec = await _login(api_client, rec_creds)
    try:
        async with restore_cpro_sender():
            await clear_cpro_sender()
            # Wejście do kolejki sprzed bramki (jak osoby z przeglądu DZ).
            monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", False)
            await _move(api_client, hor, world, "verified")
            await _move(api_client, hor, world, "cpro")
            monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", True)

            send = {
                "candidate_id": world["candidate_id"],
                "job_id": world["job_id"],
                "stage_def_id": world["defs"]["cv_sent"],
            }
            refused = await api_client.post(
                "/api/pipeline/move", headers=rec, json=send
            )
            assert refused.status_code == 403, refused.text
            moved = await api_client.post("/api/pipeline/move", headers=hor, json=send)
            assert moved.status_code == 200, moved.text
            assert await _runs(world) == 0
    finally:
        await _cleanup(world, [hor_id, rec_id])


@pytest.mark.asyncio
async def test_fallback_sender_of_the_job_can_upload_without_firm_sender(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audyt 25.09.2026: bez osoby od Cpro na firmę kolejka pokazuje zadanie
    osobie zapasowej rekrutacji (`jobs.cpro_sender_id`) — ta osoba musi móc
    je wrzucić („✓ Wrzucone”), a nie dostawać 403. Inny rekruter dalej 403."""

    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    other_id, other_creds = await _seed_user(UserRole.recruiter)
    admin_id, admin_creds = await _seed_user(UserRole.admin)
    hor = await _login(api_client, hor_creds)
    rec = await _login(api_client, rec_creds)
    other = await _login(api_client, other_creds)
    admin = await _login(api_client, admin_creds)
    try:
        async with restore_cpro_sender():
            await clear_cpro_sender()
            monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", False)
            await _move(api_client, hor, world, "verified")
            # Osobę zapasową rekrutacji wskazuje admin albo DL Nordei (PR #1844).
            await _move(api_client, admin, world, "cpro", task_assignee_id=rec_id)
            monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", True)

            # HoR widzi zadanie z osobą zapasową, bo nikt nie jest na firmę.
            queue = (await api_client.get("/api/board-tasks", headers=hor)).json()
            todo = [
                r
                for r in queue["cpro_to_send"]
                if r["candidate_id"] == world["candidate_id"]
            ]
            assert len(todo) == 1 and todo[0]["assignee_id"] == rec_id

            send = {
                "candidate_id": world["candidate_id"],
                "job_id": world["job_id"],
                "stage_def_id": world["defs"]["cv_sent"],
            }
            refused = await api_client.post(
                "/api/pipeline/move", headers=other, json=send
            )
            assert refused.status_code == 403, refused.text
            moved = await api_client.post("/api/pipeline/move", headers=rec, json=send)
            assert moved.status_code == 200, moved.text
    finally:
        await _cleanup(world, [hor_id, rec_id, other_id, admin_id])


async def _rejected_stage_def_id(world: dict) -> int:
    from app.models.pipeline_template import PipelineStageDef

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(PipelineStageDef.id).where(
                PipelineStageDef.template_id == world["template_id"],
                PipelineStageDef.is_terminal.is_(True),
            )
        )


@pytest.mark.asyncio
async def test_closed_pair_does_not_skip_qc_on_the_way_to_cv_sent(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audyt 25.09.2026: „Nowi → Odrzucony → CV wysłane” omijało QC, bo bramka
    patrzyła na bieżącą kolumnę („Zamknięci”). Liczy się kolumna sprzed
    zamknięcia — tu „Zweryfikowany”, więc bez CV firmowego 409."""

    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    world = await _seed_world()
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    try:
        await _move(api_client, dl, world, "verified")
        rejected = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": world["candidate_id"],
                "job_id": world["job_id"],
                "stage_def_id": await _rejected_stage_def_id(world),
                "rejection_reason": "Stawka",
            },
        )
        assert rejected.status_code == 200, rejected.text

        monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", True)
        refused = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": world["candidate_id"],
                "job_id": world["job_id"],
                "stage_def_id": world["defs"]["cv_sent"],
                "client_rate_value": "180",
                "client_rate_unit": "hourly",
                "client_rate_currency": "PLN",
            },
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["code"] == "CV_QC_FAILED"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CvQcRun).where(
                    CvQcRun.candidate_id == world["candidate_id"],
                    CvQcRun.job_id == world["job_id"],
                )
            )
            await db.commit()
        await _cleanup(world, [dl_id])


@pytest.mark.asyncio
async def test_fresh_pair_without_stage_rows_does_not_skip_qc(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runda 2 audytu 25.09.2026: para bez żadnego wiersza etapu (świeży
    kandydat wysłany przez API wprost na „CV wysłane”) omijała QC i osobę od
    Cpro, bo bramka kończyła się na „brak wiersza”. Para bez wierszy stoi na
    początku drogi („Nowi”), a bez CV firmowego QC nie przechodzi — także
    w paczce (`/bulk-move`)."""

    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", True)
    world = await _seed_world()
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    rate = {
        "client_rate_value": "180",
        "client_rate_unit": "hourly",
        "client_rate_currency": "PLN",
    }
    try:
        refused = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": world["candidate_id"],
                "job_id": world["job_id"],
                "stage_def_id": world["defs"]["cv_sent"],
                **rate,
            },
        )
        assert refused.status_code == 409, refused.text
        detail = refused.json()["detail"]
        assert detail["code"] == "CV_QC_FAILED"
        assert detail["stage_id"] is None

        bulk = await api_client.post(
            "/api/pipeline/bulk-move",
            headers=dl,
            json={
                "candidate_ids": [world["candidate_id"]],
                "job_id": world["job_id"],
                "stage": "cv_sent",
                **rate,
            },
        )
        assert bulk.status_code == 409, bulk.text
        assert bulk.json()["detail"]["code"] == "CV_QC_FAILED"
        async with AsyncSessionLocal() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(CandidateStage)
                    .where(
                        CandidateStage.candidate_id == world["candidate_id"],
                        CandidateStage.job_id == world["job_id"],
                    )
                )
                == 0
            )
    finally:
        await _cleanup(world, [dl_id])


@pytest.mark.asyncio
async def test_gate_switch_off_lets_the_move_through(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "CV_QC_GATE_ENABLED", False)
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    world = await _seed_world()
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    hor = await _login(api_client, hor_creds)
    dl = await _login(api_client, dl_creds)
    stage_id = await _seed_review(world, hor, api_client)
    try:
        moved = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": world["candidate_id"],
                "job_id": world["job_id"],
                "stage_def_id": world["defs"]["cv_sent"],
                "client_rate_value": "180",
                "client_rate_unit": "hourly",
                "client_rate_currency": "PLN",
            },
        )
        assert moved.status_code == 200, moved.text
        assert await _runs(world) == 0
    finally:
        await _cleanup_qc(world, stage_id)
        await _cleanup(world, [hor_id, dl_id])


@pytest.mark.asyncio
async def test_ai_fix_is_proposed_from_sources_and_applied_to_the_draft(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    hor = await _login(api_client, hor_creds)
    stage_id = await _seed_review(world, hor, api_client)
    calls: list[dict] = []

    def fake_call(**kwargs):
        calls.append(kwargs)
        payload = {
            "fixes": [
                {
                    "requirement": "Kubernetes",
                    "role": "Senior Developer · Acme Bank",
                    "current_text": "Rozwój usług w Java i Spring.",
                    "proposed_text": (
                        "Rozwój mikroserwisów **Java** na **Kubernetes** z kolejką Kafka."
                    ),
                    "source": "original",
                    "source_quote": "Senior Developer Java Kubernetes Kafka",
                },
                {
                    "requirement": "Java",
                    "role": "Developer · Globex",
                    "current_text": None,
                    "proposed_text": "Aplikacje **Java** w chmurze AWS dla 3 mln osób.",
                    "source": "original",
                    "source_quote": "AWS dla 3 mln osób",
                },
            ]
        }
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(payload))],
            model="gpt-6-luna",
        )

    monkeypatch.setattr("app.services.claude_client.call_claude", fake_call)
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda _model: True
    )
    try:
        first = await api_client.post(
            f"/api/pipeline/stages/{stage_id}/qc/fixes", headers=hor
        )
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["status"] == "ok" and body["cached"] is False
        # Cytat „AWS dla 3 mln osób” nie istnieje w oryginale — odrzucony.
        assert [f["requirement"] for f in body["fixes"]] == ["Kubernetes"]
        again = (
            await api_client.post(
                f"/api/pipeline/stages/{stage_id}/qc/fixes", headers=hor
            )
        ).json()
        assert again["cached"] is True and len(calls) == 1

        applied = await api_client.post(
            f"/api/pipeline/stages/{stage_id}/qc/apply",
            headers=hor,
            json={"action": "ai_fix", "fix_id": body["fixes"][0]["id"]},
        )
        assert applied.status_code == 200, applied.text
        checks = {c["key"]: c for c in applied.json()["checks"]}
        assert checks["must_in_cv"]["status"] == "pass"
        async with AsyncSessionLocal() as db:
            csv = await db.scalar(
                select(CandidateStageCV).where(
                    CandidateStageCV.candidate_stage_id == stage_id
                )
            )
            assert "<b>Kubernetes</b>" in csv.branded_draft_html
            assert csv.branded_status == "draft"
            assert await db.scalar(
                select(Activity.id).where(
                    Activity.action == "cv_qc_fix_applied",
                    Activity.entity_id == csv.id,
                )
            )
            await db.execute(
                delete(Activity).where(
                    Activity.entity_type == "candidate_stage_cv",
                    Activity.entity_id == csv.id,
                )
            )
            await db.commit()

        unknown = await api_client.post(
            f"/api/pipeline/stages/{stage_id}/qc/apply",
            headers=hor,
            json={"action": "ai_fix", "fix_id": "f9-000000000000"},
        )
        assert unknown.status_code == 422
    finally:
        await _cleanup_qc(world, stage_id)
        await _cleanup(world, [hor_id])


@pytest.mark.asyncio
async def test_fixes_failure_is_unavailable_not_an_error(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    hor = await _login(api_client, hor_creds)
    stage_id = await _seed_review(world, hor, api_client)

    def boom(**_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.services.claude_client.call_claude", boom)
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda _model: True
    )
    try:
        resp = await api_client.post(
            f"/api/pipeline/stages/{stage_id}/qc/fixes", headers=hor
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "unavailable"
    finally:
        await _cleanup_qc(world, stage_id)
        await _cleanup(world, [hor_id])


@pytest.mark.asyncio
async def test_cv_from_outside_nexus_cannot_be_edited(
    api_client: AsyncClient,
) -> None:
    from app.models.candidate_document import CandidateDocument

    world = await _seed_world()
    hor_id, hor_creds = await _seed_user(UserRole.head_of_recruitment)
    hor = await _login(api_client, hor_creds)
    stage_id = await _seed_review(world, hor, api_client)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CandidateStageCV).where(
                    CandidateStageCV.candidate_id == world["candidate_id"]
                )
            )
            db.add(
                CandidateDocument(
                    candidate_id=world["candidate_id"],
                    filename="Ewa_B2B_Nordea.docx",
                    file_content=_client_docx(),
                )
            )
            await db.commit()
        body = (
            await api_client.get(f"/api/pipeline/stages/{stage_id}/qc", headers=hor)
        ).json()
        assert body["cv"]["source"] == "document"
        assert body["cv"]["editable"] is False
        resp = await api_client.post(
            f"/api/pipeline/stages/{stage_id}/qc/apply",
            headers=hor,
            json={"action": "spelling"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "CV_NOT_EDITABLE"
        fixes = (
            await api_client.post(
                f"/api/pipeline/stages/{stage_id}/qc/fixes", headers=hor
            )
        ).json()
        assert fixes["status"] == "not_editable"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CandidateDocument).where(
                    CandidateDocument.candidate_id == world["candidate_id"]
                )
            )
            await db.commit()
        await _cleanup_qc(world, stage_id)
        await _cleanup(world, [hor_id])
