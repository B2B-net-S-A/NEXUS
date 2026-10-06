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
    seed_entry_row,
)
from tests.taxonomy_fixture import hydrated_taxonomy
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
    assert qc.BLOCKING_KEYS == (
        "cv_present",
        "critical_skills",
        "no_unsupported",
        "client_rules",
    )
    assert {c["severity"] for c in checks[:4]} == {"blocking"}
    assert {c["severity"] for c in checks[4:]} == {"warning"}
    by = _by_key(checks)
    assert by["cv_present"]["status"] == "pass"
    # Bez umiejętności krytycznych braki w must-have są uwagami, nie blokadą.
    assert by["critical_skills"]["status"] == "skip"
    assert by["must_in_cv"]["status"] == "fail"
    assert by["must_in_cv"]["summary"] == "1/2"
    # Kubernetes jest w oryginale — poprawka AI, nie pytanie do kandydata.
    assert by["must_in_cv"]["items"][0]["fix"] == "ai"
    assert by["must_bolded"]["status"] == "pass"
    assert by["dates"]["status"] == "pass"
    assert by["no_unsupported"]["status"] == "pass"
    passed, blocking, warnings = qc.summarize(checks)
    assert passed and blocking == 0 and warnings >= 2


def test_without_company_cv_only_generate_cv_is_asked_for() -> None:
    """Brak CV firmowego blokuje zawsze — także przy rekrutacji bez must-have
    i bez umiejętności krytycznych (do 02.10.2026 porażkę niosło `must_in_cv`,
    które przestało blokować)."""
    for extra in ({}, {"must": []}, {"critical": _reqs("Java")}):
        checks = qc.compute_checks(_qc_input("", blocks=[], has_cv=False, **extra))
        by = _by_key(checks)
        assert by["cv_present"]["status"] == "fail"
        assert by["cv_present"]["severity"] == "blocking"
        assert by["cv_present"]["items"][0]["fix"] == "generate_cv"
        assert all(c["status"] == "skip" for c in checks[1:])
        assert qc.summarize(checks) == (False, 1, 0)


def test_rodo_clause_is_not_part_of_the_last_role() -> None:
    """Klauzula zgody stoi tuż po ostatnim stanowisku. Generator pisze ją jako
    `<p class="rodo">` bez znacznika sekcji, więc do 02.10.2026 wchodziła do
    tekstu ostatniej roli (QC zaznaczało ją czerwono, a AI dostawała ją jako
    punkt stanowiska)."""
    for clause in (
        '<p class="rodo">Wyrażam zgodę na przetwarzanie moich danych osobowych '
        "zawartych w przekazanych przeze mnie dokumentach przez B2B.net S.A.</p>",
        # Starsze zatwierdzone CV zgubiło klasę — zostają pierwsze słowa klauzuli.
        "<p>I hereby consent to the processing of my personal data contained "
        "in the documents submitted by me.</p>",
        '<p data-cv-section="rodo">Wyrażam zgodę na przetwarzanie…</p>',
    ):
        blocks = _blocks(BRANDED_HTML + clause)
        assert blocks[-1].section == "rodo"
        rodo_index = len(blocks) - 1
        roles = qc.cv_roles(blocks, dz.original_roles(EXPERIENCE, ORIGINAL))
        assert rodo_index not in roles[-1].blocks
        assert "zgod" not in roles[-1].role.text.casefold()
        assert "consent" not in roles[-1].role.text.casefold()
        assert "consent" not in dz.generated_roles(blocks)[-1].text.casefold()
        assert "zgod" not in dz.generated_roles(blocks)[-1].text.casefold()
        # Edytor widzi te same bloki — poprawka AI trafia przed klauzulę.
        assert [
            b.section for b in qc.EditableCv.parse(BRANDED_HTML + clause).blocks
        ] == [b.section for b in blocks]


def test_ai_fix_for_the_last_role_lands_before_the_rodo_clause() -> None:
    html = (
        '<h2 data-cv-section="experience">Doświadczenie</h2>'
        '<p data-cv-section="role"><b>Developer</b> 2018–2021</p>'
        '<p data-cv-section="employer">Globex</p>'
        '<p class="rodo">Wyrażam zgodę na przetwarzanie moich danych osobowych.</p>'
    )
    out = qc.apply_ai_fix(
        html,
        {"role_index": 0, "cv_role_label": "Developer 2018–2021 · Globex"},
        "Aplikacje webowe w **Java** dla klientów sklepu.",
        original_text=ORIGINAL,
        experience=EXPERIENCE,
    )
    texts = [b.text for b in _blocks(out)]
    assert texts.index("Aplikacje webowe w Java dla klientów sklepu.") < texts.index(
        "Wyrażam zgodę na przetwarzanie moich danych osobowych."
    )


# ── Co blokuje: umiejętności krytyczne, zgodność z oryginałem, reguły klienta ─


def test_only_warnings_never_block() -> None:
    """Każda uwaga naraz (braki must, pogrubienia, lata, daty, tytuł) — QC
    przechodzi, bo nie ma umiejętności krytycznych ani twierdzeń spoza oryginału."""
    html = (
        "<ul><li>15 lat doświadczenia w bankowości.</li></ul>"
        '<h2 data-cv-section="experience">Doświadczenie</h2>'
        '<p data-cv-section="role"><b>Senior Developer</b></p>'
        '<p data-cv-section="employer">Acme Bank</p>'
        "<ul><li>Rozwój usług w Java i Spring, Javascript.</li></ul>"
    )
    history = [{"company": "Acme Bank", "start": "2020-01", "end": "2025-12"}]
    checks = qc.compute_checks(_qc_input(html, experience=history))
    by = _by_key(checks)
    for key in ("must_in_cv", "must_bolded", "years_header", "dates", "spelling"):
        assert by[key]["status"] == "fail", key
        assert by[key]["severity"] == "warning", key
    assert qc.summarize(checks)[:2] == (True, 0)


def test_critical_skill_gaps_block_and_count_per_skill() -> None:
    checks = qc.compute_checks(
        _qc_input(BRANDED_HTML, critical=_reqs("Java", "Kubernetes"))
    )
    by = _by_key(checks)
    critical = by["critical_skills"]
    assert critical["status"] == "fail" and critical["severity"] == "blocking"
    assert {(i["requirement"], i["role"]) for i in critical["items"]} == {
        ("Java", "Developer · Globex"),
        ("Kubernetes", "Senior Developer · Acme Bank"),
    }
    assert all(i["fix"] == "ai" for i in critical["items"])
    # Krytyczne nie dublują się w uwagach o pozostałych wymaganiach.
    assert by["must_in_cv"]["status"] == "skip"
    assert by["must_in_roles"]["status"] == "skip"
    # Jedno wymaganie = jedna rzecz do poprawy, niezależnie od liczby ról.
    assert qc.summarize(checks)[:2] == (False, 2)


def test_critical_skill_in_several_roles_is_one_task() -> None:
    html = BRANDED_HTML.replace(
        "<li>Rozwój usług w <b>Java</b> i Spring.</li>", "<li>Utrzymanie usług.</li>"
    )
    checks = qc.compute_checks(_qc_input(html, critical=_reqs("Java")))
    critical = _by_key(checks)["critical_skills"]
    assert len(critical["items"]) == 2
    assert qc.summarize(checks)[:2] == (False, 1)


def test_critical_skill_absent_everywhere_asks_the_candidate() -> None:
    checks = qc.compute_checks(_qc_input(BRANDED_HTML, critical=_reqs("Scala")))
    item = _by_key(checks)["critical_skills"]["items"][0]
    assert item["requirement"] == "Scala" and item["role"] is None
    assert item["fix"] == "ask_candidate"
    assert qc.summarize(checks)[:2] == (False, 1)


def test_critical_skill_described_in_its_roles_passes() -> None:
    checks = qc.compute_checks(
        _qc_input(
            BRANDED_HTML.replace(
                "<li>Aplikacje webowe, <b>React</b>.</li>",
                "<li>Aplikacje webowe w <b>Java</b> i React dla sklepu.</li>",
            ),
            critical=_reqs("Java"),
            must=_reqs("Java"),
        )
    )
    by = _by_key(checks)
    assert by["critical_skills"]["status"] == "pass"
    assert by["critical_skills"]["summary"] == "1/1"
    assert qc.summarize(checks)[:2] == (True, 0)


def test_critical_requirements_follow_the_search_gate() -> None:
    """Krytyczne = wybór DL, a bez niego podpowiedź z historii — ta sama
    reguła co bramka wyszukiwania; etykiety w pisowni wymagań QC."""
    from app.services import critical_skills
    from tests.taxonomy_fixture import hydrated_taxonomy

    def job(critical="absent"):
        stack: dict = {"must": [{"name": m} for m in ("Java 17", "Kubernetes")]}
        if critical != "absent":
            stack["critical"] = critical
        return SimpleNamespace(
            id=1,
            title="Java Developer",
            working_title=None,
            must_skills=["Java 17", "Kubernetes"],
            nice_skills=[],
            requirements_reviewed=True,
            matching_requirements=None,
            champion_profile={"stack": stack},
        )

    must = [
        dz.Requirement(label=n, alternatives=(n,), terms=dz.requirement_terms((n,)))
        for n in ("Java 17", "Kubernetes", "Umiejętność pracy w zespole")
    ]
    with hydrated_taxonomy():
        critical_skills.set_payload(
            {"version": 1, "labels": {"java": {"rate": 0.95, "jobs": 100}}}
        )
        try:
            chosen, source = qc.critical_requirements(job(["Kubernetes"]), must)
            assert [r.label for r in chosen] == ["Kubernetes"] and source == "dl"
            suggested, source = qc.critical_requirements(job(), must)
            assert [r.label for r in suggested] == ["Java 17"]
            assert source == "suggested"
            # Wersja z etykiety nie musi stać w CV.
            assert suggested[0].terms == ("Java",)
            none, source = qc.critical_requirements(job([]), must)
            assert none == [] and source == "none"
        finally:
            critical_skills.set_payload(None)
    # Bez wczytanego słownika nic nie jest technologią — brak krytycznych.
    assert qc.critical_requirements(job(["Kubernetes"]), must) == ([], "none")


def test_critical_requirement_is_read_like_the_search_gate() -> None:
    """„Bazy danych (Oracle, PostgreSQL)” wybrane jako krytyczne: bramka
    wyszukiwania przyjmuje którąkolwiek z nazw, więc QC też. Do 02.10.2026 QC
    szukało dosłownie „Bazy danych” i CV z opisanym Oracle dostawało blokadę
    „Brak w CV i w oryginale”."""
    label = "Bazy danych (Oracle, PostgreSQL)"
    must = [
        dz.Requirement(label=n, alternatives=(n,), terms=dz.requirement_terms((n,)))
        for n in (label, "Kubernetes")
    ]
    job = SimpleNamespace(
        id=1,
        title="Administrator baz danych",
        working_title=None,
        must_skills=[label, "Kubernetes"],
        nice_skills=[],
        requirements_reviewed=True,
        matching_requirements=None,
        champion_profile={
            "stack": {
                "must": [{"name": label}, {"name": "Kubernetes"}],
                "critical": [label],
            }
        },
    )
    html = (
        "<p>Administrowałem bazą <b>Oracle</b> 19c w banku: strojenie zapytań "
        "i kopie zapasowe.</p>"
    )
    with hydrated_taxonomy():
        critical, source = qc.critical_requirements(job, must)
        assert source == "dl"
        assert [(r.label, r.terms) for r in critical] == [
            (label, ("Oracle", "PostgreSQL"))
        ]
        # Te same nazwy czytają pozostałe sprawdzenia i poprawki (pogrubienia,
        # zgodność z oryginałem, materiał dla AI).
        assert [r.terms for r in qc.with_critical_terms(must, critical)] == [
            ("Oracle", "PostgreSQL"),
            ("Kubernetes",),
        ]
        by = _by_key(
            qc.compute_checks(
                _qc_input(
                    html,
                    must=qc.with_critical_terms(must, critical),
                    critical=critical,
                    original_text="Oracle 19c, strojenie zapytań.",
                    experience=[],
                )
            )
        )
    assert by["critical_skills"]["status"] == "pass", by["critical_skills"]
    bolded = {i["requirement"] for i in by["must_bolded"]["items"]}
    assert label not in bolded


def test_rodo_clause_is_not_cv_content_for_requirements() -> None:
    """Klauzula zgody to szablon, nie treść CV. Do 02.10.2026 wymaganie „.NET 8”
    trafiało w „B2B.net S.A.” z klauzuli: QC blokowało pozycją „net — jest w CV,
    a nie ma tego w oryginale” (której nie dało się poprawić), a krytyczne
    „.NET” przechodziło, choć treść CV go nie opisuje."""
    from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS

    def checks(**extra) -> dict[str, dict]:
        html = (
            "<p>Angular developer w zespole płatności.</p>"
            f'<p class="rodo">{TRANSLATIONS["pl"]["rodo"]}</p>'
        )
        base = dict(must=_reqs("Angular"), experience=[])
        base.update(extra)
        return _by_key(qc.compute_checks(_qc_input(html, **base)))

    def reqs(*names: str) -> list[dz.Requirement]:
        return [
            dz.Requirement(label=n, alternatives=(n,), terms=dz.requirement_terms((n,)))
            for n in names
        ]

    # Mile widziane „.NET 8”, którego nie ma ani w treści CV, ani w oryginale.
    by = checks(nice=reqs(".NET 8"), original_text="Angular developer")
    assert by["no_unsupported"]["status"] == "pass", by["no_unsupported"]
    # Słowo, które stoi wyłącznie w klauzuli, nie jest twierdzeniem o kandydacie.
    by = checks(nice=_reqs("B2B.net"), original_text="Angular developer")
    assert by["no_unsupported"]["status"] == "pass", by["no_unsupported"]
    # Krytyczne „.NET” jest w oryginale, ale nie w treści CV — klauzula go nie udaje.
    net = reqs(".NET")
    by = checks(must=net, critical=net, original_text="Angular i .NET w banku")
    assert by["critical_skills"]["status"] == "fail", by["critical_skills"]
    assert by["critical_skills"]["items"][0]["detail"].startswith(
        "Brak w CV — jest w oryginale"
    )


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


def test_version_written_in_the_cv_needs_cover_in_the_sources() -> None:
    """Technologii szukamy bez wersji („Java 17” z wymagań znajduje „Java”),
    ale wersja wpisana w CV jest twierdzeniem o kandydacie."""
    must = [
        dz.Requirement(
            label="Java 17",
            alternatives=("Java 17",),
            terms=dz.requirement_terms(("Java 17",)),
        )
    ]
    plain = "<p>Programista <b>Java</b>.</p>"
    versioned = "<p>Programista <b>Java 17</b>.</p>"
    by = _by_key(qc.compute_checks(_qc_input(plain, must=must)))
    assert by["must_in_cv"]["status"] == "pass"
    assert by["no_unsupported"]["status"] == "pass"

    by = _by_key(qc.compute_checks(_qc_input(versioned, must=must)))
    assert by["must_in_cv"]["status"] == "pass"
    item = by["no_unsupported"]["items"][0]
    assert item["term"] == "Java 17" and item["fix"] == "ask_candidate"

    by = _by_key(
        qc.compute_checks(
            _qc_input(versioned, must=must, notes_text="Pracuje na Java 17 od roku.")
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


def test_years_header_mismatch_is_reported_as_a_warning() -> None:
    html = "<ul><li>15 lat doświadczenia w bankowości.</li></ul>" + BRANDED_HTML
    history = [{"company": "A", "start": "2020-01", "end": "2025-12"}]
    by = _by_key(qc.compute_checks(_qc_input(html, experience=history)))
    assert by["years_header"]["status"] == "fail"
    assert by["years_header"]["severity"] == "warning"


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


class _ScalarDb:
    def __init__(self, *values):
        self.values = list(values)

    async def scalar(self, _stmt):
        return self.values.pop(0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("generated", "values", "expected"),
    [
        # Kopia etapu bez obrazu, wiersz generatora z obrazem — DOCX kopii
        # i tak nie da się pobrać, więc QC nie może zaliczyć zgody.
        (
            {"source": "branded_draft", "stage_id": 5, "generated_document_id": 9},
            [False, {"consent_screenshot": {"key": "k"}}],
            "missing",
        ),
        (
            {"source": "branded_finalized", "stage_id": 5, "generated_document_id": 9},
            [True],
            "ok",
        ),
        # CV z generatora bez kopii etapu: obraz na wierszu generatora.
        (
            {"source": "generated", "stage_id": None, "generated_document_id": 9},
            [{"consent_screenshot": {"key": "k"}}],
            "ok",
        ),
    ],
)
async def test_consent_of_the_stage_copy_is_what_counts(
    monkeypatch: pytest.MonkeyPatch, generated: dict, values: list, expected: str
) -> None:
    """Runda 8 (R8-N8-4): zgoda RODO w QC = ta sama reguła co blokada pobrania."""

    async def rule(_db, _client_id):
        return SimpleNamespace(requires_rodo_consent_block=True)

    monkeypatch.setattr(
        "app.services.cv_generator_b2b.client_rules.resolve_client_rule", rule
    )
    src = SimpleNamespace(generated=generated, job=SimpleNamespace(id=2, client_id=1))
    assert await qc._consent_state(_ScalarDb(*values), src) == expected


@pytest.mark.asyncio
async def test_notes_source_skips_followup_call_notes() -> None:
    """Runda 8 (R8-V3-2): notatka follow-upu (`source_ref='followup:…'`)
    nie jest źródłem faktów QC — wymienia tytuły cudzych rekrutacji."""

    seen: list = []

    class _Db:
        async def execute(self, stmt):
            seen.append(stmt)
            return SimpleNamespace(scalars=lambda: iter(["Notatka"]))

    assert await qc._notes_text(_Db(), 1) == "Notatka"
    sql = str(seen[0].compile(compile_kwargs={"literal_binds": True}))
    assert "followup:%" in sql


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


def test_fixes_material_puts_critical_gaps_first_and_keeps_their_check() -> None:
    """Przy limicie propozycji pierwszeństwo mają umiejętności krytyczne,
    a propozycja pamięta, którego sprawdzenia dotyczy."""
    must = _reqs("Java", "Kubernetes")
    checks = qc.compute_checks(_qc_input(BRANDED_HTML, must=must, critical=must[1:]))
    src = SimpleNamespace(
        original={"text": ORIGINAL},
        blocks=_blocks(BRANDED_HTML),
        candidate=SimpleNamespace(experience=EXPERIENCE),
        must=must,
    )
    material = qc.fixes_material(src, checks, "")
    assert [(i["requirement"], i["check_key"]) for i in material["items"]] == [
        ("Kubernetes", "critical_skills"),
        ("Java", "must_in_roles"),
    ]
    raw = json.dumps(
        {
            "fixes": [
                {
                    "requirement": "Kubernetes",
                    "role": "Senior Developer · Acme Bank",
                    "current_text": None,
                    "proposed_text": "Wdrażanie usług na **Kubernetes** w zespole.",
                    "source": "original",
                    "source_quote": "Senior Developer Java Kubernetes Kafka",
                }
            ]
        }
    )
    fixes = qc.parse_fixes(raw, material, "a" * 64)
    assert [f["check_key"] for f in fixes] == ["critical_skills"]


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


@pytest.mark.parametrize(
    "quote",
    [
        # Jedna litera jest podciągiem każdego oryginału.
        "a",
        # Samo słowo wymagania — za mało, żeby potwierdzało zdanie.
        "Kubernetes",
        # Zdanie z oryginału, ale bez wymagania.
        "Globex 2018-2021 Developer Java React",
    ],
)
def test_parse_fixes_quote_must_be_a_sentence_about_the_requirement(
    quote: str,
) -> None:
    """Runda 8 (R8-N8-2): cytat źródła, który niczego nie potwierdza, nie
    przepuszcza zdania z wymyślonymi liczbami."""
    raw = json.dumps(
        {
            "fixes": [
                {
                    "requirement": "Kubernetes",
                    "role": "Senior Developer · Acme Bank",
                    "current_text": None,
                    "proposed_text": (
                        "Utrzymanie 200 usług na **Kubernetes** dla 2 mln klientów."
                    ),
                    "source": "original",
                    "source_quote": quote,
                }
            ]
        }
    )
    assert qc.parse_fixes(raw, _material(), "e" * 64) == []


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


def test_ai_fix_never_replaces_the_same_text_in_another_role() -> None:
    """Runda 8 (R8-N8-5): punkt roli A zmienił się po wygenerowaniu propozycji;
    ten sam tekst w roli B nie może zostać zastąpiony zdaniem o roli A."""
    html = BRANDED_HTML.replace(
        "<li>Aplikacje webowe, <b>React</b>.</li>", "<li>Code review.</li>"
    ).replace("<li>Rozwój usług w <b>Java</b> i Spring.</li>", "<li>Nowy punkt.</li>")
    fix = {
        "role_index": 0,
        "cv_role_label": "Senior Developer 2021–obecnie · Acme Bank",
        "current_text": "Code review.",
    }
    with pytest.raises(qc.ApplyError):
        qc.apply_ai_fix(
            html,
            fix,
            "Code review usług **Kubernetes** w zespole platformy.",
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


def test_remove_term_takes_the_version_with_it() -> None:
    html = (
        '<p data-cv-section="technologies">Technologie '
        '<span class="tech">Java, Angular 15, Kafka</span></p>'
    )
    out, count = qc.remove_term(html, "Angular")
    assert count == 1
    assert [b.text for b in _blocks(out)] == ["Technologie Java, Kafka"]


def test_spelling_fix_in_html() -> None:
    out, count = qc.fix_spelling_html("<p>Javascript &amp; Postgres</p>")
    assert count == 2 and out == "<p>JavaScript &amp; PostgreSQL</p>"


# ── Obejście QC ─────────────────────────────────────────────────────────────


def test_override_reason_is_a_ready_label_or_a_free_description() -> None:
    from pydantic import ValidationError

    from app.api.cv_qc import QcOverrideRequest

    assert qc.override_reason_text("client_short_cv", "") == (
        "Klient prosił o krótsze CV"
    )
    assert qc.override_reason_text("confirmed_in_call", "  rozmowa   1.10 ") == (
        "Kandydat potwierdził to w rozmowie, w CV tego nie ma — rozmowa 1.10"
    )
    assert qc.override_reason_text("other", "Pilna prośba klienta") == (
        "Pilna prośba klienta"
    )
    assert qc.override_reason_text(None, "bo tak") == "bo tak"

    # Gotowy powód nie wymaga opisu; bez minimum znaków.
    assert QcOverrideRequest(reason_code="client_short_cv").reason == ""
    assert QcOverrideRequest(reason="  bo   tak ").reason == "bo tak"
    for body in (
        {},
        {"reason_code": "other"},
        {"reason_code": "other", "reason": "   "},
        {"reason_code": "nieznany", "reason": "Klient prosił."},
    ):
        with pytest.raises(ValidationError):
            QcOverrideRequest(**body)


def test_qc_override_reasons_mirror() -> None:
    """Powody obejścia: backend zapisuje etykietę, front ją pokazuje — jedna
    lista w dwóch miejscach."""
    source = (
        Path(__file__).resolve().parents[2] / "frontend/src/lib/cv-qc.ts"
    ).read_text()
    block = source.split("export const QC_OVERRIDE_REASONS", 1)[1].split("];", 1)[0]
    mirrored = re.findall(r'code:\s*"([a-z_]+)",\s*label:\s*"([^"]+)"', block)
    assert mirrored == list(qc.OVERRIDE_REASONS.items())


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


async def _mark_critical(world: dict, *names: str) -> None:
    """Wybór Delivery Leada: umiejętności krytyczne w profilu Championa."""
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.champion_profile = {
            "stack": {
                "must": [{"name": n} for n in ("Java", "Kubernetes")],
                "critical": list(names),
            }
        }
        await db.commit()


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
    await _mark_critical(world, "Java", "Kubernetes")
    try:
        with hydrated_taxonomy():
            resp = await api_client.get(
                f"/api/pipeline/stages/{stage_id}/qc", headers=hor
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [c["key"] for c in body["checks"]] == [
            *qc.BLOCKING_KEYS,
            *qc.WARNING_KEYS,
        ]
        # Dwie umiejętności krytyczne do poprawy: Java w Globex, Kubernetes w Acme.
        assert body["passed"] is False and body["blocking_failed"] == 2
        assert body["cv"]["source"] == "branded_draft" and body["cv"]["editable"]
        assert body["client_request"]["must"] == ["Java", "Kubernetes"]
        assert body["client_request"]["critical"] == ["Java", "Kubernetes"]
        assert body["client_request"]["critical_source"] == "dl"
        assert body["override"] is None and body["run_id"]
        # Treść CV idzie jako bloki tekstu — skrypt z edytora odpada.
        assert "alert" not in json.dumps(body["cv"]["blocks"])

        with hydrated_taxonomy():
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
    await _mark_critical(world, "Java", "Kubernetes")
    send = {
        "candidate_id": world["candidate_id"],
        "job_id": world["job_id"],
        "stage_def_id": world["defs"]["cv_sent"],
        "client_rate_value": "180",
        "client_rate_unit": "hourly",
        "client_rate_currency": "PLN",
    }
    override_url = f"/api/pipeline/stages/{stage_id}/qc/override"
    try:
        with hydrated_taxonomy():
            refused = await api_client.post("/api/pipeline/move", headers=dl, json=send)
        assert refused.status_code == 409, refused.text
        detail = refused.json()["detail"]
        assert detail["code"] == "CV_QC_FAILED"
        assert detail["blocking_failed"] == 2
        assert detail["stage_id"] == stage_id
        assert detail["message"] == "CV nie przeszło QC — do poprawy: 2."
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
            override_url, headers=rec, json={"reason_code": "client_short_cv"}
        )
        assert denied.status_code == 403
        # Bez powodu, „Inny powód” bez opisu i nieznany kod — odmowa.
        for body in (
            {},
            {"reason_code": "other", "reason": "   "},
            {"reason_code": "bo_tak", "reason": "Klient prosił."},
        ):
            refused_override = await api_client.post(
                override_url, headers=dl, json=body
            )
            assert refused_override.status_code == 422, body
        with hydrated_taxonomy():
            ok = await api_client.post(
                override_url, headers=dl, json={"reason_code": "client_short_cv"}
            )
        assert ok.status_code == 200, ok.text
        # Gotowy powód nie wymaga opisu — w historii zostaje jego etykieta.
        assert ok.json()["override"]["reason"] == "Klient prosił o krótsze CV"
        async with AsyncSessionLocal() as db:
            details = await db.scalar(
                select(Activity.details).where(
                    Activity.action == "cv_qc_override",
                    Activity.entity_id == stage_id,
                )
            )
            status = await qc.pair_statuses(
                db, [(world["candidate_id"], world["job_id"])]
            )
        assert details["reason_code"] == "client_short_cv"
        assert details["reason"] == "Klient prosił o krótsze CV"
        assert (
            status[(world["candidate_id"], world["job_id"])]["status"] == "overridden"
        )
        # Front sprzed zmiany wysyła sam opis — działa jak „Inny powód”,
        # bez minimum znaków.
        with hydrated_taxonomy():
            legacy = await api_client.post(
                override_url, headers=dl, json={"reason": "bo tak"}
            )
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()["override"]["reason"] == "bo tak"

        with hydrated_taxonomy():
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
    await seed_entry_row(world["candidate_id"], world["job_id"])
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
    await seed_entry_row(world["candidate_id"], world["job_id"])
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
    await seed_entry_row(world["candidate_id"], world["job_id"])
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
    Cpro. Od rundy 9 (R9-N11-4) taka para wchodzi WYŁĄCZNIE do „Nowych”/
    „Screeningu” (422 — także w paczce), a po wejściu bez CV firmowego QC
    nie przechodzi."""

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
    move_body = {
        "candidate_id": world["candidate_id"],
        "job_id": world["job_id"],
        "stage_def_id": world["defs"]["cv_sent"],
        **rate,
    }
    try:
        refused = await api_client.post(
            "/api/pipeline/move", headers=dl, json=move_body
        )
        assert refused.status_code == 422, refused.text
        assert "nie ma jeszcze w rekrutacji" in refused.json()["detail"]

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
        assert bulk.status_code == 422, bulk.text
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

        # Osoba w „Nowych” — dalej bez CV firmowego QC nie przechodzi.
        await seed_entry_row(world["candidate_id"], world["job_id"])
        refused = await api_client.post(
            "/api/pipeline/move", headers=dl, json=move_body
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
async def test_bulk_move_keeps_the_template_stage(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runda 8 (R8-N8-6): `/bulk-move` zapisuje `stage_def_id` jak pojedynczy
    `/move` — bez niego kolejka Cpro i tablica nie widziały wiersza."""

    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    try:
        await _move(api_client, dl, world, "verified")
        bulk = await api_client.post(
            "/api/pipeline/bulk-move",
            headers=dl,
            json={
                "candidate_ids": [world["candidate_id"]],
                "job_id": world["job_id"],
                "stage": "cv_sent",
                "client_rate_value": "180",
                "client_rate_unit": "hourly",
                "client_rate_currency": "PLN",
            },
        )
        assert bulk.status_code == 200, bulk.text
        async with AsyncSessionLocal() as db:
            latest = await db.scalar(
                select(CandidateStage)
                .where(
                    CandidateStage.candidate_id == world["candidate_id"],
                    CandidateStage.job_id == world["job_id"],
                )
                .order_by(CandidateStage.id.desc())
                .limit(1)
            )
        assert latest.stage_def_id == world["defs"]["cv_sent"]
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


def test_years_in_one_company_must_match_the_role_dates() -> None:
    """„w tym 5 lat w FikcyjnaPłatność” przy roli 01.2024–obecnie (2,75 roku)
    — liczba bez pokrycia w datach w CV do klienta. Tolerancja to ±1 rok, więc
    rola od 01.2022 (4,75 roku) przy „5 lat” jest zgodna."""
    html = (
        "<ul><li>7 lat doświadczenia jako Python Developer, w tym 5 lat w "
        "FikcyjnaPłatność Sp. z o.o.</li></ul>" + BRANDED_HTML
    )
    history = [
        {
            "company": "FikcyjnaPłatność Sp. z o.o.",
            "start": "2024-01",
            "end": "obecnie",
        },
        {"company": "Bank Testowy", "start": "2019-01", "end": "2023-12"},
    ]
    by = _by_key(
        qc.compute_checks(_qc_input(html, experience=history, today=date(2026, 10, 5)))
    )
    assert by["years_header"]["status"] == "fail"
    assert by["years_header"]["severity"] == "warning"
    assert any(
        "FikcyjnaPłatność" in (i["detail"] or "") for i in by["years_header"]["items"]
    )

    # W tolerancji (4,75 roku przy „5 lat”) — bez uwagi.
    within = [{**history[0], "start": "2022-01"}]
    assert (
        qc.company_year_claims(
            _blocks("<ul><li>w tym 5 lat w FikcyjnaPłatność</li></ul>"),
            within,
            today=date(2026, 10, 5),
        )
        == []
    )

    # Technologia to nie firma z historii — bez uwagi.
    assert (
        qc.company_year_claims(
            _blocks("<ul><li>5 lat w Java i Spring.</li></ul>"),
            history,
            today=date(2026, 10, 5),
        )
        == []
    )


def test_bold_term_needs_a_whole_word_in_the_original() -> None:
    """Q1 (audyt 06.10.2026): „Scala” nie ma pokrycia w „scalanie danych”,
    „Ruby” w „rubryce” — porównanie podłańcuchem przepuszczało zmyśloną
    technologię przez blokujące sprawdzenie."""
    assert not qc._phrase_in_sources("Scala", "Odpowiadał za scalanie danych w ETL")
    assert not qc._phrase_in_sources("Ruby", "Uzupełniał każdą rubrykę raportu")
    # Odmiana dalej pokryta formą podstawową w oryginale.
    assert qc._phrase_in_sources("Dockera", "Wdrożenia: Docker, Kubernetes")
    assert qc._phrase_in_sources("Java 11", "Java (wersja 11)")


def test_company_claim_needs_two_words_not_a_generic_first_word() -> None:
    """Q5: „IT”, „Bank”, „Grupa” na początku nazwy to nie firma — klucz po
    pierwszym słowie łączył „3 lata w IT Kontrakt” z „IT Solutions”."""
    history = [
        {"company": "IT Solutions Sp. z o.o.", "start": "2025-01", "end": "obecnie"},
        {"company": "Bank Pekao S.A.", "start": "2024-01", "end": "obecnie"},
    ]
    blocks = _blocks(
        "<ul><li>8 lat w IT Kontrakt, w tym 6 lat w Bank Millennium.</li></ul>"
    )
    assert qc.company_year_claims(blocks, history, today=date(2026, 10, 5)) == []
    # Ta sama firma (dwa słowa nazwy) — uwaga zostaje.
    claims = qc.company_year_claims(
        _blocks("<ul><li>w tym 6 lat w Bank Pekao</li></ul>"),
        history,
        today=date(2026, 10, 5),
    )
    assert [c[2] for c in claims] == ["Bank Pekao S.A."]
