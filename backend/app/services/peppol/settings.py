"""Ustawienia e-faktur Peppol (``app_settings['peppol_einvoices']``).

* ``mode`` — ``test`` (domyślnie): każda wysyłka idzie na adres testowy
  odbiorcy; ``production``: na adres produkcyjny. Finanse obawiają się
  prawdziwej faktury w Vismie Nordei, której nie da się anulować, więc tryb
  produkcyjny włącza się świadomie, po udanym teście.
* ``auto_send`` — wyłącznik automatycznej wysyłki (domyślnie wyłączony):
  pętla pobierania z KSeF wysyła faktury „do wysłania” sama, gdy Finanse go
  włączą. Bez niego wysyłka tylko przyciskiem.
* ``since`` — od której daty wystawienia faktury dostają e-fakturę (starszych
  nie doczytujemy z KSeF, żeby nie zużywać limitu pobrań).
* ``receivers`` — nabywcy w sieci Peppol po numerze VAT z faktury
  (``FI28583949``, ``PL…``): adres produkcyjny, adres testowy i identyfikator
  rejestrowy. Adresy to publiczne dane katalogu Peppol (directory.peppol.eu).
  Brak adresu w danym trybie = faktura czeka (``waiting_receiver``).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.user import User

SETTING_KEY = "peppol_einvoices"
MODES = ("test", "production")
DEFAULT_SINCE = "2026-11-01"
_PEPPOL_ID_RE = re.compile(r"^[0-9]{4}:[A-Za-z0-9.\-_:]{1,50}$")
_KEY_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{2,30}$")
NAME_MAX = 200
MAX_RECEIVERS = 30

#: Nordea (plan N2, katalog Peppol 13.11.2026). Testowe adresy Nordei są
#: w produkcyjnej sieci Peppol: „Nordea Bank Abp Spolka Akcyjna (test)”
#: 0088:7332545042126 i „Nordea Bank Abp (test)” 0088:7332545042089. Oddział
#: w Polsce nie ma w katalogu adresu produkcyjnego — jego faktury czekają.
DEFAULT_RECEIVERS: tuple[dict[str, Any], ...] = (
    {
        "key": "FI28583949",
        "name": "Nordea Bank Abp",
        "peppol_id": "0088:7332545014840",
        "test_peppol_id": "0088:7332545042126",
        "legal_id": "2858394-9",
        "legal_id_scheme": "0212",
    },
    {
        "key": "FI01123053",
        "name": "Nordea Rahoitus Suomi Oy",
        "peppol_id": "0088:7332545014857",
        "test_peppol_id": "0088:7332545042126",
        "legal_id": None,
        "legal_id_scheme": None,
    },
    {
        "key": "PL1050003082",
        "name": "Nordea Bank Abp S.A. Oddział w Polsce",
        "peppol_id": None,
        "test_peppol_id": "0088:7332545042126",
        "legal_id": None,
        "legal_id_scheme": None,
    },
)


class SettingsError(ValueError):
    pass


def _clean_id(raw: object) -> Optional[str]:
    value = str(raw or "").strip()
    if not value:
        return None
    if not _PEPPOL_ID_RE.match(value):
        raise SettingsError(f"Adres Peppol „{value[:60]}” ma zły format (schemat:numer, np. 0088:7332545014840).")
    return value


def _receiver(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SettingsError("Zły wpis odbiorcy.")
    key = str(raw.get("key") or "").replace(" ", "").upper()
    if not _KEY_RE.match(key):
        raise SettingsError("Numer VAT odbiorcy musi zaczynać się od kodu kraju (np. FI28583949).")
    legal_scheme = str(raw.get("legal_id_scheme") or "").strip() or None
    if legal_scheme and not re.match(r"^[0-9]{4}$", legal_scheme):
        raise SettingsError("Schemat identyfikatora rejestrowego to 4 cyfry (np. 0212).")
    return {
        "key": key,
        "name": str(raw.get("name") or key).strip()[:NAME_MAX],
        "peppol_id": _clean_id(raw.get("peppol_id")),
        "test_peppol_id": _clean_id(raw.get("test_peppol_id")),
        "legal_id": (str(raw.get("legal_id") or "").strip()[:64] or None),
        "legal_id_scheme": legal_scheme,
    }


def normalize(raw: object) -> dict[str, Any]:
    """Zapisane ustawienia uzupełnione domyślnymi (zły wpis = wartość domyślna)."""

    data = raw if isinstance(raw, dict) else {}
    mode = data.get("mode") if data.get("mode") in MODES else "test"
    since = data.get("since") if isinstance(data.get("since"), str) else DEFAULT_SINCE
    try:
        date.fromisoformat(since)
    except ValueError:
        since = DEFAULT_SINCE
    receivers: list[dict[str, Any]] = []
    stored = data.get("receivers")
    for entry in stored if isinstance(stored, list) else DEFAULT_RECEIVERS:
        try:
            receivers.append(_receiver(entry))
        except SettingsError:
            continue
    return {
        "mode": mode,
        "auto_send": data.get("auto_send") is True,
        "since": since,
        "receivers": receivers,
    }


async def load(db: AsyncSession) -> dict[str, Any]:
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING_KEY))
    return normalize(raw)


def validate_update(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    value = dict(current)
    if "mode" in patch:
        if patch["mode"] not in MODES:
            raise SettingsError("Tryb to „test” albo „production”.")
        value["mode"] = patch["mode"]
    if "auto_send" in patch:
        value["auto_send"] = bool(patch["auto_send"])
    if "since" in patch:
        try:
            value["since"] = date.fromisoformat(str(patch["since"])).isoformat()
        except ValueError as exc:
            raise SettingsError("Data „od” ma zły format (RRRR-MM-DD).") from exc
    if "receivers" in patch:
        entries = patch["receivers"]
        if not isinstance(entries, list) or len(entries) > MAX_RECEIVERS:
            raise SettingsError(f"Najwyżej {MAX_RECEIVERS} odbiorców.")
        receivers = [_receiver(entry) for entry in entries]
        keys = [entry["key"] for entry in receivers]
        if len(set(keys)) != len(keys):
            raise SettingsError("Ten sam numer VAT odbiorcy występuje dwa razy.")
        value["receivers"] = receivers
    return value


async def save(db: AsyncSession, value: dict[str, Any], *, actor: User) -> dict[str, Any]:
    """Zapis (bez commita)."""

    statement = insert(AppSetting).values(key=SETTING_KEY, value=value, updated_by=actor.id)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor.id},
        )
    )
    return value


def receiver_key(buyer_foreign_id: Optional[str], buyer_nip: Optional[str]) -> Optional[str]:
    """Klucz odbiorcy z faktury: VAT UE nabywcy albo „PL” + NIP."""

    if buyer_foreign_id:
        return buyer_foreign_id.replace(" ", "").upper()
    if buyer_nip:
        return f"PL{buyer_nip}"
    return None


def find_receiver(value: dict[str, Any], key: Optional[str]) -> Optional[dict[str, Any]]:
    if not key:
        return None
    return next((entry for entry in value["receivers"] if entry["key"] == key), None)


def address_for(receiver: dict[str, Any], mode: str) -> Optional[str]:
    return receiver.get("test_peppol_id") if mode == "test" else receiver.get("peppol_id")
