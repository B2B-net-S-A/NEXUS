"""Lista rekrutacji do wyboru w filtrze kandydatów (blok „Rekrutacje”).

Zasila `GET /api/jobs-lookup/search`. Dwa tryby:

* **szukanie** — to, co pokazuje rejestr `/jobs` (bez rekrutacji klientów
  ukrytych i usuniętych), zawężone tekstem i statusem; tekst pasuje do nazwy
  rekrutacji (roboczej i od klienta), numeru referencyjnego, nazwy klienta albo
  numeru rekrutacji. Technologii z wymagań świadomie tu NIE czytamy: lista
  pokazuje tytuł i klienta, więc trafienie „po Javie” byłoby wierszem bez
  wyjaśnienia i wypychało trafienia po nazwie poza limit;
* **etykiety** — rekrutacje i klienci po identyfikatorach, bez filtra
  widoczności i statusu. Zapisany wcześniej identyfikator dalej filtruje listę
  kandydatów, więc jego nazwa nie może zniknąć z ekranu.
"""

from typing import Any, Optional, Sequence

from sqlalchemy import and_, func, or_, select, true

from app.models.client import Client
from app.models.job import Job, JobStatus
from app.services.client_identity import (
    client_display_name_expression,
    job_client_listed_clause,
)
from app.services.job_working_title import job_display_title_expr
from app.services.polish_ilike import polish_folded_ilike

# Najdłuższy numer, który na pewno mieści się w identyfikatorze (int4).
_MAX_ID_DIGITS = 9
MAX_LABEL_IDS = 200
CLIENT_SUGGESTIONS = 5
MIN_CLIENT_QUERY = 2


def job_id_from_text(text: str) -> Optional[int]:
    """Numer rekrutacji wpisany w pole szukania („2143”, „#2143”) albo ``None``."""
    digits = text.strip().removeprefix("#").strip()
    if digits.isascii() and digits.isdigit() and len(digits) <= _MAX_ID_DIGITS:
        return int(digits)
    return None


def _client_name_matches(needle: str) -> Any:
    return or_(
        polish_folded_ilike(Client.name, needle),
        polish_folded_ilike(Client.display_name, needle),
    )


def search_clause(q: str) -> Any:
    needle = q.strip()
    if not needle:
        return true()
    client_match = (
        select(Client.id)
        .where(Client.id == Job.client_id, _client_name_matches(needle))
        .correlate_except(Client)
        .exists()
    )
    parts = [
        polish_folded_ilike(Job.title, needle),
        polish_folded_ilike(Job.working_title, needle),
        polish_folded_ilike(Job.reference_number, needle),
        polish_folded_ilike(Job.client_reference, needle),
        client_match,
    ]
    job_id = job_id_from_text(needle)
    if job_id is not None:
        parts.append(Job.id == job_id)
    return or_(*parts)


def _status_clause(status: str) -> Any:
    if status == "open":
        return Job.status != JobStatus.closed
    if status == "closed":
        return Job.status == JobStatus.closed
    return true()


def _search_filter(q: str, status: str) -> Any:
    return and_(
        job_client_listed_clause(Job.client_id),
        _status_clause(status),
        search_clause(q),
    )


def _item_statement() -> Any:
    return select(
        Job.id,
        job_display_title_expr().label("title"),
        Job.client_id,
        client_display_name_expression().label("client_name"),
        Job.status,
    ).outerjoin(Client, Client.id == Job.client_id)


def search_statement(q: str, status: str, limit: int) -> Any:
    order = [Job.id.desc()]
    job_id = job_id_from_text(q)
    if job_id is not None:
        order.insert(0, (Job.id == job_id).desc())
    return (
        _item_statement().where(_search_filter(q, status)).order_by(*order).limit(limit)
    )


def search_total_statement(q: str, status: str) -> Any:
    return select(func.count()).select_from(Job).where(_search_filter(q, status))


def _clients_statement() -> Any:
    jobs_count = func.count(Job.id)
    name = client_display_name_expression()
    return (
        select(Client.id, name.label("name"), jobs_count.label("jobs_count"))
        .join(Job, Job.client_id == Client.id)
        .group_by(Client.id)
        .order_by(jobs_count.desc(), Client.id)
    )


def clients_matching_statement(q: str) -> Any:
    """Klienci pasujący nazwą — pozycje „Wszystkie rekrutacje klienta …”."""
    return (
        _clients_statement()
        .where(
            _client_name_matches(q.strip()),
            Client.hidden.is_(False),
            Client.deleted_at.is_(None),
        )
        .limit(CLIENT_SUGGESTIONS)
    )


def jobs_by_id_statement(ids: Sequence[int]) -> Any:
    return _item_statement().where(Job.id.in_(list(ids))).order_by(Job.id.desc())


def clients_by_id_statement(ids: Sequence[int]) -> Any:
    return _clients_statement().where(Client.id.in_(list(ids)))


def item_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "client_id": row.client_id,
        "client_name": row.client_name,
        "status": "closed" if row.status == JobStatus.closed else "open",
    }


def client_from_row(row: Any) -> dict[str, Any]:
    return {"id": row.id, "name": row.name, "jobs_count": int(row.jobs_count)}
