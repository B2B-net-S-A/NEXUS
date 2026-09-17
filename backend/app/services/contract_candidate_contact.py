"""Kontakt do konsultanta na umowie — jedna reguła kolejności źródeł.

Ticket „E-mail i telefon kandydata w widoku kontraktu": karta „Informacje
o kontrakcie" pokazuje kontakt do konsultanta, biorąc go w kolejności

1. **umowa z generatora** — wpisane w „Dane Partnera" i zapisane na kontrakcie
   (`contracts.candidate_email` / `candidate_phone`), także ręczna poprawka
   w widoku kontraktu;
2. **profil kandydata** — `candidates.email` / `candidates.phone`;
3. nic — pole zostaje puste.

Dwie rzeczy, które łatwo cofnąć „przy okazji":

* **Kolumna na umowie jest NADPISANIEM, nie migawką.** Fallback do profilu
  liczy się przy ODCZYCIE, więc poprawiony w profilu telefon jest widoczny na
  umowie od razu — dopóki nikt nie wpisał na niej własnej wartości.
  Materializacja całej prawdy przy backfillu dawałaby umowy z kontaktem
  starzejącym się w ciszy.
* **Wyczyszczenie pola przywraca fallback.** Pusty string i ``None`` w PATCH
  normalizujemy do ``NULL``; gdyby pusty string zapisywał się dosłownie,
  „usunąłem wartość" znaczyłoby „zablokowałem profil na zawsze", a pusta
  komórka obok wypełnionego profilu czyta się jak utrata danych.

Moduł jest czysty (bez I/O i bez sesji) i świadomie wspólny dla widoku
kontraktu oraz raportu braków — raport MUSI pytać o to samo, co ekran, inaczej
wypisywałby do ręcznego uzupełnienia osoby, które na ekranie kontakt mają.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Protocol

from sqlalchemy import inspect as sa_inspect

# Lustro limitów kolumn (migracja 0320): e-mail jak `contracts.client_pm_email`,
# telefon jak `candidates.phone`. Dłuższa wartość jest odrzucana przy zapisie,
# nie przycinana — przycięty numer telefonu wygląda na poprawny i nie da się
# odróżnić od literówki.
EMAIL_MAX_LENGTH = 255
PHONE_MAX_LENGTH = 30

ContactSource = Literal["contract", "candidate_profile"]

SOURCE_CONTRACT: ContactSource = "contract"
SOURCE_CANDIDATE_PROFILE: ContactSource = "candidate_profile"


class _HasContact(Protocol):
    email: Optional[str]
    phone: Optional[str]


@dataclass(frozen=True)
class ResolvedContact:
    """Wartość pokazywana na ekranie plus informacja, skąd pochodzi."""

    email: Optional[str] = None
    email_source: Optional[ContactSource] = None
    phone: Optional[str] = None
    phone_source: Optional[ContactSource] = None


def _clean(value: Optional[str]) -> Optional[str]:
    """Puste, same białe znaki i ``None`` to jedno i to samo: brak wartości."""

    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _pick(
    override: Optional[str], profile: Optional[str]
) -> tuple[Optional[str], Optional[ContactSource]]:
    explicit = _clean(override)
    if explicit is not None:
        return explicit, SOURCE_CONTRACT
    fallback = _clean(profile)
    if fallback is not None:
        return fallback, SOURCE_CANDIDATE_PROFILE
    return None, None


def resolve_contact(
    *,
    contract_email: Optional[str],
    contract_phone: Optional[str],
    candidate: Optional[_HasContact],
) -> ResolvedContact:
    """Rozstrzygnij kontakt dla jednej umowy.

    ``candidate is None`` to legalny stan, nie błąd: umowa odpięta od usuniętego
    kandydata (migracja 0225) nadal musi się wyrenderować — wisi na niej
    historia podpisów i faktur. Wtedy zostaje samo nadpisanie z umowy, a gdy
    i ono jest puste (kasowanie kandydata je zeruje, art. 17 RODO) — nic.
    """

    profile_email = getattr(candidate, "email", None) if candidate else None
    profile_phone = getattr(candidate, "phone", None) if candidate else None
    email, email_source = _pick(contract_email, profile_email)
    phone, phone_source = _pick(contract_phone, profile_phone)
    return ResolvedContact(
        email=email,
        email_source=email_source,
        phone=phone,
        phone_source=phone_source,
    )


def _loaded_candidate(contract):
    """``contract.candidate`` tylko wtedy, gdy JUŻ jest w pamięci.

    Wszyscy dzisiejsi wołający robią ``selectinload(Contract.candidate)``, ale
    ta funkcja nie może wisieć na ich dyscyplinie: sięgnięcie po niezaładowaną
    relację w sesji async to ``MissingGreenlet``, czyli 500 BEZ nagłówków CORS —
    przeglądarka pokazuje wtedy „Network Error" bez statusu i bez powodu.
    Niezaładowana relacja degraduje więc do „brak profilu" (zostaje samo
    nadpisanie z umowy), zamiast wywracać cały odczyt kontraktu.
    """

    state = sa_inspect(contract, raiseerr=False)
    if state is not None and "candidate" in state.unloaded:
        return None
    return getattr(contract, "candidate", None)


def resolve_for_contract(contract) -> ResolvedContact:
    """Wygodna nakładka na obiekt ORM ``Contract`` z załadowanym kandydatem."""

    return resolve_contact(
        contract_email=getattr(contract, "candidate_email", None),
        contract_phone=getattr(contract, "candidate_phone", None),
        candidate=_loaded_candidate(contract),
    )


def normalize_email(value: Optional[str]) -> Optional[str]:
    """Zapisywany e-mail: przycięty, małymi literami, pusty → ``NULL``.

    ``lower()`` jest zgodne z ``dedup_service._normalize_email``, żeby ta sama
    skrzynka nie wyglądała na dwie różne w zależności od tego, kto ją wpisał.
    """

    cleaned = _clean(value)
    return cleaned.lower() if cleaned else None


def normalize_phone(value: Optional[str]) -> Optional[str]:
    """Zapisywany telefon: sam ``strip()``.

    Świadomie BEZ normalizacji do cyfr (`dedup_service._normalize_phone` tnie do
    ostatnich 9): tam chodzi o porównywanie, a tu o numer, który człowiek ma
    wybrać — prefiks kierunkowy i format zostają takie, jak je wpisano.
    """

    return _clean(value)


def email_too_long(value: Optional[str]) -> bool:
    return value is not None and len(value) > EMAIL_MAX_LENGTH


def phone_too_long(value: Optional[str]) -> bool:
    return value is not None and len(value) > PHONE_MAX_LENGTH
