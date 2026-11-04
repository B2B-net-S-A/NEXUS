"""Zgody, etap 2 — rozpoznanie odpowiedzi mailem (bez bazy i bez sieci).

Zatwierdza tylko samo słowo w pierwszej linii nowej treści (dalej najwyżej
podpis); cytat poprzedniego maila się nie liczy; znacznik w temacie ma kod
związany z wersją zgody; nadawca musi być sobą (``from`` = ``sender``, bez
nieudanego SPF/DKIM/DMARC). Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email import message_from_string

import pytest

import app.services.email as email_mod
import app.services.m365.app_mail as app_mail
from app.core.config import settings
from app.services.hr.approvals import mail_reader, mail_reply
from tests.test_mail_circuit import memory_circuit  # noqa: F401

SIGNER = "Jan Testowy"
SUBMITTED = datetime(2026, 10, 20, 9, 30, 12, 345678, tzinfo=timezone.utc)


def _classify(text: str, signer: str | None = SIGNER) -> mail_reply.Reply:
    return mail_reply.classify(text, signer_name=signer)


# ── Słowa ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    ["approved", "Approved.", "OK", "ok!", "Zgoda", "tak", "  approved  ", "Okay"],
)
def test_the_word_alone_approves(text: str) -> None:
    assert _classify(text).kind == "approve"


@pytest.mark.parametrize(
    "text",
    [
        "not approved",
        "ok?",
        "OK ?",
        "ok, ale do 500 zł",
        "nie",
        "approved?",
        "tak, ale po rozmowie",
        "zgoda na połowę",
    ],
)
def test_anything_else_is_a_question_for_the_author(text: str) -> None:
    reply = _classify(text)
    assert reply.kind == "other"
    assert reply.text == text.strip()


def test_signature_after_the_word_still_approves() -> None:
    assert _classify("approved\n\nJan Testowy\nCEO\n+48 000 000 000").kind == "approve"
    assert _classify("ok\nPozdrawiam,\nJan").kind == "approve"
    assert _classify("ok\nPozdrawiam, Jan").kind == "approve"
    assert _classify("Approved\n--\nJan Testowy").kind == "approve"
    assert _classify("tak\n\nSent from Outlook for iOS").kind == "approve"
    assert _classify("ok\nDzięki").kind == "approve"
    assert _classify("ok\nDzięki\nJan Testowy\nCEO").kind == "approve"


def test_a_second_line_of_content_is_not_a_signature() -> None:
    assert _classify("ok\nale tylko do 500 zł").kind == "other"
    assert _classify("ok\nDzięki, ale do 500 zł").kind == "other"
    # Sam zwrot, a po nim treść — to nie podpis.
    assert _classify("tak\nDzięki\nale tylko do 500 zł").kind == "other"
    # Bez znanego podpisu druga linia to treść — wraca jako pytanie, nie zgoda.
    assert _classify("approved\nCEO", signer=None).kind == "other"


def test_empty_reply_decides_nothing() -> None:
    assert _classify("").kind == "empty"
    assert _classify("\n\nPozdrawiam\nJan Testowy").kind == "empty"


def test_long_question_is_cut_to_the_note_limit() -> None:
    reply = _classify("a po co? " * 300)
    assert reply.kind == "other"
    assert len(reply.text) <= 1000 and reply.text.endswith("…")


# ── Nowa treść bez cytatu ────────────────────────────────────────────────────

QUOTE_HTML = (
    '<div id="divRplyFwdMsg"><b>Od:</b> Nexus<br><b>Temat:</b> [Nexus] Zgoda</div>'
    "<div>Możesz też odpowiedzieć jednym słowem „approved”</div>"
)


def test_outlook_html_reply_keeps_only_the_new_text() -> None:
    body = (
        "<html><head><style>p{margin:0}</style></head><body>"
        "<div>Approved</div>"
        '<div id="Signature"><p>Jan Testowy</p><p>CEO</p></div>'
        '<div id="appendonsend"></div><hr>' + QUOTE_HTML + "</body></html>"
    )
    text = mail_reply.new_text(body, "html")
    assert text == "Approved"
    assert _classify(text).kind == "approve"


def test_quote_alone_never_approves() -> None:
    # Pusta odpowiedź na mail, którego cytat zawiera słowo „approved”.
    body = '<div><br></div><div id="appendonsend"></div><hr>' + QUOTE_HTML
    assert mail_reply.new_text(body, "html") == ""


def test_plain_text_quote_and_gmail_style_are_cut() -> None:
    text = mail_reply.new_text(
        "a po co nam to?\n\nW dniu 20.10.2026 o 10:00 Nexus napisał:\n> approved",
        "text",
    )
    assert text == "a po co nam to?"
    text = mail_reply.new_text(
        "ok\r\n\r\nFrom: Nexus <nexus@example.com>\r\nSent: Tuesday\r\napproved",
        "text",
    )
    assert text == "ok"
    html_text = mail_reply.new_text(
        '<div dir="ltr">tak</div><div class="gmail_quote">approved</div>', "html"
    )
    assert html_text == "tak"


def test_desktop_outlook_signature_bookmark_is_cut() -> None:
    body = '<p>ok</p><p><a name="_MailAutoSig">Jan</a> CEO, firma</p>'
    assert mail_reply.new_text(body, "html") == "ok"


# ── Znacznik ─────────────────────────────────────────────────────────────────


def test_marker_round_trip_and_version_binding(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret")
    marker = mail_reply.marker(42, SUBMITTED)
    subject = f"RE: [Nexus] Zgoda: Delegacja — 980 zł brutto {marker}"
    found = mail_reply.find_marker(subject)
    assert found is not None and found[0] == 42
    assert mail_reply.code_matches(42, SUBMITTED, found[1])
    # Poprawka autora zmienia ``submitted_at`` — stara odpowiedź nie pasuje.
    assert not mail_reply.code_matches(42, SUBMITTED + timedelta(minutes=5), found[1])
    # Sam numer zgody wpisany ręcznie nic nie zatwierdzi.
    assert not mail_reply.code_matches(43, SUBMITTED, found[1])
    assert mail_reply.find_marker("RE: [Nexus] Zgoda 42") is None


def test_marker_found_in_quote_when_subject_was_edited(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", "test-secret")
    marker = mail_reply.marker(7, SUBMITTED)
    assert mail_reply.find_marker("RE: zmieniony temat", f"...{marker}...") == (
        7,
        marker[-9:-1],
    )


def test_reply_mailbox_needs_flag_and_address(monkeypatch) -> None:
    monkeypatch.setattr(settings, "HR_APPROVALS_REPLY_MAILBOX", " zgody@example.com ")
    monkeypatch.setattr(settings, "HR_APPROVALS_MAIL_REPLY_ENABLED", False)
    assert mail_reply.reply_mailbox() is None
    monkeypatch.setattr(settings, "HR_APPROVALS_MAIL_REPLY_ENABLED", True)
    assert mail_reply.reply_mailbox() == "zgody@example.com"
    monkeypatch.setattr(settings, "HR_APPROVALS_REPLY_MAILBOX", "")
    assert mail_reply.reply_mailbox() is None


# ── Nadawca i autoodpowiedź ──────────────────────────────────────────────────


def _msg(**extra) -> dict:
    msg = {
        "from": {"emailAddress": {"address": "CEO@example.com"}},
        "sender": {"emailAddress": {"address": "ceo@example.com"}},
        "subject": "RE: [Nexus] Zgoda",
        "internetMessageHeaders": [],
    }
    msg.update(extra)
    return msg


def test_sender_must_be_himself() -> None:
    assert mail_reader.sender_address(_msg()) == "ceo@example.com"
    on_behalf = _msg(sender={"emailAddress": {"address": "assistant@example.com"}})
    assert mail_reader.sender_address(on_behalf) is None
    assert mail_reader.sender_address(_msg(**{"from": None})) is None


@pytest.mark.parametrize(
    "headers",
    [
        # Bez nagłówków uwierzytelnienia — nie decydujemy (fail-closed).
        [],
        [{"name": "Authentication-Results", "value": "spf=fail; dmarc=fail"}],
        [{"name": "Authentication-Results", "value": "spf=softfail; dmarc=pass"}],
        [{"name": "Authentication-Results", "value": "dkim=none; compauth=fail"}],
        [{"name": "X-MS-Exchange-Organization-AuthAs", "value": "Anonymous"}],
        [
            {"name": "X-MS-Exchange-Organization-AuthAs", "value": "Internal"},
            {"name": "Authentication-Results", "value": "dmarc=fail"},
        ],
    ],
)
def test_unconfirmed_or_spoofed_mail_is_not_authenticated(headers) -> None:
    assert not mail_reader.authenticated(_msg(internetMessageHeaders=headers))


def test_internal_or_dmarc_pass_mail_is_authenticated() -> None:
    internal = [
        {"name": "X-MS-Exchange-Organization-AuthAs", "value": "Internal"},
        {"name": "Authentication-Results", "value": "dkim=none (message not signed)"},
    ]
    assert mail_reader.authenticated(_msg(internetMessageHeaders=internal))
    dmarc = [{"name": "Authentication-Results", "value": "spf=pass; dmarc=pass"}]
    assert mail_reader.authenticated(_msg(internetMessageHeaders=dmarc))


def test_auto_reply_is_recognized() -> None:
    assert mail_reader.is_auto_reply(
        _msg(
            internetMessageHeaders=[{"name": "Auto-Submitted", "value": "auto-replied"}]
        )
    )
    assert mail_reader.is_auto_reply(_msg(subject="Automatic reply: [Nexus] Zgoda"))
    assert not mail_reader.is_auto_reply(_msg())


# ── Reply-To w wysyłce ───────────────────────────────────────────────────────


def test_smtp_message_carries_reply_to() -> None:
    raw = email_mod._build_message(
        "ceo@example.com", "s", "t", None, "zgody@example.com"
    ).as_string()
    assert message_from_string(raw)["Reply-To"] == "zgody@example.com"
    plain = email_mod._build_message("ceo@example.com", "s", "t").as_string()
    assert message_from_string(plain)["Reply-To"] is None


def test_graph_message_carries_reply_to(monkeypatch, memory_circuit) -> None:  # noqa: F811
    for key, value in {
        "M365_APP_MAIL_ENABLED": True,
        "M365_MAIL_SENDER_UPN": "nexus@example.com",
        "M365_CLIENT_ID": "cid",
        "M365_CLIENT_SECRET": "secret",
        "M365_APP_MAIL_CLIENT_ID": "",
        "M365_APP_MAIL_CLIENT_SECRET": "",
        "M365_MAIL_TENANT_ID": "contoso.onmicrosoft.com",
    }.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(app_mail, "_acquire_token", lambda: "tok")
    captured: list[dict] = []

    class _Resp:
        status_code = 202

    def _post(url, json=None, headers=None, timeout=None):
        captured.append(json)
        return _Resp()

    monkeypatch.setattr(app_mail.httpx, "post", _post)
    assert app_mail.send_via_graph_app(
        to="ceo@example.com", subject="s", text_body="t", reply_to="zgody@example.com"
    )
    assert app_mail.send_via_graph_app(to="ceo@example.com", subject="s", text_body="t")
    assert captured[0]["message"]["replyTo"] == [
        {"emailAddress": {"address": "zgody@example.com"}}
    ]
    assert "replyTo" not in captured[1]["message"]
