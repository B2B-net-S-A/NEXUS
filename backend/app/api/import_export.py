"""
CSV Import / Export for Candidates.
POST /api/import/candidates  — upload CSV, create candidates (dedup by email)
GET  /api/export/candidates  — download all candidates as CSV (UTF-8 BOM)
"""

import csv
import io
import codecs
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.candidate import Candidate, CandidateStatus
from app.models.activity import Activity

# Re-audyt M2 (PR1b): to jest DRUGA, rownolegla powierzchnia eksportu/importu
# kandydatow obok /api/candidates/export. PR1 zamknal tamta (TAC+ i audyt),
# a ta zostala na golym CurrentUser: GET /api/export/candidates robi
# select(Candidate) BEZ limitu i strumieniuje imie/nazwisko/email/telefon/
# lokalizacje/stawke calej bazy do dowolnej zalogowanej roli (w tym `user`,
# ktora PR1 mial odcieta), bez zdarzenia audytowego. Import pozwalal tej
# samej roli masowo tworzyc kandydatow.
from app.api.candidate_access import CandidateExportAccess, CandidateWriteAccess
from app.services import candidate_audit
from app.services import candidate_profile_facts
from app.services.candidate_language_writer import (
    normalize_language_payload,
    sync_candidate_languages_from_source,
)
from app.services.candidate_profile_rate import canonical_profile_rate_amount
from app.services.candidate_location_writer import normalize_candidate_location

logger = logging.getLogger(__name__)
router = APIRouter()

# Expected CSV columns (case-insensitive, order flexible)
EXPECTED_COLUMNS = {
    "name",
    "lastname",
    "email",
    "phone",
    "city",
    "country",
    "location",
    "source",
    "skills",
    "languages",
    "expected_rate_hourly",
}


def _parse_skills(raw: str) -> list:
    """Convert 'Python, React, AWS' → [{'name': 'Python'}, ...]"""
    if not raw or not raw.strip():
        return []
    return [{"name": s.strip()} for s in raw.split(",") if s.strip()]


def _parse_profile_rate(raw: str) -> Decimal:
    try:
        amount = Decimal(raw.strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid_profile_rate") from exc
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ValueError("invalid_profile_rate")
    if amount >= Decimal("100000000"):
        raise ValueError("invalid_profile_rate")
    return amount


@router.post("/import/candidates")
async def import_candidates(
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    """
    Accept CSV file (UTF-8 or UTF-8-BOM) and create Candidate records.
    Deduplicates by email — rows with existing emails are skipped.
    Returns: {imported, skipped, errors, details}
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Plik musi być w formacie CSV")

    raw_bytes = await file.read()

    # Detect and strip BOM if present
    if raw_bytes.startswith(codecs.BOM_UTF8):
        raw_bytes = raw_bytes[len(codecs.BOM_UTF8) :]

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw_bytes.decode("cp1250")  # Windows Polish fallback
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400,
                detail="Nie można odczytać pliku — użyj kodowania UTF-8",
            )

    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        raise HTTPException(
            status_code=400, detail="Plik CSV jest pusty lub nie ma nagłówków"
        )

    # Normalize header names (strip whitespace, lowercase)
    normalized_fields = {f.strip().lower(): f for f in reader.fieldnames}

    def get_col(row: dict, col: str) -> str:
        original = normalized_fields.get(col)
        if original and original in row:
            value = row[original]
            return "" if value is None else str(value).strip()
        return ""

    imported = 0
    skipped = 0
    errors = 0
    details = []
    imported_ids: list[int] = []
    field_errors = 0

    for row_num, row in enumerate(reader, start=2):  # start=2 (header is row 1)
        try:
            email = get_col(row, "email").lower() or None
            name = get_col(row, "name")
            lastname = get_col(row, "lastname")

            if not name and not lastname:
                errors += 1
                details.append(
                    {
                        "row": row_num,
                        "status": "error",
                        "reason": "Brak imienia i nazwiska",
                    }
                )
                continue

            # Dedup by email
            if email:
                existing = await db.execute(
                    select(Candidate).where(Candidate.email == email)
                )
                if existing.scalar_one_or_none():
                    skipped += 1
                    details.append(
                        {
                            "row": row_num,
                            "status": "skipped",
                            "email": email,
                            "reason": "Email już istnieje w bazie",
                        }
                    )
                    continue

            skills_raw = get_col(row, "skills")
            rate_raw = get_col(row, "expected_rate_hourly")
            rate_currency = get_col(row, "expected_rate_currency").upper()
            source_raw = get_col(row, "source") or "manual"
            raw_country = get_col(row, "country")
            location = normalize_candidate_location(
                city=get_col(row, "city") or None,
                country=raw_country or None,
                raw_location=get_col(row, "location") or None,
            )
            row_field_errors: list[dict[str, str]] = []
            if raw_country and location.country is None:
                row_field_errors.append(
                    {
                        "field": "country",
                        "code": "invalid_candidate_country",
                    }
                )
            languages_raw = get_col(row, "languages")
            if languages_raw:
                _normalized_languages, invalid_languages = normalize_language_payload(
                    languages_raw
                )
                if invalid_languages:
                    row_field_errors.append(
                        {
                            "field": "languages",
                            "code": "invalid_candidate_languages",
                        }
                    )

            # A retired column is an error by schema presence, even when every
            # cell is empty.  This prevents an obsolete template from looking
            # successfully migrated while silently dropping the field.
            for retired_field in ("salary_expectation", "salary_currency"):
                if retired_field in normalized_fields:
                    row_field_errors.append(
                        {
                            "field": retired_field,
                            "code": "candidate_monthly_rate_retired",
                        }
                    )

            parsed_rate: Decimal | None = None
            if rate_raw:
                if rate_currency and rate_currency != "PLN":
                    row_field_errors.append(
                        {
                            "field": "expected_rate_currency",
                            "code": "candidate_profile_rate_requires_pln",
                        }
                    )
                else:
                    try:
                        amount = _parse_profile_rate(rate_raw)
                    except ValueError:
                        row_field_errors.append(
                            {
                                "field": "expected_rate_hourly",
                                "code": "invalid_profile_rate",
                            }
                        )
                    else:
                        parsed_rate = amount
            elif rate_currency:
                row_field_errors.append(
                    {
                        "field": "expected_rate_currency",
                        "code": "candidate_profile_rate_amount_required",
                    }
                )

            # A savepoint protects the outer bulk transaction if any persistence
            # hook fails after validation; no half-created candidate survives.
            async with db.begin_nested():
                candidate = Candidate(
                    name=name or "—",
                    lastname=lastname or "",
                    email=email,
                    phone=get_col(row, "phone") or None,
                    city=location.city,
                    country=location.country,
                    location=location.projection,
                    source=source_raw[:100],
                    skills=_parse_skills(skills_raw),
                    status=CandidateStatus.active,
                )
                db.add(candidate)
                await db.flush()

                if languages_raw:
                    await sync_candidate_languages_from_source(
                        db,
                        candidate_id=candidate.id,
                        raw_languages=languages_raw,
                        provenance="csv",
                        source_ref=f"csv-row:{row_num}",
                    )

                if parsed_rate is not None:
                    await candidate_profile_facts.update_candidate_profile_rate(
                        db,
                        candidate_id=candidate.id,
                        amount=parsed_rate,
                        expected_version=candidate.profile_rate_version,
                        actor_id=current_user.id,
                    )

                activity = Activity(
                    entity_type="candidate",
                    entity_id=candidate.id,
                    action="imported",
                    user_id=current_user.id,
                    details={
                        "name": f"{candidate.name} {candidate.lastname}",
                        "source": "csv_import",
                    },
                )
                db.add(activity)
                await db.flush()

            imported_ids.append(candidate.id)

            imported += 1
            detail = {
                "row": row_num,
                "status": "imported",
                "name": f"{name} {lastname}".strip(),
                "email": email,
            }
            if row_field_errors:
                field_errors += len(row_field_errors)
                detail["status"] = "imported_with_field_errors"
                detail["field_errors"] = row_field_errors
            details.append(detail)

        except Exception as exc:
            errors += 1
            details.append(
                {
                    "row": row_num,
                    "status": "error",
                    "reason": str(exc),
                }
            )

    # Record the reindex intent for everything this import created. Bulk path,
    # so intent only — embedding inline here would be one Voyage call per row
    # inside the import loop, turning a 5 000-row CSV into 5 000 sequential API
    # calls where a single timeout costs a candidate. Cheap INSERTs in the same
    # transaction: if the import rolls back, the intents go with it.
    try:
        from app.services.index_outbox_service import CANDIDATE, record_bulk_reindex

        await record_bulk_reindex(db, CANDIDATE, imported_ids)
    except Exception as exc:  # noqa: BLE001 — never fail an import on the queue
        logger.warning("Recording reindex intent for CSV import failed: %s", exc)

    await db.commit()

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
        "field_errors": field_errors,
        "details": details,
    }


_CANDIDATE_EXPORT_HEADER = (
    "id",
    "name",
    "lastname",
    "email",
    "phone",
    "location",
    "source",
    "status",
    "skills",
    "expected_rate_hourly",
    "created_at",
    "open_to_side_projects",
    "open_to_sales_support",
    "open_to_expert_consult",
)

# Dokladnie te kolumny, ktore `_candidate_export_row` wypisuje (plus waluta,
# ktorej sam CSV nie ma, ale bez ktorej nie da sie zredagowac stawki). Reszta
# modelu — `raw_cv_text`, JSONB-y profilu, embeddingi — nigdy nie trafiala do
# pliku, a mimo to szla przez siec i pamiec procesu przy KAZDYM eksporcie.
_CANDIDATE_EXPORT_ENTITIES = (
    Candidate.id,
    Candidate.name,
    Candidate.lastname,
    Candidate.email,
    Candidate.phone,
    Candidate.location,
    Candidate.source,
    Candidate.status,
    Candidate.skills,
    Candidate.expected_rate_hourly,
    Candidate.expected_rate_currency,
    Candidate.created_at,
    Candidate.open_to_side_projects,
    Candidate.open_to_sales_support,
    Candidate.open_to_expert_consult,
)

# Ile wierszy asyncpg materializuje naraz przy strumieniowaniu. Ta sama
# wartosc co w `POST /api/candidates/export` — jedno miejsce mniej do
# rozjechania sie.
_EXPORT_YIELD_PER = 500
_EXPORT_CHUNK_BYTES = 64 * 1024


def _candidate_export_row(c) -> list:
    """Jeden wiersz CSV. Przyjmuje ORM ``Candidate`` ALBO wiersz projekcji —
    liczy sie tylko dostep po nazwach atrybutow, ktory daja oba."""
    # Flatten skills list → "Python, React, AWS"
    skills_list = c.skills or []
    if isinstance(skills_list, list):
        skills_str = ", ".join(
            s.get("name", s) if isinstance(s, dict) else str(s) for s in skills_list
        )
    else:
        skills_str = ""

    created = c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else ""
    profile_rate = canonical_profile_rate_amount(
        c.expected_rate_hourly,
        c.expected_rate_currency,
    )

    return [
        c.id,
        c.name or "",
        c.lastname or "",
        c.email or "",
        c.phone or "",
        c.location or "",
        c.source or "",
        c.status.value if c.status else "",
        skills_str,
        profile_rate if profile_rate is not None else "",
        created,
        "tak" if c.open_to_side_projects else "",
        "tak" if c.open_to_sales_support else "",
        "tak" if c.open_to_expert_consult else "",
    ]


def _build_candidates_csv(candidates) -> bytes:
    """Serialize candidates to CSV bytes (UTF-8 BOM for Excel/Polish chars).

    Sync/CPU-bound — zostaje dla wolajacych, ktorzy maja juz cala liste w
    pamieci (testy). Endpoint eksportu strumieniuje, wiec calej listy nigdy
    nie tworzy.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_CANDIDATE_EXPORT_HEADER)
    for c in candidates:
        writer.writerow(_candidate_export_row(c))

    # Encode with UTF-8 BOM for Polish characters in Excel
    return codecs.BOM_UTF8 + output.getvalue().encode("utf-8")


async def _stream_candidates_csv(db: AsyncSession, query):
    """Wypuszcza CSV kawalkami, w miare jak Postgres oddaje wiersze."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CANDIDATE_EXPORT_HEADER)
    # BOM tylko raz, przed naglowkiem — Excel czyta go z poczatku pliku.
    yield codecs.BOM_UTF8 + buffer.getvalue().encode("utf-8")
    buffer.seek(0)
    buffer.truncate(0)

    stream = await db.stream(query.execution_options(yield_per=_EXPORT_YIELD_PER))
    async for row in stream:
        writer.writerow(_candidate_export_row(row))
        if buffer.tell() >= _EXPORT_CHUNK_BYTES:
            yield buffer.getvalue().encode("utf-8")
            buffer.seek(0)
            buffer.truncate(0)
    if buffer.tell():
        yield buffer.getvalue().encode("utf-8")


@router.get("/export/candidates")
async def export_candidates(
    current_user: CandidateExportAccess,
    db: AsyncSession = Depends(get_db),
):
    """
    Export all candidates as CSV with UTF-8 BOM (Polish characters support).

    Projekcja + strumien, nie `select(Candidate).scalars().all()`. Tamto
    ladowalo ~49 tys. pelnych wierszy ORM (z `raw_cv_text` i JSONB-ami) do
    pamieci procesu, zeby wypisac z nich 14 kolumn — przy `mem_limit`
    kontenera realne bylo ubicie backendu, a wtedy 502 dostaja WSZYSCY
    zalogowani, nie tylko eksportujacy.

    Ksztalt CSV celowo NIE jest scalany z `POST /api/candidates/export`:
    tamten ma inny zestaw kolumn i wlasny format XLSX, wiec wspolna sciezka
    zmienilaby plik pod istniejacymi odbiorcami tej trasy. Kontrakt, ktorego
    pilnuje `test_parallel_export_surface_matches_export_capability`, dotyczy
    UPRAWNIEN (matryca 403), nie serializacji — i ten zostaje nietkniety.
    """
    query = select(*_CANDIDATE_EXPORT_ENTITIES).order_by(Candidate.created_at.desc())

    # Audyt musi byc utrwalony ZANIM zaczniemy oddawac bajty: po starcie
    # StreamingResponse nie ma juz gdzie zapisac wiersza, a slad ma powstac
    # nawet gdy pobieranie urwie sie w polowie. Stad osobny `count()` —
    # `row_count` to liczba kandydatow w chwili zadania, tak jak dotad.
    row_count = int(await db.scalar(select(func.count()).select_from(Candidate)) or 0)

    # Ten sam nieusuwalny slad audytowy co /api/candidates/export (PR1) —
    # bez PII, same liczniki.
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.EXPORT_REQUESTED,
        user_id=current_user.id,
        details={
            "endpoint": "GET /api/export/candidates",
            "format": "csv",
            "row_count": row_count,
        },
    )
    await db.commit()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    filename = f"kandydaci_{timestamp}.csv"

    return StreamingResponse(
        _stream_candidates_csv(db, query),
        media_type="text/csv; charset=utf-8-sig",
        # Bez `Content-Length` — rozmiaru nie znamy przed wyslaniem, a
        # zgadniety naglowek jest gorszy niz jego brak (przegladarka ucina
        # plik do zadeklarowanej dlugosci). Transfer leci chunked, tak jak w
        # `POST /api/candidates/export`.
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
