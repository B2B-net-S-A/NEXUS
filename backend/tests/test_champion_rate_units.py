"""A document rate becomes a budget only when the document says PLN per hour.

#1477's retention fix kept the parser's `rate_value` whenever the document
text in `rate_raw` did not parse as one PLN/h number. That was meant for a
PLN/h range ("120–140 zł/h"), but it equally kept "45 EUR/h", "1200 PLN/MD"
and "20 000 PLN/mies. brutto" as a PLN/h budget — and
`fill_job_columns_from_champion` copied the number into an empty
`jobs.rate_budget_hourly`, where scoring and the rate dealbreaker read it as
the candidate's maximum hourly rate.

The text is the source of truth: a PLN-per-hour text gives the budget — one
value, or the UPPER bound of a range / "do X" (the field is the candidate's
maximum and the dealbreaker reads it as a ceiling; the parser's midpoint
understated it), noted as a warning. Everything else is unresolved and
reported as a missing budget, whatever number the model put next to it — and
an import must not undo that.
"""

import uuid
from contextlib import asynccontextmanager
from io import BytesIO

import pytest
from docx import Document
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.services.champion_intake import prepare_profile, user_edit, validation
from app.services.champion_profile_ingest import build_champion_dict
from tests.test_champion_intake_v4 import filled

RATE = "basics.rate_value"

# (document text, number the model put next to it). The second and fourth
# rows are the dangerous ones: the model converted the unit on its own, so the
# number looks like a plausible hourly rate.
NOT_PLN_PER_HOUR = [
    ("45 EUR/h", 45.0),
    ("1200 PLN/MD", 1200.0),
    ("1200 PLN/MD", 150.0),
    ("20 000 PLN/mies. brutto", 125.0),
]


def parsed(number, raw) -> dict:
    """What the AI parser returns for a document without the Word v4 tables."""
    return {
        "basics": {
            "role_name": "Senior Java Developer",
            "rate_value": number,
            "rate_raw": raw,
            "work_mode": "zdalnie",
        },
        "stack": {"must": [{"name": "Java 17"}], "nice": []},
        "project": {"about": "Platforma płatności.", "responsibilities": "API"},
        "screening_questions": [
            {
                "id": "q1",
                "question": "Jak projektujesz idempotentne API?",
                "ideal_answer": "Klucze idempotencji i ponowienia.",
                "deal_breaker": "",
            },
            {
                "id": "q2",
                "question": "Jak planujesz migrację?",
                "ideal_answer": "Etapy, ryzyka i plan wycofania.",
                "deal_breaker": "",
            },
        ],
    }


def ai_preview(number, raw) -> dict:
    """`preview_document`'s AI path: build the dict, normalise it once."""
    return prepare_profile(build_champion_dict(parsed(number, raw), None))


def codes(profile, job=None) -> set[tuple[str, str]]:
    return {(i["code"], i["path"]) for i in validation(profile, job)["issues"]}


# ── The rule itself ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,number", NOT_PLN_PER_HOUR)
def test_a_rate_in_another_unit_is_unresolved_not_kept(raw, number) -> None:
    cp = ai_preview(number, raw)

    assert cp["basics"]["rate_value"] is None, f"{raw!r} was kept as {number} PLN/h"
    assert cp["basics"]["rate_raw"] == raw
    assert cp["intake"]["unresolved"][RATE] == raw
    assert RATE not in cp["intake"]["advisory"]
    assert {("missing_budget", RATE), ("unresolved_value", RATE)} <= codes(cp)


@pytest.mark.parametrize(
    "raw,number",
    [
        ("120–140 zł/h", 130.0),  # the parser's midpoint
        ("120-140 PLN/h", 120.0),
        ("120 - 140 zł/h netto", 140.0),
        ("120 zł/h – 140 zł/h", 125.0),
        ("do 140 PLN/h", 140.0),
        ("do 140 PLN/h netto", 110.0),
        ("max. 140 zł/godz. + VAT", 135.0),
        # The model's number does not matter — even outside the range.
        ("120–140 zł/h", 200.0),
        ("120–140 zł/h", 119.99),
        ("do 140 PLN/h", 150.0),
        ("120/140 zł/h", None),
        ("do 140 zł netto/h", None),
    ],
)
def test_a_pln_per_hour_range_or_bound_gives_its_upper_bound_with_an_advisory(
    raw, number
) -> None:
    cp = ai_preview(number, raw)

    assert cp["basics"]["rate_value"] == 140.0
    assert cp["basics"]["rate_raw"] == raw
    assert cp["intake"]["advisory"][RATE] == raw
    assert RATE not in cp["intake"]["unresolved"]
    issues = {i["code"]: i for i in validation(cp)["issues"]}
    assert issues["rate_source_ambiguous"]["severity"] == "warning"
    assert issues["rate_source_ambiguous"]["blocked_operations"] == []
    assert "górną granicę" in issues["rate_source_ambiguous"]["message"]
    assert "missing_budget" not in issues


@pytest.mark.parametrize(
    "raw,number",
    [
        ("120–140 EUR/h", 130.0),
        ("120–140 zł/h brutto", 130.0),
        ("120–140 zł", 130.0),  # no unit: per hour is a guess
        ("130 zł/h lub 1000 zł/MD", 130.0),
        ("stawka do negocjacji", 130.0),
    ],
)
def test_a_number_the_document_text_does_not_back_is_unresolved(raw, number) -> None:
    cp = ai_preview(number, raw)

    assert cp["basics"]["rate_value"] is None
    assert cp["intake"]["unresolved"][RATE] == raw
    assert ("missing_budget", RATE) in codes(cp)


@pytest.mark.parametrize(
    "raw,number",
    [
        ("140 zł/h", 999.0),
        ("140 zł/h", 150.0),
        ("140 zł netto/h", 150.0),
        ("140 zł/h (netto, B2B)", None),
        ("Stawka: 140 zł/h", 130.0),
    ],
)
def test_a_single_pln_per_hour_rate_wins_over_the_parser_number(raw, number) -> None:
    cp = ai_preview(number, raw)

    assert cp["basics"]["rate_value"] == 140.0
    assert cp["basics"]["rate_raw"] == raw
    assert RATE not in cp["intake"]["unresolved"]
    # One value, not a range: nothing to warn about.
    assert RATE not in cp["intake"]["advisory"]


def test_a_parser_number_without_a_document_text_is_kept() -> None:
    cp = ai_preview(135.0, None)

    assert cp["basics"]["rate_value"] == 135.0
    assert cp["basics"]["rate_raw"] is None
    assert RATE not in cp["intake"]["unresolved"]
    assert RATE not in cp["intake"]["advisory"]


def test_the_word_form_rate_cell_is_read_as_document_text() -> None:
    """The v4 table puts the cell text into `raw_fields`, not `rate_raw`."""
    stored = filled()
    profile = {**stored, "basics": {**stored["basics"], "rate_value": "140 zł/h netto"}}

    cp = prepare_profile(profile, raw_fields={RATE: "140 zł/h netto"})

    assert cp["basics"]["rate_value"] == 140.0
    assert cp["basics"]["rate_raw"] == "140 zł/h netto"
    assert RATE not in cp["intake"]["unresolved"]


# ── The import branch of `user_edit` must not undo it ────────────────────────


def stale_preview(number, raw) -> dict:
    """The preview shape produced before this fix: number kept, text advisory."""
    cp = ai_preview(None, raw)
    cp["basics"]["rate_value"] = number
    cp["intake"]["unresolved"].pop(RATE, None)
    cp["intake"]["advisory"] = {RATE: raw}
    return cp


def stored_with_budget(value: float = 99.0) -> dict:
    """A stored v4 profile whose budget no row of the tables above carries.

    An import whose number EQUALS the stored budget keeps the stored budget
    whole (see `test_an_import_that_keeps_the_stored_number_keeps_its_text`).
    """
    cp = filled()
    cp["basics"].update(rate_value=value, rate_raw=f"{value:g} zł/h")
    return cp


@pytest.mark.parametrize("old", [{}, "filled"])
@pytest.mark.parametrize("raw,number", NOT_PLN_PER_HOUR)
def test_import_does_not_turn_a_foreign_unit_into_a_budget(old, raw, number) -> None:
    stored = stored_with_budget() if old == "filled" else {}

    for preview in (ai_preview(number, raw), stale_preview(number, raw)):
        imported = user_edit(stored, preview, 7, imported=True)

        assert imported["basics"]["rate_value"] is None
        # The document text survives; it is not replaced by the number.
        assert imported["basics"]["rate_raw"] == raw
        assert imported["intake"]["unresolved"][RATE] == raw
        assert ("missing_budget", RATE) in codes(imported)


@pytest.mark.parametrize("old", [{}, "filled"])
def test_import_keeps_a_range_warning_next_to_the_upper_bound(old) -> None:
    stored = stored_with_budget() if old == "filled" else {}

    imported = user_edit(stored, ai_preview(130.0, "120–140 zł/h"), 7, imported=True)

    assert imported["basics"]["rate_value"] == 140.0
    assert imported["basics"]["rate_raw"] == "120–140 zł/h"
    assert imported["intake"]["advisory"][RATE] == "120–140 zł/h"
    assert "rate_source_ambiguous" in {code for code, _ in codes(imported)}


@pytest.mark.parametrize(
    "incoming_raw", [None, "140", "1200 PLN/MD", "120–150 zł/h", "45 EUR/h"]
)
def test_an_import_that_keeps_the_stored_number_keeps_its_text(incoming_raw) -> None:
    """An unchanged budget is never re-derived — whatever text comes with it."""
    stored = stored_with_budget(140.0)
    stored["basics"]["rate_raw"] = "do 140 zł netto/h"
    stored["intake"]["advisory"][RATE] = "do 140 zł netto/h"

    imported = user_edit(
        stored,
        {"basics": {"rate_value": "140", "rate_raw": incoming_raw}, "intake": {}},
        7,
        imported=True,
    )

    assert imported["basics"]["rate_value"] == 140.0
    assert imported["basics"]["rate_raw"] == "do 140 zł netto/h"
    assert imported["intake"]["advisory"][RATE] == "do 140 zł netto/h"
    assert RATE not in imported["intake"]["unresolved"]


def test_a_changed_number_without_text_is_a_typed_budget() -> None:
    stored = stored_with_budget(140.0)
    stored["intake"]["advisory"][RATE] = "140 zł/h"

    imported = user_edit(
        stored, {"basics": {"rate_value": "150", "rate_raw": None}}, 7, imported=True
    )

    assert imported["basics"]["rate_value"] == 150.0
    assert imported["basics"]["rate_raw"] is None
    assert RATE not in imported["intake"]["advisory"]
    assert RATE not in imported["intake"]["unresolved"]


def test_validation_reads_the_stored_budget_not_a_re_read_of_its_text() -> None:
    """A parser midpoint stored before the upper-bound rule, synced to the job.

    Re-reading "120–140 zł/h" gives 140 now; comparing THAT with the column
    (130, synced from the stored 130) reported a conflict between two equal
    values in the database — with the gate on, a blocked search.
    """
    from tests.test_champion_intake_v4 import job

    cp = filled()
    cp["basics"].update(rate_value=130.0, rate_raw="120–140 zł/h")
    draft = job(cp)
    draft.rate_budget_hourly = 130

    issues = {i["code"]: i for i in validation(cp, draft)["issues"]}

    assert "column_conflict" not in issues
    assert "missing_budget" not in issues
    # The text is still re-read for its warning.
    assert issues["rate_source_ambiguous"]["severity"] == "warning"


def test_a_typed_number_still_replaces_the_document_text_in_the_editor() -> None:
    """Outside an import the number is the Delivery Lead's own decision."""
    stored = user_edit({}, ai_preview(None, "45 EUR/h"), 7, imported=True)

    edited = user_edit(stored, {"basics": {"rate_value": 180}}, 7)

    assert edited["basics"]["rate_value"] == 180.0
    assert RATE not in edited["intake"]["unresolved"]


# ── API: preview → apply-import never fills `jobs.rate_budget_hourly` ────────


def _docx() -> bytes:
    document = Document()
    document.add_paragraph("Profil Championa — rola Java, opis w treści.")
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


async def _seed_job() -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Synthetic Champion rate {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        job = Job(
            title="Synthetic Java role",
            status=JobStatus.draft,
            client_id=client.id,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _job(job_id: int) -> Job:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Job).where(Job.id == job_id))


@pytest.fixture
def ai_document(monkeypatch):
    """The AI parser answers with the given rate; quota and re-embed stubbed."""
    answer: dict = {}

    async def fake_parse(text):
        return parsed(answer["number"], answer["raw"])

    @asynccontextmanager
    async def no_quota(*args, **kwargs):
        yield None

    async def no_refresh(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.services.champion_profile_ingest.parse_champion_document", fake_parse
    )
    monkeypatch.setattr("app.services.ai_quota.ai_feature", no_quota)
    monkeypatch.setattr(
        "app.services.job_matching_refresh.refresh_job_matching", no_refresh
    )
    return answer


async def _preview(app_client, headers) -> dict:
    response = await app_client.post(
        "/api/champion/preview",
        files={
            "file": (
                "profil.docx",
                _docx(),
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document",
            )
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["champion_profile"]


async def _apply(app_client, headers, job_id: int, profile: dict) -> dict:
    route = f"/api/jobs/{job_id}/champion-profile"
    before = (await app_client.get(route, headers=headers)).json()
    response = await app_client.post(
        route + "/apply-import",
        json={
            "profile": profile,
            "expected_fingerprint": before["fingerprint"],
            "sync_fields": [],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("raw,number", NOT_PLN_PER_HOUR)
async def test_apply_import_of_a_foreign_unit_leaves_the_budget_empty(
    app_client, app_auth_headers, ai_document, raw, number
):
    ai_document.update(raw=raw, number=number)
    job_id = await _seed_job()

    preview = await _preview(app_client, app_auth_headers)
    applied = await _apply(app_client, app_auth_headers, job_id, preview)

    profile = applied["champion_profile"]
    assert profile["basics"]["rate_value"] is None
    assert profile["basics"]["rate_raw"] == raw
    assert profile["intake"]["unresolved"][RATE] == raw
    issue_codes = {(i["code"], i["path"]) for i in applied["validation"]["issues"]}
    assert {("missing_budget", RATE), ("unresolved_value", RATE)} <= issue_codes
    assert applied["job_values"]["rate_value"] is None
    assert (await _job(job_id)).rate_budget_hourly is None


async def test_apply_import_of_a_stale_preview_cannot_fill_the_budget(
    app_client, app_auth_headers, ai_document
):
    """A preview computed before the fix still carries the kept number."""
    job_id = await _seed_job()

    applied = await _apply(
        app_client, app_auth_headers, job_id, stale_preview(1200.0, "1200 PLN/MD")
    )

    assert applied["champion_profile"]["basics"]["rate_value"] is None
    assert applied["champion_profile"]["basics"]["rate_raw"] == "1200 PLN/MD"
    assert (await _job(job_id)).rate_budget_hourly is None


async def test_editor_import_flow_keeps_the_unresolved_text(
    app_client, app_auth_headers, ai_document
):
    """The import dialog: preview → edited copy → /validate → apply-import.

    `ChampionImportReview` puts the unresolved text into the rate field, sends
    it back as `rate_value` with `rate_raw = null` and empties `unresolved`.
    """
    ai_document.update(raw="45 EUR/h", number=45.0)
    job_id = await _seed_job()
    preview = await _preview(app_client, app_auth_headers)
    shown = preview["intake"]["unresolved"].get(RATE) or preview["basics"]["rate_value"]
    assert shown == "45 EUR/h", "the dialog would show the number, not the text"
    edited = {
        **preview,
        "basics": {**preview["basics"], "rate_value": shown, "rate_raw": None},
        "intake": {**preview["intake"], "policy_version": 1, "unresolved": {}},
    }

    checked = await app_client.post(
        "/api/champion/validate", json={"profile": edited}, headers=app_auth_headers
    )
    assert checked.status_code == 200, checked.text
    applied = await _apply(
        app_client, app_auth_headers, job_id, checked.json()["champion_profile"]
    )

    assert applied["champion_profile"]["basics"]["rate_value"] is None
    assert (await _job(job_id)).rate_budget_hourly is None


async def test_apply_import_of_a_pln_per_hour_range_budgets_its_upper_bound(
    app_client, app_auth_headers, ai_document
):
    ai_document.update(raw="120–140 zł/h", number=130.0)
    job_id = await _seed_job()

    preview = await _preview(app_client, app_auth_headers)
    applied = await _apply(app_client, app_auth_headers, job_id, preview)

    profile = applied["champion_profile"]
    assert profile["basics"]["rate_value"] == 140.0
    assert profile["basics"]["rate_raw"] == "120–140 zł/h"
    assert profile["intake"]["advisory"][RATE] == "120–140 zł/h"
    issue_codes = {i["code"] for i in applied["validation"]["issues"]}
    assert "rate_source_ambiguous" in issue_codes
    assert "missing_budget" not in issue_codes
    assert float((await _job(job_id)).rate_budget_hourly) == 140.0
