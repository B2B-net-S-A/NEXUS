"""Treści maili do kandydatów. Bez formy Pan/Pani, bo płci nie znamy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from app.core.scheduling import DEFAULT_TZ
from app.services.own_hiring.slots import day_label


@dataclass(frozen=True)
class MailText:
    subject: str
    body_html: str


def when_label(moment: datetime) -> str:
    local = moment.astimezone(ZoneInfo(DEFAULT_TZ))
    return f"{day_label(local.date())}, {local:%H:%M}"


def invitation(*, role_title: str, minutes: int, link: str) -> MailText:
    role = escape(role_title)
    href = escape(link, quote=True)
    body = (
        "<p>Dzień dobry,</p>"
        f"<p>dziękuję za zgłoszenie na stanowisko {role}. Twoje doświadczenie "
        "zwróciło moją uwagę i chciałbym porozmawiać.</p>"
        f"<p>Proponuję krótką rozmowę na Teams, około {minutes} minut. "
        "Termin wybierzesz samodzielnie:</p>"
        f'<p><a href="{href}">Wybierz termin rozmowy</a></p>'
        "<p>Jeśli żaden termin nie pasuje albo rekrutacja jest już nieaktualna, "
        "wystarczy odpowiedzieć na tę wiadomość.</p>"
    )
    return MailText(f"Rozmowa o pracy: {role_title}", body)


def reminder(
    *, role_title: str, start: datetime, office_address: str, link: str
) -> MailText:
    place = (
        f"w biurze: {escape(office_address)}"
        if office_address
        else "w miejscu podanym w zaproszeniu"
    )
    href = escape(link, quote=True)
    online = office_address == ""
    where = "na Teams, link jest w zaproszeniu w kalendarzu" if online else place
    body = (
        "<p>Dzień dobry,</p>"
        f"<p>przypominam o naszej rozmowie: {escape(when_label(start))}, {where}.</p>"
        f'<p>Jeśli termin się zmienił: <a href="{href}">zmień lub odwołaj</a>.</p>'
    )
    return MailText(f"Przypomnienie o rozmowie: {role_title}", body)


def meeting_description(*, role_title: str, link: str) -> str:
    href = escape(link, quote=True)
    return (
        f"<p>Rozmowa o stanowisku {escape(role_title)}.</p>"
        f'<p><a href="{href}">Zmień lub odwołaj termin</a></p>'
    )


def office_description(*, role_title: str, address: str) -> str:
    return (
        f"<p>Druga rozmowa o stanowisku {escape(role_title)}, w biurze.</p>"
        f"<p>Adres: {escape(address)}</p>"
    )
