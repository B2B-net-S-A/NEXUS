"""
Duplicate detection for candidates.

Dwie rzeczy, których nie wolno mylić (decyzja Artura, 12.10.2026):

* **Ta sama osoba = ten sam e-mail** — `find_candidate_by_email`. Tylko to
  wolno brać, gdy kod DECYDUJE: odmawia założenia kandydata albo podpina CV do
  istniejącego profilu (okno „Dodaj kandydata”, `/from-cv`, poczta M365,
  import masowy). Inny e-mail to inna osoba — bez ostrzeżeń.
* **Możliwe duplikaty** — `find_candidate_duplicates`. Lista podpowiedzi dla
  człowieka (okno scalania, `/check-duplicates`) i wyszukanie profilu po
  adresie LinkedIn we wtyczce. Niczego sama nie blokuje.

Match score semantics (`find_candidate_duplicates`):
  1.00 — email exact, or phone last-9-digits match
  0.95 — linkedin slug match (`…linkedin.com/in/<slug>`)
  0.90 — exact (name, lastname) match after lower-case normalization
  0.00 — below threshold, not returned
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate


def _normalize_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    return email.strip().lower() or None


def _normalize_phone(phone: Optional[str]) -> Optional[str]:
    """Keep only digits, match by last 9 (handles +48 prefixes, spaces, dashes)."""
    if not phone:
        return None
    digits = re.sub(r"[^\d]", "", phone)
    return digits[-9:] if len(digits) >= 9 else digits or None


def _normalize_name(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return s.strip().lower() or None


def _linkedin_slug(url: Optional[str]) -> Optional[str]:
    """Identyfikator profilu z adresu `…linkedin.com/in/<slug>`, inaczej None.

    Do 12.10.2026 był to ostatni kawałek po „/” z DOWOLNEJ wartości pola, więc
    „linkedin.com”, „LinkedIn” czy „?locale=en_US” stawały się identyfikatorem
    osoby — na produkcji 34 obce osoby z „linkedin.com” w polu wychodziły jako
    „podobni kandydaci” (1 579 z 27 583 wartości nie było adresem profilu).
    """
    from app.services.proxycurl import normalize_linkedin_url

    canonical = normalize_linkedin_url(url)
    if not canonical:
        return None
    return canonical.rsplit("/", 1)[-1].lower() or None


async def find_candidate_by_email(
    db: AsyncSession,
    email: Optional[str],
    *,
    exclude_candidate_id: Optional[int] = None,
) -> list[dict]:
    """Kandydaci z tym adresem e-mail (bez rozróżniania wielkości liter).

    Reguła „ta sama osoba = ten sam e-mail”. Zwykle jeden wiersz; kilka tylko
    dla par sprzed tej reguły, różniących się wielkością liter (unikalny indeks
    jest na surowej kolumnie) — stąd stała kolejność po id.

    Wyrażenie musi zostać DOKŁADNIE `lower(btrim(email))`: tylko wtedy planer
    bierze `ix_candidates_email_lower_btrim` (`test_candidate_email_lower_index`).
    """
    norm_email = _normalize_email(email)
    if not norm_email:
        return []

    stmt = select(
        Candidate.id, Candidate.name, Candidate.lastname, Candidate.email
    ).where(func.lower(func.btrim(Candidate.email)) == norm_email)
    if exclude_candidate_id is not None:
        stmt = stmt.where(Candidate.id != exclude_candidate_id)
    stmt = stmt.order_by(Candidate.id).limit(5)

    rows = (await db.execute(stmt)).all()
    return [
        {
            "candidate_id": row.id,
            "name": row.name,
            "lastname": row.lastname,
            "email": row.email,
            "match_score": 1.0,
            "match_reasons": ["email_exact"],
        }
        for row in rows
    ]


async def find_candidate_duplicates(
    db: AsyncSession,
    *,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    linkedin: Optional[str] = None,
    name: Optional[str] = None,
    lastname: Optional[str] = None,
    exclude_candidate_id: Optional[int] = None,
    min_score: float = 0.85,
) -> list[dict]:
    """
    Return candidates that match any of the identifiers, sorted by match_score desc.

    Podpowiedzi dla człowieka, nie reguła tożsamości — patrz docstring modułu.

    Each entry: {candidate_id, name, lastname, email, match_score, match_reasons}
    """
    norm_email = _normalize_email(email)
    norm_phone = _normalize_phone(phone)
    norm_linkedin_slug = _linkedin_slug(linkedin)
    norm_name = _normalize_name(name)
    norm_lastname = _normalize_name(lastname)

    clauses = []
    if norm_email:
        clauses.append(func.lower(func.btrim(Candidate.email)) == norm_email)
    if norm_phone:
        # Compare last-9-digits of stored phone after stripping non-digits
        clauses.append(
            func.regexp_replace(Candidate.phone, r"[^0-9]", "", "g").ilike(
                f"%{norm_phone}"
            )
        )
    if norm_linkedin_slug:
        # `linkedin_slug` to kolumna generowana z indeksem częściowym (0106,
        # bez pustych) — stąd jawne `!= ''`. Bez zapasowego `ILIKE` na surowym
        # polu: dla krótkiej końcówki ładował pół bazy przy każdym sprawdzeniu.
        clauses.append(
            (Candidate.linkedin_slug != "")
            & (Candidate.linkedin_slug == norm_linkedin_slug)
        )
    if norm_name and norm_lastname:
        clauses.append(
            (func.lower(Candidate.name) == norm_name)
            & (func.lower(Candidate.lastname) == norm_lastname)
        )

    if not clauses:
        return []

    # Tylko kolumny potrzebne do porównania — pełny wiersz niesie tekst CV.
    stmt = select(
        Candidate.id,
        Candidate.name,
        Candidate.lastname,
        Candidate.email,
        Candidate.phone,
        Candidate.linkedin_slug,
    ).where(or_(*clauses))
    if exclude_candidate_id is not None:
        stmt = stmt.where(Candidate.id != exclude_candidate_id)

    result = await db.execute(stmt)
    candidates = result.all()

    matches: list[dict] = []
    for c in candidates:
        reasons: list[str] = []
        score = 0.0

        if norm_email and c.email and c.email.strip().lower() == norm_email:
            reasons.append("email_exact")
            score = max(score, 1.0)

        if norm_phone and c.phone:
            cphone = _normalize_phone(c.phone)
            if cphone and cphone == norm_phone:
                reasons.append("phone_exact")
                score = max(score, 1.0)

        # Powód z kolumny, którą dopasował SQL — ponowne liczenie z surowego
        # pola w Pythonie gubiłoby wiersze (np. adres mobilny `/mwlite/in/…`).
        if norm_linkedin_slug and c.linkedin_slug == norm_linkedin_slug:
            reasons.append("linkedin_slug_match")
            score = max(score, 0.95)

        if (
            norm_name
            and norm_lastname
            and c.name
            and c.lastname
            and c.name.strip().lower() == norm_name
            and c.lastname.strip().lower() == norm_lastname
        ):
            reasons.append("name_exact")
            score = max(score, 0.9)

        if score >= min_score:
            matches.append(
                {
                    "candidate_id": c.id,
                    "name": c.name,
                    "lastname": c.lastname,
                    "email": c.email,
                    "match_score": round(score, 2),
                    "match_reasons": reasons,
                }
            )

    # Drugi klucz po id: wtyczka LinkedIn bierze pierwszy wiersz, a kilka
    # profili potrafi dzielić ten sam identyfikator.
    matches.sort(key=lambda x: (-x["match_score"], x["candidate_id"]))
    return matches
