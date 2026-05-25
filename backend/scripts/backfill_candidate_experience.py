"""Backfill `candidates.experience` JSONB z `candidates.cv_extracted_data`.

Po co? Z 48k kandydatów tylko 30 ma wypełnione `experience` JSONB, ale 44k
ma jakieś dane w `cv_extracted_data` (importy z Traffit + TalentRadar).
Filtry "obecna firma" / "obecne stanowisko" są technicznie poprawne, ale
praktycznie nic nie znajdują bo brak danych do filtrowania.

Trzy warianty `cv_extracted_data`:

* **TalentRadar string** (~38 rzędów) — JSONB string z osadzonym
  escaped JSON object zawierającym `work_history` + `current_role`.
* **Traffit array** (~267 rzędów) — JSONB array (39-43 itemów) gdzie
  ~4 są unikalne, jeden z nich to ten sam string-with-work_history co
  TalentRadar (efekt UPSERT `||` z migracji historycznych).
* **Traffit object** (~44k rzędów) — flat dict z `traffit_*` kluczami;
  bez `work_history`. Można odczytać tylko `traffit_Position` (rola/role)
  i `traffit_previous_employers` (CSV firm, bez dat).

Schemat output (matches `app/models/candidate.py` docstring):
  experience: list[dict] = [{company, role, start, end, desc}]
  experience[0] = najnowsza / obecna (end IS NULL gdy aktualnie pracuje)

Idempotency: pomija kandydatów którzy już mają `experience`
(jsonb_array_length > 0) — bezpieczne re-run.

Użycie:
  python scripts/backfill_candidate_experience.py --dry-run
  python scripts/backfill_candidate_experience.py --batch-size=2000 --sleep-ms=200
  python scripts/backfill_candidate_experience.py --variants tr_string,tr_array
  python scripts/backfill_candidate_experience.py --skip-lcc   # nie ruszaj linkedin_current_company

Każdy commit transakcji = jeden batch. Crash w środku = bezpieczny resume.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import asyncpg

logger = logging.getLogger("backfill_experience")


# ── parsing ────────────────────────────────────────────────────────────────


def _norm_str(value: Any) -> str | None:
    """Trim whitespace; return None for empty/None."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    stripped = value.strip()
    return stripped or None


def _build_experience_from_work_history(wh: Iterable[Any]) -> list[dict]:
    """Map talent_radar work_history items → our schema.

    Input item shape (talent_radar / traffit-array):
      {role, company, start_date, end_date, description, technologies}

    Output shape (our experience JSONB):
      [{company, role, start, end, desc}]

    Dedupe by (company.lower(), role.lower(), start). Sort: end IS NULL
    first (current), then by end DESC.
    """
    items: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for raw in wh or []:
        if not isinstance(raw, dict):
            continue
        company = _norm_str(raw.get("company"))
        role = _norm_str(raw.get("role"))
        start = _norm_str(raw.get("start_date") or raw.get("start"))
        end = _norm_str(raw.get("end_date") or raw.get("end"))
        desc = _norm_str(raw.get("description") or raw.get("desc"))

        # Skip totally empty rows
        if not company and not role:
            continue

        key = ((company or "").lower(), (role or "").lower(), start or "")
        if key in seen:
            continue
        seen.add(key)

        items.append(
            {
                "company": company,
                "role": role,
                "start": start,
                "end": end,
                "desc": desc,
            }
        )

    # Sort: current (end IS NULL) first, then end DESC.
    # Use empty string as sort key for None end → with reverse=True they go last;
    # we want them FIRST so use (has_end, end_or_empty) ascending then desc on end.
    def _sort_key(it: dict) -> tuple[int, str]:
        has_end = 0 if not it.get("end") else 1
        return (has_end, "" if not it.get("end") else it["end"])

    items.sort(key=_sort_key, reverse=False)
    # has_end=0 (current) first; among finished, we want most recent end first → reverse just the tail.
    current = [i for i in items if not i.get("end")]
    finished = [i for i in items if i.get("end")]
    finished.sort(key=lambda i: i["end"], reverse=True)
    return current + finished


def _parse_payload_dict(payload: dict) -> tuple[list[dict], str | None]:
    """Parse a TalentRadar-style payload dict → (experience, current_company).

    `current_company` = experience[0].company gdy experience[0].end IS NULL.
    """
    wh = payload.get("work_history")
    if not isinstance(wh, list):
        return [], None
    experience = _build_experience_from_work_history(wh)
    current_company = None
    if experience and not experience[0].get("end") and experience[0].get("company"):
        current_company = experience[0]["company"]
    return experience, current_company


def parse_tr_string(raw: Any) -> tuple[list[dict], str | None]:
    """Parse TalentRadar string variant.

    `cv_extracted_data` jest JSON-stringiem osadzonym jako JSONB string.
    asyncpg deserializuje go do Pythona jako `str` (zawiera JSON inside).
    """
    if not isinstance(raw, str):
        return [], None
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return [], None
    if not isinstance(payload, dict):
        return [], None
    return _parse_payload_dict(payload)


def parse_tr_array(arr: Any) -> tuple[list[dict], str | None]:
    """Parse Traffit-array variant.

    Array zawiera 39+ itemów (najczęściej duplikatów). Każdy item to:
    - dict (np. {"legacy_source": "traffit"}, {})
    - lub JSON-string (zawierający work_history, jak TalentRadar)

    Iterujemy aż znajdziemy item z `work_history`.
    """
    if not isinstance(arr, list):
        return [], None

    for item in arr:
        payload: dict | None = None
        if isinstance(item, str):
            try:
                parsed = json.loads(item)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(parsed, dict):
                payload = parsed
        elif isinstance(item, dict):
            payload = item

        if not payload:
            continue
        wh = payload.get("work_history")
        if isinstance(wh, list) and wh:
            return _parse_payload_dict(payload)

    return [], None


def _empty_slot() -> dict:
    """Placeholder row z wszystkimi polami None.

    Używane jako `experience[0]` gdy nie znamy obecnej roli/firmy — żeby
    past employers wypełniające `experience[1..]` nie pollutowały filtra
    "obecna firma" (który czyta `experience[0].company`).
    """
    return {"company": None, "role": None, "start": None, "end": None, "desc": None}


def parse_traffit_object(obj: Any) -> tuple[list[dict], str | None]:
    """Parse Traffit-object variant — partial (no current company known).

    Daje:
    - experience[0..N-1] = role(s) split z `traffit_Position` (current first)
    - experience[N..] = past employers split z `traffit_previous_employers`

    Gdy `traffit_Position` jest puste a `traffit_previous_employers` ma dane,
    dodajemy NULL placeholder jako `experience[0]` żeby past employer nie
    wyglądał na obecną firmę. To preserve'uje "previous company" filter
    (ordinality > 1) ale nie psuje "obecna firma" filter (NULL company nie matchuje).
    """
    if not isinstance(obj, dict):
        return [], None

    experience: list[dict] = []

    # Rola(e) — pierwsza = current
    position_raw = obj.get("traffit_Position")
    has_position = False
    if isinstance(position_raw, str):
        roles = [r.strip() for r in position_raw.split(",") if r.strip()]
        for role in roles:
            has_position = True
            experience.append(
                {"company": None, "role": role, "start": None, "end": None, "desc": None}
            )

    # Past employers — bez ról
    employers_raw = obj.get("traffit_previous_employers")
    if isinstance(employers_raw, str):
        emp_list = [e.strip() for e in employers_raw.split(",") if e.strip()]
        if emp_list:
            # Bez pozycji → placeholder, żeby past employer nie pollutował exp[0]
            if not has_position:
                experience.append(_empty_slot())
            seen_companies = {
                (e["company"] or "").lower() for e in experience if e.get("company")
            }
            for emp in emp_list:
                if emp.lower() in seen_companies:
                    continue
                experience.append(
                    {
                        "company": emp,
                        "role": None,
                        "start": None,
                        "end": None,
                        "desc": None,
                    }
                )
                seen_companies.add(emp.lower())

    # No current_company derivable (we don't know which past employer is now)
    return experience, None


# ── stats + dispatch ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Variant:
    name: str
    description: str


VARIANTS = {
    "tr_string": Variant(
        "tr_string", "TalentRadar JSON-string z work_history (~38 rzędów)"
    ),
    "tr_array": Variant(
        "tr_array", "Traffit array z osadzonym TalentRadar payload (~267 rzędów)"
    ),
    "traffit_obj": Variant(
        "traffit_obj",
        "Traffit flat object: traffit_Position + traffit_previous_employers (~29k z czegoś użytecznego, ~44k total)",
    ),
}


@dataclass
class Stats:
    processed: int = 0
    parsed_ok: int = 0
    parsed_empty: int = 0  # data present but no useful fields
    parse_error: int = 0
    skipped_already: int = 0  # experience already set
    updated_lcc: int = 0  # linkedin_current_company set
    per_variant: dict[str, int] = field(default_factory=dict)

    def bump(self, key: str, n: int = 1) -> None:
        setattr(self, key, getattr(self, key) + n)

    def bump_variant(self, variant: str) -> None:
        self.per_variant[variant] = self.per_variant.get(variant, 0) + 1


def detect_variant(jtype: str, source: str | None) -> str | None:
    """Map (jsonb_typeof, external_source) → variant name."""
    if jtype == "string":
        return "tr_string"
    if jtype == "array":
        return "tr_array"
    if jtype == "object":
        return "traffit_obj"
    return None


def parse_row(
    cv_extracted_data: Any, jtype: str, source: str | None
) -> tuple[list[dict], str | None, str | None]:
    """Dispatch parser by variant. Returns (experience, lcc, variant_name)."""
    variant = detect_variant(jtype, source)
    if variant is None:
        return [], None, None

    try:
        if variant == "tr_string":
            exp, lcc = parse_tr_string(cv_extracted_data)
        elif variant == "tr_array":
            exp, lcc = parse_tr_array(cv_extracted_data)
        elif variant == "traffit_obj":
            exp, lcc = parse_traffit_object(cv_extracted_data)
        else:
            return [], None, variant
        return exp, lcc, variant
    except Exception as e:  # defensive — per-row error shouldn't kill the run
        logger.warning("parse error for variant=%s: %s", variant, e)
        return [], None, variant


# ── DB loop ────────────────────────────────────────────────────────────────


SELECT_BATCH_SQL = """
SELECT
    id,
    external_source,
    linkedin_current_company,
    jsonb_typeof(cv_extracted_data) AS jtype,
    cv_extracted_data
FROM candidates
WHERE
    (experience IS NULL OR jsonb_typeof(experience) <> 'array' OR jsonb_array_length(experience) = 0)
    AND cv_extracted_data IS NOT NULL
    AND cv_extracted_data <> '{}'::jsonb
    AND cv_extracted_data <> '[]'::jsonb
    AND jsonb_typeof(cv_extracted_data) = ANY($1)
    AND id > $2
ORDER BY id
LIMIT $3
"""


UPDATE_EXPERIENCE_SQL = """
UPDATE candidates
SET experience = $2::jsonb, updated_at = NOW()
WHERE id = $1
"""

UPDATE_EXPERIENCE_AND_LCC_SQL = """
UPDATE candidates
SET experience = $2::jsonb,
    linkedin_current_company = $3,
    updated_at = NOW()
WHERE id = $1 AND linkedin_current_company IS NULL
"""


async def _reconnect(dsn: str, max_retries: int = 5) -> asyncpg.Connection:
    """Open asyncpg connection with exponential-backoff retry.

    Cycling Coolify deploys may bounce Postgres briefly. Each retry pauses
    progressively longer (1s, 2s, 4s, 8s, 16s) before giving up.
    """
    delay = 1.0
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return await asyncpg.connect(dsn)
        except (OSError, asyncpg.PostgresError) as e:
            last_err = e
            logger.warning(
                "connect attempt %d/%d failed: %s; retry in %.0fs",
                attempt,
                max_retries,
                e,
                delay,
            )
            await asyncio.sleep(delay)
            delay *= 2
    raise RuntimeError(f"could not reconnect to DB after {max_retries} tries: {last_err}")


async def _run(
    dsn: str,
    batch_size: int,
    sleep_ms: int,
    dry_run: bool,
    variants: list[str],
    set_lcc: bool,
    sample_log_path: Path | None,
) -> Stats:
    stats = Stats()
    conn = await _reconnect(dsn)
    sample_fh = None
    if sample_log_path:
        sample_fh = sample_log_path.open("w", encoding="utf-8")

    variant_to_jtype = {
        "tr_string": "string",
        "tr_array": "array",
        "traffit_obj": "object",
    }
    jtypes = sorted({variant_to_jtype[v] for v in variants if v in variant_to_jtype})
    logger.info("scanning variants=%s (jtypes=%s)", variants, jtypes)

    try:
        last_id = 0
        batch_no = 0
        while True:
            batch_no += 1
            try:
                rows = await conn.fetch(SELECT_BATCH_SQL, jtypes, last_id, batch_size)
            except (asyncpg.exceptions.ConnectionDoesNotExistError,
                    asyncpg.exceptions.InterfaceError,
                    asyncpg.exceptions.PostgresConnectionError,
                    OSError) as e:
                logger.warning("fetch failed (%s); reconnecting", e)
                await conn.close()
                conn = await _reconnect(dsn)
                continue
            if not rows:
                logger.info("[batch %d] no more rows", batch_no)
                break

            # Parse phase (in-memory, no DB)
            updates: list[tuple[int, str, str | None]] = []
            for row in rows:
                stats.bump("processed")
                last_id = row["id"]

                cv_data = row["cv_extracted_data"]
                # asyncpg returns JSONB as raw JSON text (str). First decode
                # unwraps to Python type: array→list, object→dict, string→str
                # (still inner JSON-encoded — `parse_tr_string` decodes once more).
                if isinstance(cv_data, str):
                    try:
                        cv_data = json.loads(cv_data)
                    except (json.JSONDecodeError, ValueError):
                        stats.bump("parse_error")
                        continue

                experience, lcc, variant = parse_row(
                    cv_data, row["jtype"], row["external_source"]
                )

                if variant is None:
                    continue

                if not experience:
                    stats.bump("parsed_empty")
                    if sample_fh and stats.parsed_empty <= 20:
                        sample_fh.write(
                            f"[empty {variant}] id={row['id']}: "
                            f"{json.dumps(cv_data, default=str)[:300]}\n"
                        )
                    continue

                stats.bump("parsed_ok")
                stats.bump_variant(variant)

                lcc_to_set = lcc if set_lcc and lcc and not row["linkedin_current_company"] else None

                updates.append((row["id"], json.dumps(experience, ensure_ascii=False), lcc_to_set))

            if not updates:
                logger.info("[batch %d] no updates from %d rows", batch_no, len(rows))
                continue

            # Apply phase
            if dry_run:
                logger.info(
                    "[batch %d] dry-run: would UPDATE %d candidates", batch_no, len(updates)
                )
            else:
                try:
                    async with conn.transaction():
                        for cand_id, exp_json, lcc_val in updates:
                            if lcc_val:
                                res = await conn.execute(
                                    UPDATE_EXPERIENCE_AND_LCC_SQL, cand_id, exp_json, lcc_val
                                )
                                if res.endswith(" 1"):
                                    stats.bump("updated_lcc")
                                else:
                                    await conn.execute(
                                        UPDATE_EXPERIENCE_SQL, cand_id, exp_json
                                    )
                            else:
                                await conn.execute(UPDATE_EXPERIENCE_SQL, cand_id, exp_json)
                except (asyncpg.exceptions.ConnectionDoesNotExistError,
                        asyncpg.exceptions.InterfaceError,
                        asyncpg.exceptions.PostgresConnectionError,
                        OSError) as e:
                    logger.warning(
                        "[batch %d] commit interrupted (%s); reconnecting + retrying same batch",
                        batch_no,
                        e,
                    )
                    try:
                        await conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                    conn = await _reconnect(dsn)
                    # Reset last_id so the same batch is re-fetched; subtract the
                    # batch we just attempted from counters to keep stats honest.
                    last_id = rows[0]["id"] - 1 if rows else last_id
                    stats.processed -= len(rows)
                    # parsed_ok/empty already incremented — keep them (idempotent retry won't double-count
                    # because the WHERE clause skips already-updated rows on re-fetch).
                    batch_no -= 1
                    continue
                logger.info(
                    "[batch %d] updated=%d (parsed_ok cumulative=%d / processed=%d)",
                    batch_no,
                    len(updates),
                    stats.parsed_ok,
                    stats.processed,
                )

            if len(rows) < batch_size:
                logger.info("[batch %d] last partial batch", batch_no)
                break

            if sleep_ms > 0:
                await asyncio.sleep(sleep_ms / 1000.0)

    finally:
        if sample_fh:
            sample_fh.close()
        await conn.close()

    return stats


# ── CLI ────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument(
        "--sleep-ms",
        type=int,
        default=100,
        help="Delay between batches (production safety; 0 = no sleep).",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--variants",
        default=",".join(VARIANTS.keys()),
        help="Comma-separated variant filter (tr_string,tr_array,traffit_obj).",
    )
    parser.add_argument(
        "--skip-lcc",
        action="store_true",
        help="Nie ustawiaj linkedin_current_company (zostaw dla LinkedIn sync).",
    )
    parser.add_argument(
        "--sample-log",
        type=str,
        default=None,
        help="Path do logu sample failures (do 20 wpisów per parsed_empty bucket).",
    )
    return parser.parse_args()


def _resolve_dsn() -> str:
    raw = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://nexus:nexus@postgres:5432/nexus"
    )
    return raw.replace("postgresql+asyncpg://", "postgresql://")


def _format_stats(stats: Stats) -> str:
    lines = [
        f"processed: {stats.processed}",
        f"parsed_ok: {stats.parsed_ok}",
        f"parsed_empty: {stats.parsed_empty}",
        f"parse_error: {stats.parse_error}",
        f"updated_lcc: {stats.updated_lcc}",
        "per_variant:",
    ]
    for k, v in sorted(stats.per_variant.items()):
        lines.append(f"  {k}: {v}")
    return "\n  ".join(lines)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = _parse_args()

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown:
        logger.error("Unknown variants: %s. Valid: %s", unknown, list(VARIANTS.keys()))
        return 2

    dsn = _resolve_dsn()
    sample_log_path = Path(args.sample_log) if args.sample_log else None

    logger.info(
        "starting backfill: dry_run=%s batch_size=%d sleep_ms=%d variants=%s set_lcc=%s",
        args.dry_run,
        args.batch_size,
        args.sleep_ms,
        variants,
        not args.skip_lcc,
    )
    stats = asyncio.run(
        _run(
            dsn=dsn,
            batch_size=args.batch_size,
            sleep_ms=args.sleep_ms,
            dry_run=args.dry_run,
            variants=variants,
            set_lcc=not args.skip_lcc,
            sample_log_path=sample_log_path,
        )
    )
    logger.info("DONE.\n  %s", _format_stats(stats))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
