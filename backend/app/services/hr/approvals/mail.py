"""Mail do decydującego o zgodzie: kwota, po co i przyciski (decyzja Artura 20.10.2026).

Wyjątek od maila „Czas i ludzie” (``services/hr/hr_mail.py`` wycina kwoty
i wolny tekst): decyzję z maila da się podjąć tylko, gdy mail mówi, ile i po
co. Kwota i uzasadnienie idą WYŁĄCZNIE do osoby, która o zgodzie decyduje
(dzwonek ``hr_approval_requested`` dostaje tylko ona); autor dostaje decyzję
zwykłym mailem bez wolnego tekstu.

Mail składa się z wiersza zgody w chwili wysyłki: zgoda już rozpatrzona albo
na etapie kogoś innego = bez maila (``None``). Przyciski otwierają NEXUS
(logowanie jak zwykle) na tej zgodzie z wybraną decyzją do potwierdzenia.

Etap 2 (20.10.2026, ``mail_reply.reply_mailbox()`` niepuste): temat niesie
znacznik ``[Zgoda <id>/<kod>]``, mail ma Reply-To na skrzynkę zgód
(``notification_email_outbox``), a odpowiedź „approved” zatwierdza zgodę
(``mail_reader.py``). Inna treść wraca do autora jako pytanie.
"""

from __future__ import annotations

import html
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_approval import ApprovalRequest
from app.models.notification import Notification
from app.models.user import User
from app.services.email import absolute_link, open_button_html
from app.services.hr.approvals import mail_reply
from app.services.hr.approvals.service import (
    KIND_LABELS,
    amount_text,
    can_decide,
    finals_for_request,
    request_link,
)
from app.services.hr.payroll_periods import label

PURPOSE_MAIL_MAX = 600


def _short(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def render(
    db: AsyncSession, notif: Notification, user: User
) -> Optional[tuple[str, str, str]]:
    """(temat, tekst, HTML) albo ``None``, gdy mail nie ma już sensu."""

    if (
        notif.related_entity_type != "approval_request"
        or notif.related_entity_id is None
    ):
        return None
    request = await db.get(ApprovalRequest, notif.related_entity_id)
    if request is None:
        return None
    finals = await finals_for_request(db, request)
    if not can_decide(user.id, request, finals):
        return None
    names = dict(
        (
            await db.execute(
                select(User.id, User.name).where(
                    User.id.in_(
                        [
                            uid
                            for uid in (
                                request.requester_user_id,
                                request.beneficiary_user_id,
                                request.endorsed_by,
                            )
                            if uid is not None
                        ]
                    )
                )
            )
        ).all()
    )
    requester = names.get(request.requester_user_id, "")
    kind = KIND_LABELS[request.kind]
    subject_line = kind
    facts: list[tuple[str, str]] = [("Kwota", amount_text(request))]
    if request.kind == "bonus":
        person = names.get(request.beneficiary_user_id, "")
        subject_line = f"{kind} — {person}"
        facts.append(("Dla", person))
        if request.payout_year and request.payout_month:
            facts.append(("Wypłata", label(request.payout_year, request.payout_month)))
    if request.needed_by:
        facts.append(("Potrzebne do", request.needed_by.strftime("%d.%m.%Y")))
    if request.endorsed_by:
        facts.append(("Poparł(a)", names.get(request.endorsed_by, "")))
    purpose = _short(request.purpose, PURPOSE_MAIL_MAX)
    base = request_link(request.id)
    approve = absolute_link(f"{base}&decide=approve")
    decline = absolute_link(f"{base}&decide=reject")
    open_link = absolute_link(base)

    subject = f"[Nexus] Zgoda: {subject_line} — {amount_text(request)}"
    by_reply = mail_reply.reply_mailbox() is not None
    if by_reply:
        subject += f" {mail_reply.marker(request.id, request.submitted_at)}"
    reply_hint = (
        "Możesz też odpowiedzieć na tego maila jednym słowem „approved” — to "
        "jak „Zatwierdź”. Każda inna odpowiedź wróci do autora jako pytanie."
    )
    lines = [
        f"Cześć {user.name or user.email},",
        "",
        f"{requester} prosi o zgodę: {kind.lower()} — {request.title}.",
        "",
        *(f"{key}: {value}" for key, value in facts),
        "",
        f"Po co: {purpose}",
        "",
        f"Zatwierdź: {approve}",
        f"Odrzuć albo dopytaj: {decline}",
        f"Otwórz w Nexusie: {open_link}",
        "",
        *([reply_hint, ""] if by_reply else []),
        "— Nexus ATS",
    ]
    rows = "".join(
        f'<tr><td style="color:#64748b;padding:2px 16px 2px 0">{html.escape(key)}</td>'
        f'<td style="font-weight:600">{html.escape(value)}</td></tr>'
        for key, value in facts
    )
    html_body = (
        f"<p>Cześć {html.escape(user.name or user.email)},</p>"
        f"<p><strong>{html.escape(requester)}</strong> prosi o zgodę: "
        f"{html.escape(kind.lower())} — {html.escape(request.title)}.</p>"
        f'<table style="border-collapse:collapse;margin:8px 0">{rows}</table>'
        f'<p style="white-space:pre-line"><span style="color:#64748b">Po co:</span> '
        f"{html.escape(purpose)}</p>"
        f"<p>{open_button_html(approve, 'Zatwierdź')} &nbsp; "
        f'<a href="{html.escape(decline, quote=True)}" style="display:inline-block;'
        "border:1px solid #cbd5e1;color:#0f172a;padding:9px 18px;border-radius:6px;"
        'text-decoration:none;font-weight:500">Odrzuć albo dopytaj</a> &nbsp; '
        f'<a href="{html.escape(open_link, quote=True)}">Otwórz w Nexusie</a></p>'
        + (f"<p>{html.escape(reply_hint)}</p>" if by_reply else "")
        + '<hr><p style="color:#888;font-size:12px">Przyciski otwierają zgodę w Nexusie '
        "— decyzję potwierdzasz tam. Nexus ATS</p>"
    )
    return subject, "\n".join(lines), html_body


__all__ = ["render"]
