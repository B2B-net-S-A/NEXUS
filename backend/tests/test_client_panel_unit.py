"""Panel klienta bez bazy: token, etykiety, stany, stempel, kontrakty repo."""

from __future__ import annotations

import ast
import io
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE
from fastapi import HTTPException

from app.core.config import settings
from app.services import client_panel as service
from app.services.client_panel_schema import TABLE_DDL
from app.services.client_panel_stamp import stamp_panel_link

BACKEND = Path(__file__).resolve().parents[1]


def _docx() -> bytes:
    document = Document()
    document.add_paragraph("")
    document.add_paragraph("Programista – Anna Przykładowa")
    document.add_paragraph("Treść CV")
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def test_token_is_deterministic_and_changes_with_the_nonce() -> None:
    first = service.compute_token(7, "a" * 32)
    assert first == service.compute_token(7, "a" * 32)
    assert first != service.compute_token(7, "b" * 32)
    assert first != service.compute_token(8, "a" * 32)
    assert len(first) == service.TOKEN_LENGTH
    assert service._TOKEN_RE.match(first)


def test_rotation_makes_a_new_token_and_keeps_only_the_digest() -> None:
    panel = SimpleNamespace(id=5, token_nonce=None, token_sha256=None)
    assert service.current_token(panel) is None
    old = service.issue_token(panel)
    assert panel.token_sha256 == service.token_digest(old)
    assert old not in (panel.token_sha256, panel.token_nonce)
    new = service.issue_token(panel)
    assert new != old
    assert panel.token_sha256 == service.token_digest(new)
    assert service.current_token(panel) == new


@pytest.mark.parametrize("token", ["", "abc", "A" * 16, "1" * 16, "a" * 17, "a/b"])
async def test_malformed_token_is_404_without_touching_the_database(token) -> None:
    with pytest.raises(HTTPException) as refused:
        await service.load_public_panel(None, token)  # type: ignore[arg-type]
    assert refused.value.status_code == 404


def test_urls_use_the_public_address(monkeypatch) -> None:
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://nexus.example.com/")
    assert service.panel_urls("abc") == (
        "https://nexus.example.com/k/abc",
        "nexus.example.com/k/abc",
    )
    assert service.panel_urls("abc", "pid")[0].endswith("/k/abc?c=pid")


def test_default_expiry_is_the_end_of_the_day_in_sixty_days() -> None:
    expiry = service.default_expiry(date(2031, 3, 1))
    assert expiry.date() == date(2031, 4, 30)
    assert (expiry.hour, expiry.minute) == (23, 59)


def test_expired_only_after_the_date() -> None:
    now = datetime(2031, 1, 1, tzinfo=timezone.utc)
    panel = SimpleNamespace(expires_at=now + timedelta(seconds=1))
    assert service.is_expired(panel, now) is False
    panel.expires_at = now
    assert service.is_expired(panel, now) is True
    panel.expires_at = None
    assert service.is_expired(panel, now) is False


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (None, "do ustalenia"),
        (date(2031, 1, 1), "od zaraz"),
        (date(2031, 1, 10), "od zaraz"),
        (date(2031, 2, 3), "od 03.02.2031"),
    ],
)
def test_available_label(available, expected) -> None:
    assert service.available_label(available, date(2031, 1, 10)) == expected


def _request(kind: str, status: str = "open") -> SimpleNamespace:
    return SimpleNamespace(kind=kind, status=status)


@pytest.mark.parametrize(
    ("requests", "slot", "expected"),
    [
        ([], None, "none"),
        ([_request("question")], None, "question_open"),
        ([_request("question", "answered")], None, "answered"),
        ([_request("question")], "awaiting_recruiter", "interview_requested"),
        ([], "awaiting_dl", "interview_requested"),
        ([_request("question")], "confirmed", "interview_confirmed"),
        ([], "cancelled", "none"),
        ([_request("not_fit", "closed")], "confirmed", "not_fit"),
    ],
)
def test_candidate_state_strongest_fact_wins(requests, slot, expected) -> None:
    slot_request = SimpleNamespace(status=slot) if slot else None
    assert service.candidate_state(requests, slot_request) == expected


def test_interview_block_shows_the_choice_only_when_confirmed() -> None:
    slots = [
        {"start": "2031-01-01T09:00:00+00:00", "end": "2031-01-01T10:00:00+00:00"},
        {"start": "2031-01-02T09:00:00+00:00", "end": "2031-01-02T10:00:00+00:00"},
    ]
    assert service.interview_block(None) == {
        "status": "none",
        "slots": [],
        "chosen": None,
    }
    waiting = SimpleNamespace(status="awaiting_dl", slots=slots, chosen_index=1)
    assert service.interview_block(waiting)["chosen"] is None
    done = SimpleNamespace(status="confirmed", slots=slots, chosen_index=1)
    block = service.interview_block(done)
    assert block["chosen"] == {"start": slots[1]["start"]}
    assert set(block["slots"][0]) == {"start", "end", "window_end"}
    gone = SimpleNamespace(status="cancelled", slots=slots, chosen_index=1)
    assert service.interview_block(gone)["slots"] == []


def test_blind_name_is_masked_like_the_public_view() -> None:
    person = SimpleNamespace(name="Anna", lastname="Przykładowa")
    cv = service.PairCv(1, None, None, "pl", True, None)
    assert service.person_name(person, cv) == "Kandydat"
    english = service.PairCv(1, None, None, "en", True, None)
    assert service.person_name(person, english) == "Candidate"
    open_cv = service.PairCv(1, None, None, "pl", False, None)
    assert service.person_name(person, open_cv) == "Anna Przykładowa"
    assert service._pdf_name(
        service.PairCv(1, None, "x_Anna.docx", "pl", True, None)
    ) == ("CV.pdf")


def test_ip_hash_never_contains_the_address_and_changes_daily() -> None:
    first = service.hash_ip("203.0.113.9", date(2031, 1, 1))
    assert "203.0.113.9" not in first
    assert len(first) == 64
    assert first == service.hash_ip("203.0.113.9", date(2031, 1, 1))
    assert first != service.hash_ip("203.0.113.9", date(2031, 1, 2))


# ── Stempel ──────────────────────────────────────────────────────────────────


def test_stamp_puts_a_frame_with_link_under_the_title() -> None:
    original = _docx()
    url = "https://nexus.example.com/k/abcdefghijklmnop?c=pid"
    stamped = stamp_panel_link(
        original,
        url,
        "nexus.example.com/k/abcdefghijklmnop",
        datetime(2031, 3, 1, 12, tzinfo=timezone.utc),
    )
    assert stamped != original
    document = Document(io.BytesIO(stamped))
    body = list(document.element.body)
    title_at = next(
        i for i, el in enumerate(body) if "Programista" in "".join(el.itertext())
    )
    assert body[title_at + 1].tag.endswith("}tbl")
    frame = document.tables[0]
    assert len(document.inline_shapes) == 1
    text = frame.rows[0].cells[1]._tc.xpath("string(.)")
    assert "nexus.example.com/k/abcdefghijklmnop" in text
    assert "01.03.2031" in text
    targets = [
        rel.target_ref
        for rel in document.part.rels.values()
        if rel.reltype == RELATIONSHIP_TYPE.HYPERLINK
    ]
    assert targets == [url]
    assert document.paragraphs[-1].text == "Treść CV"


def test_stamp_failure_returns_the_file_untouched() -> None:
    assert stamp_panel_link(b"not a docx", "u", "s", None) == b"not a docx"
    empty = io.BytesIO()
    Document().save(empty)
    assert stamp_panel_link(empty.getvalue(), "u", "s", None) == empty.getvalue()


# ── Kontrakty repo ───────────────────────────────────────────────────────────


def test_migration_and_entrypoint_share_one_ddl_source() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "from app.services import client_panel_schema as _client_panel_schema" in (
        entrypoint
    )
    assert "*_CLIENT_PANEL_DDL," in entrypoint
    assert (
        "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'client_panel_request'"
        in entrypoint
    )
    migration = (BACKEND / "alembic/versions/0633_client_panel.py").read_text(
        encoding="utf-8"
    )
    assert "schema.TABLE_DDL" in migration
    assert "client_panel_request" in migration
    assert any("CREATE TABLE IF NOT EXISTS client_panels" in s for s in TABLE_DDL)


@pytest.mark.parametrize(
    "table",
    [
        "client_panels",
        "client_panel_candidates",
        "client_panel_requests",
        "client_panel_views",
    ],
)
def test_tables_are_probed_by_deep_health(table: str) -> None:
    assert f'("{table}", ' in (BACKEND / "app/main.py").read_text(encoding="utf-8")


def test_public_module_has_no_future_annotations() -> None:
    tree = ast.parse(
        (BACKEND / "app/api/public_client_panel.py").read_text(encoding="utf-8")
    )
    assert not [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
    ]


def test_no_ai_import_in_the_public_path() -> None:
    for name in (
        "app/api/public_client_panel.py",
        "app/services/client_panel.py",
        "app/services/client_panel_evidence.py",
        "app/services/client_panel_requests.py",
    ):
        source = (BACKEND / name).read_text(encoding="utf-8")
        assert "ai_feature" not in source
        assert "ai_models" not in source
