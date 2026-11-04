"""Maile podpisu w NEXUSIE — ze skrzynki osoby, która wysłała umowę (M365).

Kontraktor zna nadawcę (Sandra, rekruter), więc mail z jego skrzynki budzi
mniej podejrzeń niż systemowy. Bez połączonej skrzynki nic nie wychodzi:
wołający pokazuje link do skopiowania albo zostawia sam dzwonek. Awaria
wysyłki nigdy nie cofa stanu wniosku.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_config
from app.models.m365 import M365Connection
from app.models.user import User
from app.services.b2b_esign.service import SIGNED_COPY_DAYS
from app.services.m365 import sender as m365_sender

logger = logging.getLogger(__name__)

MSG_NO_MAILBOX = "Twoja skrzynka Microsoft 365 nie jest połączona z NEXUSEM."
MSG_FAILED = "Nie udało się wysłać maila — wyślij link sam."

_WARSAW = ZoneInfo("Europe/Warsaw")
REGISTER_PATH = "/contracts/b2b-generator?tab=generated"

# Jeden wzór dla wszystkich maili obiegu (uwaga Klaudii 27.10.2026): bez
# „Pozdrawiamy, B2B Network”, bo pod treścią i tak jest stopka Outlooka
# nadawcy z „Pozdrawiam”; czcionka jak domyślna w Outlooku; akcja jako
# przycisk zamiast linku w środku akapitu. Style przechodzą przez wysyłkę
# dzięki ``styled_body`` w ``m365_sender.send_new``.
_FONT = (
    "font-family: Aptos, Calibri, Arial, sans-serif; font-size: 11pt; color: #1f1f1f"
)
_SMALL = (
    "font-family: Aptos, Calibri, Arial, sans-serif; font-size: 10pt; color: #5a5a5a"
)
_BRAND_RED = "#c8102e"
# Dopełniacz: „Link działa do poniedziałku 02.11.2026”.
_WEEKDAYS_GENITIVE = (
    "poniedziałku",
    "wtorku",
    "środy",
    "czwartku",
    "piątku",
    "soboty",
    "niedzieli",
)


def _p(text: str, *, small: bool = False, margin: str = "0 0 12px") -> str:
    return f'<p style="margin: {margin}; {_SMALL if small else _FONT}">{text}</p>'


def _button(url: str, label: str) -> str:
    """Przycisk z tabeli: Outlook z silnikiem Worda nie rysuje paddingu na ``<a>``."""
    return (
        '<table cellpadding="0" cellspacing="0" style="margin: 16px 0 6px">'
        f'<tr><td style="background-color: {_BRAND_RED}; padding: 10px 20px">'
        f'<a href="{html.escape(url)}" style="{_FONT}; color: #ffffff; '
        f'font-weight: bold; text-decoration: none">{label}</a>'
        "</td></tr></table>"
    )


def _deadline(moment: datetime) -> str:
    local = moment.astimezone(_WARSAW)
    return f"{_WEEKDAYS_GENITIVE[local.weekday()]} {local:%d.%m.%Y}"


def contractor_sign_message(
    *, number: str, url: str, expires_at: datetime, renewed: bool = False
) -> tuple[str, str]:
    """(temat, treść) maila do kontraktora z linkiem do podpisu.

    ``renewed``: nowy link po terminie na tym samym PDF-ie (27.10.2026) — plik
    podpisany wcześniej nadal przejdzie, więc mail to mówi."""
    num = html.escape(number)
    steps = "".join(
        f'<li style="margin: 0 0 3px; {_FONT}">{step}</li>'
        for step in (
            "Na stronie pobierz PDF umowy.",
            "Podpisz go kwalifikowanym podpisem elektronicznym.",
            "Wgraj podpisany plik na tej samej stronie.",
        )
    )
    lead = (
        f"poprzedni link do umowy o współpracy B2B nr {num} wygasł, przesyłam "
        "nowy. Umowa się nie zmieniła: jeśli plik jest już podpisany, wgraj go "
        "bez ponownego podpisu."
        if renewed
        else f"przesyłam do podpisu umowę o współpracy B2B nr {num}."
    )
    body = (
        _p("Dzień dobry,")
        + _p(lead, margin="0")
        + _button(url, "Otwórz umowę do podpisu")
        + _p(f"Link działa do {_deadline(expires_at)}.", small=True)
        + _p("<b>Jak podpisać</b>", margin="0 0 4px")
        + f'<ol style="margin: 0 0 12px; padding-left: 22px">{steps}</ol>'
        + _p(
            "Podpis kwalifikowany jest potrzebny, bo umowa przenosi autorskie "
            "prawa majątkowe. Jeśli go nie masz albo link nie działa, odpisz "
            "na tego maila.",
            small=True,
        )
    )
    subject = (
        f"Nowy link: umowa B2B nr {number} do podpisu"
        if renewed
        else f"Umowa B2B nr {number} do podpisu"
    )
    return subject, body


def contractor_extended_message(
    *, number: str, expires_at: datetime
) -> tuple[str, str]:
    """(temat, treść) maila o przedłużonym terminie (27.10.2026).

    Link się nie zmienia i żyje tylko w pierwszym mailu (w bazie jest jego
    skrót), więc mail mówi, że działa dłużej."""
    body = (
        _p("Dzień dobry,")
        + _p(
            f"termin podpisu umowy B2B nr {html.escape(number)} jest dłuższy. "
            "Link z poprzedniego maila działa teraz do "
            f"{_deadline(expires_at)}."
        )
        + _p(
            "Jeśli nie masz podpisu kwalifikowanego albo link nie działa, "
            "odpisz na tego maila.",
            small=True,
        )
    )
    return f"Umowa B2B nr {number}: dłuższy termin podpisu", body


def contractor_reminder_message(
    *, number: str, sent_at: datetime, expires_at: datetime
) -> tuple[str, str]:
    """(temat, treść) przypomnienia dla kontraktora.

    Sam link żyje tylko w pierwszym mailu (w bazie jest jego skrót), więc
    przypomnienie wskazuje tamten mail po dacie."""
    body = (
        _p("Dzień dobry,")
        + _p(
            f"przypominam o umowie B2B nr {html.escape(number)} z maila z "
            f"{sent_at.astimezone(_WARSAW):%d.%m.%Y}. Link do podpisu w tamtym "
            f"mailu działa do {_deadline(expires_at)}."
        )
        + _p(
            "Jeśli nie masz podpisu kwalifikowanego albo link nie działa, "
            "odpisz na tego maila.",
            small=True,
        )
    )
    return f"Przypomnienie: umowa B2B nr {number} czeka na podpis", body


def company_signer_message(
    *, number: str, contractor_name: str, since: datetime, reminder: bool
) -> tuple[str, str]:
    """(temat, treść) maila do osoby, która podpisuje za B2B Network.

    Olaf 26.10.2026: „nic mi nie przyszło” — był tylko dzwonek bez ikony."""
    link = f"{app_config.PUBLIC_BASE_URL.rstrip('/')}{REGISTER_PATH}"
    who = html.escape(contractor_name)
    num = html.escape(number)
    if reminder:
        subject = f"Przypomnienie: umowa B2B {number} nadal czeka na Twój podpis"
        lead = (
            f"umowa B2B nr {num} ma podpis kontraktora ({who}) od "
            f"{since.astimezone(_WARSAW):%d.%m.%Y} i nadal czeka na podpis "
            "za B2B Network."
        )
    else:
        subject = f"Umowa B2B {number} czeka na Twój podpis"
        lead = (
            f"umowa B2B nr {num} ma już podpis kwalifikowany kontraktora "
            f"({who}). Brakuje podpisu za B2B Network."
        )
    body = (
        _p("Cześć,")
        + _p(lead, margin="0")
        + _button(link, "Otwórz umowę w NEXUSIE")
        + _p(
            "Pobierz PDF, podpisz go podpisem kwalifikowanym (PAdES) i wgraj "
            "z powrotem. Kontraktor dostanie wtedy swój egzemplarz mailem.",
            small=True,
            margin="10px 0 12px",
        )
    )
    return subject, body


def contractor_copy_message(*, number: str) -> tuple[str, str]:
    """(temat, treść) maila z umową podpisaną przez obie strony (26.10.2026)."""
    subject = f"Umowa B2B {number} podpisana przez obie strony"
    body = (
        _p("Dzień dobry,")
        + _p(
            f"w załączniku umowa B2B nr {html.escape(number)} podpisana przez "
            "Ciebie i przez B2B Network. To Twój egzemplarz, zachowaj go."
        )
        + _p(
            f"Plik pobierzesz też ze strony podpisu przez {SIGNED_COPY_DAYS} dni.",
            small=True,
        )
    )
    return subject, body


async def cc_emails(db: AsyncSession, user_ids: Sequence[int]) -> list[str]:
    """Adresy osób w DW (aktywne konta z e-mailem) — w kolejności z wysyłki."""
    if not user_ids:
        return []
    rows = await db.execute(
        select(User.id, User.email).where(
            User.id.in_(list(user_ids)), User.is_active.is_(True)
        )
    )
    emails = {uid: email for uid, email in rows.all() if email}
    return [emails[uid] for uid in user_ids if uid in emails]


async def mailbox_connected(db: AsyncSession, user_id: int) -> bool:
    connection = await db.scalar(
        select(M365Connection).where(M365Connection.user_id == user_id)
    )
    return bool(connection and connection.is_active)


async def send_from(
    db: AsyncSession,
    *,
    user_id: int | None,
    to: str,
    subject: str,
    body_html: str,
    candidate_id: int | None,
    request_key: str,
    attachments: Sequence[m365_sender.FileAttachment] = (),
    cc: Sequence[str] = (),
) -> tuple[bool, Optional[str]]:
    """(wysłano, powód) — ``request_key`` chroni przed drugą wysyłką przy ponowieniu."""
    if not user_id or not to:
        return False, MSG_NO_MAILBOX
    connection = await db.scalar(
        select(M365Connection).where(M365Connection.user_id == user_id)
    )
    if connection is None or not connection.is_active:
        return False, MSG_NO_MAILBOX
    try:
        await m365_sender.send_new(
            db,
            connection,
            to=[to],
            cc=[address for address in cc if address and address != to],
            subject=subject,
            body_html=body_html,
            candidate_id=candidate_id,
            client_request_id=request_key,
            commit_reservation=True,
            attachments=attachments,
            styled_body=True,
        )
        await db.commit()
    except Exception:  # noqa: BLE001 — stan wniosku zostaje
        logger.exception("[b2b_esign] mail nie wyszedł key=%s", request_key)
        await db.rollback()
        return False, MSG_FAILED
    return True, None
