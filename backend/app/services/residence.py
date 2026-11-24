"""Osoby mieszkające poza Polską (decyzja Artura 24.11.2026).

System nie proponuje ich do żadnej rekrutacji: silnik „Nowych” ich nie
dodaje, a nietknięte karty od systemu znikają. Ręcznie można je dodać.
Na kopii produkcji z 24.11.2026 w 30 dni system dodał do „Nowych” 115 osób
z krajem w profilu innym niż Polska (61 spoza UE), a rekruterzy odrzucali je
głównie jako „Inne”.

Mieszka poza Polską = kraj w profilu (``Candidate.country``) inny niż ``PL``
i miasto spoza słownika polskich miejscowości. Miasto w Polsce wygrywa
z krajem, bo kraj bywa obywatelstwem: 23 profile mają np. kraj ``BY``
i miasto Warszawa. Profil bez kraju przechodzi — nie wiemy, gdzie osoba
mieszka; domyka go powód odrzucenia „Mieszka poza Polską”, który zapisuje
kraj na profilu (``record_from_rejection``).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Select, Text, any_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import ARRAY

from app.models.candidate import Candidate
from app.services import candidate_audit

POLAND = "PL"


def _country(value: object) -> Optional[str]:
    text = str(value or "").strip().upper()
    return text or None


def city_in_poland(candidate: Candidate) -> bool:
    """Czy miasto z profilu (``city`` albo stare ``location``, pierwszy człon
    przed przecinkiem) jest polską miejscowością ze słownika ``pl_places``.
    Lustro warunku w :func:`abroad_ids`."""
    from app.services import pl_places

    # `getattr`: ścieżki systemu dostają też lekkie obiekty bez pól lokalizacji.
    return any(
        pl_places.resolve(value) is not None
        for value in (
            getattr(candidate, "city", None),
            getattr(candidate, "location", None),
        )
        if value
    )


def lives_outside_poland(candidate: Candidate) -> bool:
    country = _country(getattr(candidate, "country", None))
    if country is None or country == POLAND:
        return False
    return not city_in_poland(candidate)


def abroad_ids() -> Select:
    """``SELECT id`` osób, które według profilu mieszkają poza Polską — ta sama
    reguła co :func:`lives_outside_poland`, do ``NOT IN`` w ścieżkach systemu."""
    from app.services import pl_places

    keys = literal(list(pl_places.all_keys()), type_=ARRAY(Text))
    country = func.upper(func.btrim(Candidate.country))
    return select(Candidate.id).where(
        func.coalesce(country, "") != "",
        country != POLAND,
        ~or_(
            pl_places.place_key_sql(Candidate.city) == any_(keys),
            pl_places.place_key_sql(Candidate.location) == any_(keys),
        ),
    )


def record_from_rejection(
    db,
    candidate: Candidate,
    *,
    country: str,
    user_id: int,
    job_id: int,
    stage_id: int,
) -> bool:
    """Kraj z odrzucenia „Mieszka poza Polską” na profilu — jak ołówek
    „Lokalizacja” (blokada przed nadpisaniem z CV, audyt). Polskie miasto
    w profilu znika razem ze starym krajem, bo inaczej przeważyłoby nad
    nowym krajem i system dalej proponowałby tę osobę."""
    from app.services.candidate_location_writer import project_candidate_location

    country = _country(country)
    if country is None or country == POLAND:
        raise ValueError("Kraj spoza Polski, kod ISO alfa-2.")
    changed = ["country"] if _country(candidate.country) != country else []
    candidate.country = country
    if city_in_poland(candidate):
        candidate.city = None
        changed.append("city")
    if not changed:
        return False
    candidate.location = project_candidate_location(candidate.city, candidate.country)
    extracted = (
        dict(candidate.cv_extracted_data)
        if isinstance(candidate.cv_extracted_data, dict)
        else {}
    )
    for field in changed:
        extracted[f"_manual_override_{field}"] = True
    candidate.cv_extracted_data = extracted
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.LOCATION_CHANGED,
        user_id=user_id,
        entity_id=candidate.id,
        details={
            "changed_fields": sorted(changed),
            "manual_lock": True,
            "source": "rejection",
            "job_id": job_id,
            "stage_id": stage_id,
        },
    )
    return True
