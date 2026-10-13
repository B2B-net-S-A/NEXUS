"""„To nieprawda” i „Jakość QC” (D5, D6, 13.10.2026) — logika bez bazy.

Dane fikcyjne. Integracja (trasy, bramka ruchu, dzwonek DL) — w
`test_cv_qc.py`, sekcja „To nieprawda”.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services import cv_finding_dismissals as dismissals
from app.services import cv_qc as qc
from app.services import qc_quality
from app.services.dl_review import risks_for

AT = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def _dismissal(key: str, check_key: str = "must_in_cv") -> dict:
    return {
        "key": key,
        "source": "qc",
        "check_key": check_key,
        "label": key,
        "view": {
            "id": 1,
            "reason": "in_cv",
            "reason_label": "Jest w CV — QC tego nie znalazło",
            "note": None,
            "by_name": "Anna Testowa",
            "at": AT.isoformat(),
        },
    }


def _check(key: str, severity: str, items: list[dict]) -> dict:
    return {
        "key": key,
        "label": key,
        "severity": severity,
        "status": "fail" if items else "pass",
        "summary": f"{len(items)} do poprawy",
        "items": items,
        "roles": [],
        "info": [],
    }


def test_dismissed_item_moves_aside_and_check_passes() -> None:
    checks = [
        _check(
            "no_unsupported",
            "blocking",
            [{"key": "no_unsupported|graphql|cv", "requirement": "GraphQL"}],
        )
    ]
    blocking = dismissals.apply_dismissals(
        checks, [_dismissal("no_unsupported|graphql|cv", "no_unsupported")]
    )
    check = checks[0]
    assert blocking == 1
    assert check["status"] == "pass" and check["items"] == []
    assert check["dismissed_items"][0]["dismissal"]["by_name"] == "Anna Testowa"
    assert check["summary"].endswith("pominięte: 1")
    passed, blocking_failed, _ = qc.summarize(checks)
    assert passed and blocking_failed == 0
    assert qc.dismissed_blocking(checks) == 1


def test_cv_and_client_rules_cannot_be_dismissed() -> None:
    item = {"key": "client_rules|stawka|cv", "detail": "Stawka w CV"}
    checks = [_check("client_rules", "blocking", [item])]
    assert (
        dismissals.apply_dismissals(checks, [_dismissal(item["key"], "client_rules")])
        == 0
    )
    assert checks[0]["status"] == "fail" and checks[0]["items"] == [item]


def test_dismissing_a_role_does_not_hide_a_skill_missing_from_the_whole_cv() -> None:
    role_item = {
        "key": "critical_skills|kafka|developer · firma beta",
        "requirement": "Kafka",
        "role": "Developer · Firma Beta",
        "absent_in_cv": True,
    }
    checks = [_check("critical_skills", "blocking", [role_item])]
    dismissals.apply_dismissals(
        checks, [_dismissal(role_item["key"], "critical_skills")]
    )
    check = checks[0]
    assert check["status"] == "fail"
    assert [i["key"] for i in check["items"]] == ["critical_skills|kafka|cv"]


def test_compute_checks_marks_critical_role_items_absent_from_the_cv() -> None:
    from tests.test_cv_qc import EXPERIENCE, ORIGINAL, _blocks, _reqs

    html = (
        '<h2 data-cv-section="experience">Doświadczenie</h2>'
        '<p data-cv-section="role"><b>Senior Developer</b> 2021–obecnie</p>'
        '<p data-cv-section="employer">Acme Bank</p>'
        "<ul><li>Rozwój usług w Java i Spring dla systemu płatności.</li></ul>"
    )
    kafka = _reqs("Kafka")
    experience = [
        {
            **EXPERIENCE[0],
            "desc": "Zaprojektował przetwarzanie zdarzeń na Kafka w Acme Bank.",
        }
    ]
    data = qc.QcInput(
        must=kafka,
        nice=[],
        blocks=_blocks(html),
        has_cv=True,
        bold_known=True,
        original_text=ORIGINAL
        + "\nZaprojektował przetwarzanie zdarzeń na Kafka w Acme Bank.",
        experience=experience,
        critical=kafka,
    )
    check = next(c for c in qc.compute_checks(data) if c["key"] == "critical_skills")
    role_items = [i for i in check["items"] if i.get("role")]
    assert role_items and all(i["absent_in_cv"] for i in role_items)


@pytest.mark.parametrize(
    ("reason", "note", "error"),
    [
        ("nonsense", None, "Wybierz powód"),
        ("other", "   ", "Opisz"),
    ],
)
def test_reason_is_checked(reason: str, note: str | None, error: str) -> None:
    with pytest.raises(dismissals.DismissError, match=error):
        dismissals.validate_reason(reason, note)


def test_other_reason_keeps_a_trimmed_note() -> None:
    assert dismissals.validate_reason("other", "  to   jest  w CV ") == (
        "other",
        "to jest w CV",
    )


def test_text_key_ignores_spacing_case_and_marks_but_not_status() -> None:
    a = dismissals.text_key("WERYFIKUJ:  usunięto  OpenTelemetry")
    assert a == dismissals.text_key("weryfikuj: usunieto opentelemetry")
    assert dismissals.text_key("x", "unsupported") != dismissals.text_key(
        "x", "conflict"
    )


def test_bold_all_skips_a_requirement_marked_untrue() -> None:
    from tests.test_cv_qc import _reqs

    reqs = _reqs("Java", "Kafka")
    dismissed = {"must_bolded|kafka|cv"}
    assert [r.label for r in qc.without_dismissed_bold(reqs, "must", dismissed)] == [
        "Java"
    ]
    assert len(qc.without_dismissed_bold(reqs, "nice", dismissed)) == 2


def test_effective_states_manual_wins_and_blocking_stays_active() -> None:
    states = {
        "must_bolded": {"auto": "info", "manual": "active"},
        "title_matches_role": {"auto": "info"},
        "spelling": {"manual": "off"},
        "no_unsupported": {"manual": "off", "auto": "info"},
    }
    effective = qc_quality.effective_states(states)
    assert effective["must_bolded"] == "active"
    assert effective["title_matches_role"] == "info"
    assert effective["spelling"] == "off"
    assert effective["no_unsupported"] == "active"


def test_muted_and_off_checks_do_not_count_as_warnings() -> None:
    checks = [
        _check("title_matches_role", "warning", [{"key": "t", "detail": "Tytuł"}]),
        _check("spelling", "warning", [{"key": "s", "term": "Postgres"}]),
        _check("no_unsupported", "blocking", [{"key": "n", "term": "Redis"}]),
    ]
    qc_quality.apply_check_states(
        checks,
        {"title_matches_role": "info", "spelling": "off", "no_unsupported": "info"},
    )
    by = {c["key"]: c for c in checks}
    assert by["title_matches_role"]["muted"] is True
    assert by["spelling"]["status"] == "skip" and by["spelling"]["items"] == []
    assert "muted" not in by["no_unsupported"]
    passed, blocking, warnings = qc.summarize(checks)
    assert (passed, blocking, warnings) == (False, 1, 0)


def test_dl_sees_dismissed_blocking_findings() -> None:
    common = dict(
        eligibility_reason=None,
        eligibility_code=None,
        employed_elsewhere=[],
        worked_at_client=None,
        deal_breaker_hits=0,
        over_budget_by=None,
        sent_to_client_before=[],
        red_flags=None,
    )
    dismissed = risks_for(**common, qc_status="overridden", qc_dismissed=2)
    assert [r["code"] for r in dismissed] == ["qc_dismissed"]
    assert "(2)" in dismissed[0]["label"]
    override = risks_for(**common, qc_status="overridden")
    assert [r["code"] for r in override] == ["qc_overridden"]


def test_migration_is_mirrored_in_entrypoint_and_model() -> None:
    root = Path(__file__).resolve().parents[1]
    entry = (root / "entrypoint.sh").read_text()
    migration = (root / "alembic/versions/0438_cv_finding_dismissals.py").read_text()
    squash = lambda t: re.sub(r"\s+", " ", t)  # noqa: E731
    for fragment in (
        "CREATE TABLE IF NOT EXISTS cv_finding_dismissals (",
        "candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE",
        "candidate_stage_id INTEGER NULL REFERENCES candidate_stages(id) ON DELETE SET NULL",
        "finding_key VARCHAR(400) NOT NULL",
        "blocking BOOLEAN NOT NULL DEFAULT false",
        "restored_reason VARCHAR(16) NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_cv_finding_dismissals_active",
        "WHERE restored_at IS NULL",
        "CREATE INDEX IF NOT EXISTS ix_cv_finding_dismissals_created",
    ):
        assert fragment in squash(migration), fragment
        assert fragment in squash(entry), fragment
    assert 'down_revision = "0437_candidate_source_created_at"' in migration
    from app.models.cv_finding_dismissal import CvFindingDismissal

    columns = set(CvFindingDismissal.__table__.columns.keys())
    for name in re.findall(
        r"^    ([a-z_]+) [A-Z]", migration.split('"""CREATE TABLE')[1], re.M
    ):
        assert name in columns, name


@pytest.mark.asyncio
async def test_editor_moves_untrue_generator_and_review_findings_aside(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import cv_editor_issues

    warning = "WERYFIKUJ: usunięto OpenTelemetry"
    finding = {"text": "Ponad 10 lat w bankowości.", "status": "unsupported"}

    async def active(_db, _candidate_id, _job_id, _sources):
        view = {
            "id": 7,
            "reason": "not_needed",
            "reason_label": "Nie dotyczy tej rekrutacji",
            "note": None,
            "by_name": "Anna Testowa",
            "at": AT.isoformat(),
        }
        return [
            {
                "key": dismissals.text_key(warning),
                "source": "generator",
                "check_key": "generator",
                "label": warning,
                "view": view,
            },
            {
                "key": dismissals.text_key(finding["text"], "unsupported"),
                "source": "review",
                "check_key": "review",
                "label": finding["text"],
                "view": view,
            },
        ]

    monkeypatch.setattr(dismissals, "active", active)
    issues = {
        "generator_warnings": [warning, "Brak dat roli w Firmie Beta"],
        "content_review": {
            "status": "reviewed",
            "findings": [finding, {"text": "Inna linia", "status": "conflict"}],
            "version": 2,
        },
        "dismissed": [],
    }
    await cv_editor_issues._split_dismissed(object(), issues, (1, 2))
    assert issues["generator_warnings"] == ["Brak dat roli w Firmie Beta"]
    assert issues["content_review"]["findings"] == [
        {"text": "Inna linia", "status": "conflict"}
    ]
    assert {(d["source"], d["text"]) for d in issues["dismissed"]} == {
        ("generator", warning),
        ("review", finding["text"]),
    }


def test_checks_with_dismissals_can_be_hashed_and_stored() -> None:
    # Przegląd PR 3: datetime w widoku pominięcia wywracał `_checks_hash`
    # (zapis przebiegu) — każde „To nieprawda” kończyło się 500.
    checks = [
        _check(
            "must_bolded",
            "warning",
            [{"key": "must_bolded|kafka|cv", "requirement": "Kafka"}],
        )
    ]
    dismissals.apply_dismissals(
        checks, [_dismissal("must_bolded|kafka|cv", "must_bolded")]
    )
    assert isinstance(qc._checks_hash(checks), str)
    assert checks[0]["dismissed_items"][0]["dismissal"]["at"] == AT.isoformat()


@pytest.mark.asyncio
async def test_a_second_identical_dismissal_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Podwójne kliknięcie albo dwie osoby naraz: indeks częściowy odrzuca drugi
    # wiersz — to nie jest błąd, uwaga jest już pominięta.
    from sqlalchemy.exc import IntegrityError

    class _Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _Db:
        added: list = []

        def begin_nested(self):
            return _Nested()

        def add(self, row):
            self.added.append(row)

        async def flush(self):
            raise IntegrityError("insert", {}, Exception("duplicate key"))

    row = dismissals.new_row(
        candidate_id=1,
        job_id=2,
        stage_id=3,
        source="qc",
        check_key="must_bolded",
        key="must_bolded|kafka|cv",
        label="Kafka",
        reason="in_cv",
        note=None,
        quote=None,
        blocking=False,
        user_id=4,
    )
    assert await dismissals.insert_once(_Db(), row) is False
