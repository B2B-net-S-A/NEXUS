"""Dwa adresy administracji: widoczny dla ludzi i skrzynka M365 NEXUSA.

* ``ADMIN_CASES_MAILBOX`` — adres, który ludzie czytają i na który piszą
  (administracja@). Trafia do autoodpowiedzi urlopowej („w pilnych sprawach”),
  do nagłówka Reply-To komunikatów i maila powitalnego oraz na ekrany.
* ``ADMIN_CASES_M365_MAILBOX`` — skrzynka w Microsoft 365, którą czytnik spraw
  czyta przez Graph i z której NEXUS wysyła. Potrzebna, gdy adres widoczny nie
  jest skrzynką M365: od 18.10.2026 administracja@ zostaje na home.pl, a NEXUS
  dostaje kopię poczty do nexus-administracja@ (wariant B, decyzja Artura).

Pusta jedna zmienna = obie role ma druga, więc skrzynka przeniesiona do M365
(jeden adres) dalej działa z samą ``ADMIN_CASES_MAILBOX``. Czytnik spraw liczy
to samo ze zmiennych środowiska (``mail_ingest.mailbox_upn``).
"""

from __future__ import annotations

from typing import Optional

from app.core.config import settings


def _clean(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    return text or None


def public_address() -> Optional[str]:
    """Adres administracji widoczny dla ludzi (autoodpowiedź, Reply-To, ekrany)."""

    return _clean(settings.ADMIN_CASES_MAILBOX) or _clean(
        settings.ADMIN_CASES_M365_MAILBOX
    )


def m365_mailbox() -> Optional[str]:
    """UPN skrzynki M365, którą NEXUS czyta i z której wysyła."""

    return _clean(settings.ADMIN_CASES_M365_MAILBOX) or _clean(
        settings.ADMIN_CASES_MAILBOX
    )
