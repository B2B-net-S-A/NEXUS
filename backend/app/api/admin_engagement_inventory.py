"""GET /api/admin/engagement-inventory — read-only raport anomalii lifecycle
współpracy (kontrakt / dokument / podpis / zamówienie / stawki / zakończenie /
sprzęt / faktury).

Moduł 5 (kontrakty/engagement/onboarding/billing/offboarding), plan PR-00:
zmierzyć produkcyjny stan lifecycle ZANIM wprowadzimy kanoniczny Engagement
i przebudujemy authority (fale B+). Klasy anomalii pochodzą z sekcji 14.2
dokumentu audytu `docs/contracts-engagement-onboarding-billing-offboarding-
module-audit-and-claude-implementation-plan-2026-07-16.md`.

Rozłączność z Modułem 4: `/api/admin/pipeline-inventory` (PR-00 M4) pokrywa już
relację stage↔contract (`hired_no_contract`, `multiple_live_contracts`,
`contract_no_hired`). Ten raport ich NIE dubluje — patrzy wyłącznie na
WEWNĘTRZNY stan współpracy po stronie kontraktu (dokument, podpis, zamówienie,
harmonogram stawek, zakończenie, sprzęt, faktura). Operator zestawia oba raporty
po `query_version`/`generated_at`.

Kontrakt (identyczny jak pipeline-inventory, świadomie reużyty):
- WYŁĄCZNIE odczyt (SELECT) — endpoint niczego nie naprawia i nie mutuje.
- Zero PII i zero sekretów w output: sample zawiera tylko numeryczne ID
  (contract/candidate/client/job/order/equipment/signature/invoice) oraz
  identyfikatory dokumentów (numer umowy/faktury) i daty progu (effective_from).
  Nigdy nazwisk, e-maili, telefonów, treści ani surowego tokenu linku podpisu.
- Sample ograniczone do SAMPLE_LIMIT pozycji per check.
- Każdy check ma własny timeout; błąd jednego checku nie wywala raportu
  (pole `error` zamiast liczby).
- `query_version` + `generated_at` pozwalają porównywać kolejne przebiegi.

Auth: jak /api/admin/snapshot — X-Snapshot-Token (machine) albo JWT admina.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_snapshot import _snapshot_auth
from app.core.database import get_db
from app.core.scheduling import business_today

router = APIRouter()

# Bump przy każdej zmianie definicji zapytań — raporty porównujemy tylko
# w obrębie tej samej wersji.
QUERY_VERSION = "m5-pr00-v4"

SAMPLE_LIMIT = 20
CHECK_TIMEOUT_SECONDS = 20.0

# „Dziś" w checkach dat to dzień w kalendarzu firmy, podawany z Pythona jako
# `:today`. `CURRENT_DATE` bazy liczy się w strefie sesji (UTC), więc między
# północą warszawską a UTC kontrakt startujący „dziś" wychodził jako przyszły.
# Kontrakt „żywy" = trwająca współpraca w oczach reszty systemu (raporty, marża,
# alerty, profil klienta). Uwaga: `active` NIE dowodzi startu ani podpisu — to
# właśnie mierzymy niżej.
_LIVE = "('active', 'ending')"


# ── Definicje checków ────────────────────────────────────────────────────────
# key -> (severity, description, SQL). Konwencja identyczna z pipeline-inventory:
# ostatnia kolumna to `total_count` z COUNT(*) OVER () (pełny licznik mimo LIMIT),
# reszta kolumn trafia do sample. Sample MUSI zawierać wyłącznie pola z allowlisty
# w teście (identyfikatory numeryczne + numer dokumentu + data progu).

_CHECKS: list[tuple[str, str, str, str]] = [
    (
        "active_without_document",
        "P0",
        "Kontrakt active/ending bez żadnego wiersza contract_documents — "
        "„aktywna” współpraca bez dołączonego dokumentu (P0.1, prod #15).",
        f"""
        SELECT c.id AS contract_id, c.candidate_id, c.client_id,
               COUNT(*) OVER () AS total_count
        FROM contracts c
        WHERE c.status IN {_LIVE}
          AND NOT EXISTS (
            SELECT 1 FROM contract_documents d WHERE d.contract_id = c.id
          )
        ORDER BY c.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "active_before_start_date",
        "P0",
        "Kontrakt active/ending, którego start_date jest w przyszłości — "
        "future-start oznaczony jako rozpoczęty (P1.6, prod).",
        f"""
        SELECT c.id AS contract_id, c.candidate_id, c.client_id,
               COUNT(*) OVER () AS total_count
        FROM contracts c
        WHERE c.status IN {_LIVE}
          AND c.start_date IS NOT NULL
          AND c.start_date > :today
        ORDER BY c.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "future_termination_marked_ended",
        "P0",
        "Kontrakt ended, którego terminated_at jest w przyszłości — "
        "przedwczesne zakończenie future-dated (P0.7).",
        """
        SELECT c.id AS contract_id, c.candidate_id, c.client_id,
               COUNT(*) OVER () AS total_count
        FROM contracts c
        WHERE c.status = 'ended'
          AND c.terminated_at IS NOT NULL
          AND c.terminated_at > :today
        ORDER BY c.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "active_without_job",
        "P0",
        "Kontrakt active/ending bez powiązanego job_id — brak spójnego "
        "handoff oferta→współpraca (prod: aktywny bez oferty).",
        f"""
        SELECT c.id AS contract_id, c.candidate_id, c.client_id,
               COUNT(*) OVER () AS total_count
        FROM contracts c
        WHERE c.status IN {_LIVE} AND c.job_id IS NULL
        ORDER BY c.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "active_without_rates",
        "P1",
        "Kontrakt active/ending bez rate_candidate lub rate_client — "
        "aktywacja obeszła gate stawek (generic PATCH, prod: active bez stawek).",
        f"""
        SELECT c.id AS contract_id, c.candidate_id, c.client_id,
               COUNT(*) OVER () AS total_count
        FROM contracts c
        WHERE c.status IN {_LIVE}
          AND (c.rate_candidate IS NULL OR c.rate_client IS NULL)
        ORDER BY c.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "active_without_order_coverage",
        "P1",
        "Kontrakt active/ending bez ważnego ClientOrder pokrywającego dziś i "
        "bez legacy client_order_end_date >= dziś (P1.4).",
        f"""
        SELECT c.id AS contract_id, c.candidate_id, c.client_id,
               COUNT(*) OVER () AS total_count
        FROM contracts c
        WHERE c.status IN {_LIVE}
          AND NOT EXISTS (
            SELECT 1 FROM client_orders o
            WHERE o.contract_id = c.id
              AND o.status = 'active'
              AND (o.end_date IS NULL OR o.end_date >= :today)
          )
          AND (
            c.client_order_end_date IS NULL
            OR c.client_order_end_date < :today
          )
        ORDER BY c.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "legacy_order_date_drift",
        "P1",
        "Contract.client_order_end_date różni się od MAX(client_orders.end_date) "
        "tego kontraktu — dwa źródła prawdy o dacie zamówienia (P1.3).",
        """
        SELECT c.id AS contract_id, c.candidate_id, c.client_id,
               COUNT(*) OVER () AS total_count
        FROM contracts c
        JOIN (
            SELECT contract_id, MAX(end_date) AS max_end
            FROM client_orders
            WHERE end_date IS NOT NULL
            GROUP BY contract_id
        ) o ON o.contract_id = c.id
        WHERE c.client_order_end_date IS NOT NULL
          AND c.client_order_end_date <> o.max_end
        ORDER BY c.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "order_client_mismatch",
        "P0",
        "client_orders.client_id różni się od client_id kontraktu, na którym "
        "zamówienie wisi — jeden wiersz spina DWÓCH klientów, więc zakończenie "
        "współpracy u jednego dotykało zamówienia u drugiego.",
        """
        SELECT o.id AS order_id, o.contract_id, o.client_id,
               COUNT(*) OVER () AS total_count
        FROM client_orders o
        JOIN contracts c ON c.id = o.contract_id
        WHERE o.client_id <> c.client_id
        ORDER BY o.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "periodic_duplicates_group_line",
        "P0",
        "Kontrakt ma jednocześnie OTWARTE zamówienie okresowe (samodzielne) "
        "i OTWARTĄ linię zamówienia grupowego (MD/kosztowego) — dwa równoległe "
        "zapisy tej samej współpracy; zakończenie jednego domykało drugie.",
        """
        SELECT c.id AS contract_id, c.candidate_id, c.client_id,
               standalone.id AS order_id,
               COUNT(*) OVER () AS total_count
        FROM contracts c
        JOIN LATERAL (
            SELECT o.id
            FROM client_orders o
            WHERE o.contract_id = c.id
              AND o.order_group_id IS NULL
              AND o.status IN ('draft', 'active', 'paused')
            ORDER BY o.id
            LIMIT 1
        ) standalone ON TRUE
        WHERE EXISTS (
            SELECT 1 FROM client_orders g
            WHERE g.contract_id = c.id
              AND g.order_group_id IS NOT NULL
              AND g.status IN ('draft', 'active', 'paused')
        )
        ORDER BY c.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "rate_schedule_same_date_dup",
        "P1",
        "Wiele wierszy harmonogramu stawek dzieli (contract_id, effective_from) "
        "w którejkolwiek z 3 tabel — brak DB unique, resolver ma tie-break (P1.5).",
        """
        SELECT contract_id, effective_from, occurrences,
               COUNT(*) OVER () AS total_count
        FROM (
            SELECT contract_id, effective_from, COUNT(*) AS occurrences
            FROM contract_candidate_rates
            GROUP BY contract_id, effective_from HAVING COUNT(*) > 1
            UNION ALL
            SELECT contract_id, effective_from, COUNT(*) AS occurrences
            FROM contract_client_rates
            GROUP BY contract_id, effective_from HAVING COUNT(*) > 1
            UNION ALL
            SELECT contract_id, effective_from, COUNT(*) AS occurrences
            FROM contract_framework_rates
            GROUP BY contract_id, effective_from HAVING COUNT(*) > 1
        ) dups
        ORDER BY contract_id DESC, effective_from DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "ended_without_reason",
        "P1",
        "Kontrakt ended bez termination_reason — raport retencji nie odróżni "
        "planowanego od przedwczesnego (P1.7, prod: 29/29 unspecified).",
        """
        SELECT c.id AS contract_id, c.candidate_id, c.client_id,
               COUNT(*) OVER () AS total_count
        FROM contracts c
        WHERE c.status = 'ended' AND c.termination_reason IS NULL
        ORDER BY c.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "signed_without_activation",
        "P2",
        "DocumentSignature completed, a kontrakt nadal draft — podpis nie "
        "uruchomił spójnej aktywacji (P0.4).",
        """
        SELECT s.id AS signature_id, s.contract_id,
               COUNT(*) OVER () AS total_count
        FROM document_signatures s
        JOIN contracts c ON c.id = s.contract_id
        WHERE s.status = 'completed' AND c.status = 'draft'
        ORDER BY s.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "completed_signature_without_artifact",
        "P2",
        "DocumentSignature completed bez zapisanego signed_document_id/url — "
        "brak dowodowego artefaktu (P0.8).",
        """
        SELECT s.id AS signature_id, s.contract_id,
               COUNT(*) OVER () AS total_count
        FROM document_signatures s
        WHERE s.status = 'completed'
          AND s.signed_document_id IS NULL
          AND s.signed_document_url IS NULL
        ORDER BY s.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "stuck_signature",
        "P2",
        "DocumentSignature w sending/sent/in_progress starszy niż 24h — "
        "backlog wysyłki bez restart-safe recovery (P0.9).",
        """
        SELECT s.id AS signature_id, s.contract_id,
               COUNT(*) OVER () AS total_count
        FROM document_signatures s
        WHERE s.status IN ('sending', 'sent', 'in_progress')
          AND s.created_at < NOW() - INTERVAL '24 hours'
        ORDER BY s.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "orphan_active_signature_link",
        "P2",
        "Aktywny (nieużyty, nieodwołany, nieprzeterminowany) link podpisu, "
        "którego DocumentSignature jest już terminalny — martwy link wciąż "
        "podpisywalny (P0.2). Sample = signature_id, nigdy surowy token.",
        """
        SELECT l.signature_id AS signature_id,
               COUNT(*) OVER () AS total_count
        FROM signature_links l
        JOIN document_signatures s ON s.id = l.signature_id
        WHERE l.used_at IS NULL
          AND l.revoked IS FALSE
          AND l.expires_at > NOW()
          AND s.status IN ('withdrawn', 'completed', 'rejected', 'failed', 'expired')
        ORDER BY l.signature_id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "ended_with_assigned_equipment",
        "P2",
        "Kontrakt ended ze sprzętem wydanym i nadal nierozliczonym "
        "(return_status=pending) — zakończenie bez zwrotu aktywów (P1.10).",
        """
        SELECT c.id AS contract_id, e.id AS equipment_id,
               COUNT(*) OVER () AS total_count
        FROM contracts c
        JOIN contract_equipment e ON e.contract_id = c.id
        WHERE c.status = 'ended'
          AND e.handed_over_date IS NOT NULL
          AND e.return_status = 'pending'
        ORDER BY c.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "duplicate_contract_number",
        "P2",
        "Powtórzony (contract_number, year) w b2b_generated_contracts — "
        "kolizja numeracji, np. po delete najnowszego wpisu (P0.11).",
        """
        SELECT contract_number, occurrences,
               COUNT(*) OVER () AS total_count
        FROM (
            SELECT contract_number, year, COUNT(*) AS occurrences
            FROM b2b_generated_contracts
            GROUP BY contract_number, year
            HAVING COUNT(*) > 1
        ) dups
        ORDER BY occurrences DESC, contract_number DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "duplicate_invoice_number",
        "P2",
        "Powtórzony invoice_number — brak twardej unikalności numeru faktury (P1.12).",
        """
        SELECT invoice_number, occurrences,
               COUNT(*) OVER () AS total_count
        FROM (
            SELECT invoice_number, COUNT(*) AS occurrences
            FROM invoices
            GROUP BY invoice_number
            HAVING COUNT(*) > 1
        ) dups
        ORDER BY occurrences DESC, invoice_number DESC
        LIMIT :sample_limit
        """,
    ),
    # ── Audyt 18.09.2026: wiersze do ręcznego rozstrzygnięcia przez Delivery ──
    # Każdy z nich wymaga DECYZJI BIZNESOWEJ (którą wersję zostawić, jaka jest
    # prawdziwa data), więc świadomie nie ma dla nich automatu — raport tak,
    # migracja naprawcza nie.
    (
        "duplicate_order_group_number",
        "P0",
        "Dwa żywe zamówienia MD/kosztowe o TYM SAMYM numerze u tego samego "
        "klienta — budżet jest liczony podwójnie. Brak unikalności na "
        "(client_id, order_number) w `client_order_groups`; dołożenie "
        "ograniczenia wymaga najpierw rozstrzygnięcia duplikatów.",
        """
        SELECT g.client_id, g.order_number, COUNT(*) AS occurrences,
               COUNT(*) OVER () AS total_count
        FROM client_order_groups g
        WHERE g.order_number IS NOT NULL
          AND g.order_number <> ''
          AND g.status IN ('draft', 'active', 'scheduled')
        GROUP BY g.client_id, g.order_number
        HAVING COUNT(*) > 1
        ORDER BY occurrences DESC, g.order_number DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "md_rate_looks_hourly",
        "P1",
        "Stawka w polu ZA MD jest tak niska, że wygląda na stawkę GODZINOWĄ "
        "wpisaną w złą kolumnę (konsultant za 10,88 zł/MD). Próg 100 PLN/MD: "
        "realna stawka dzienna nie schodzi tak nisko, a godzinowa rzadko ją "
        "przekracza. Korekta to zwykle ×8, ale potwierdza ją człowiek.",
        """
        SELECT o.id AS order_id, o.contract_id, o.client_id,
               COUNT(*) OVER () AS total_count
        FROM client_orders o
        WHERE o.order_group_id IS NOT NULL
          AND o.status IN ('draft', 'active', 'paused')
          AND (
            (o.md_rate_cost IS NOT NULL AND o.md_rate_cost > 0
             AND o.md_rate_cost < 100)
            OR (o.md_rate_revenue IS NOT NULL AND o.md_rate_revenue > 0
                AND o.md_rate_revenue < 100)
          )
        ORDER BY o.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "live_contract_without_start_date",
        "P1",
        "Żywy kontrakt bez daty rozpoczęcia. Od 18.09.2026 taki kontrakt LICZY "
        "się do MRR i liczników (brak daty = brak wiedzy, nie „planowany”), "
        "więc nie znika już po cichu — ale data nadal jest do uzupełnienia "
        "i tylko Delivery ją zna.",
        f"""
        SELECT c.id AS contract_id, c.candidate_id, c.client_id,
               COUNT(*) OVER () AS total_count
        FROM contracts c
        WHERE c.status IN {_LIVE}
          AND c.start_date IS NULL
        ORDER BY c.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "terminated_at_survived_reopen",
        "P2",
        "Kontrakt jest ŻYWY, a niesie datę wypowiedzenia — ślad po przywróceniu "
        "współpracy. `terminated_at` nie jest czyszczone przy aneksie ani "
        "`reopen_contract`, więc reguła daty końca umowy B2B czyta stan, który "
        "przestał obowiązywać.",
        f"""
        SELECT c.id AS contract_id, c.candidate_id, c.client_id,
               COUNT(*) OVER () AS total_count
        FROM contracts c
        WHERE c.status IN {_LIVE}
          AND c.terminated_at IS NOT NULL
        ORDER BY c.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "live_order_rate_not_synced_to_contract",
        "P1",
        "Żywe zamówienie niesie stawkę klienta, a kontrakt pod nim jej nie ma. "
        "Podzbiór `active_without_rates`, ale wskazuje ZAMÓWIENIE, z którego "
        "stawkę wziąć — dlatego jest osobno. "
        "marża i MRR liczą się wtedy z niczego. Kierunek zamówienie→kontrakt "
        "działa od 0304, więc to są wiersze SPRZED synchronizacji albo takie, "
        "których żaden zapis od tego czasu nie dotknął.",
        f"""
        SELECT c.id AS contract_id, c.candidate_id, c.client_id,
               o.id AS order_id,
               COUNT(*) OVER () AS total_count
        FROM contracts c
        JOIN client_orders o ON o.contract_id = c.id
        WHERE c.status IN {_LIVE}
          AND o.order_group_id IS NULL
          AND o.status IN ('active', 'paused')
          AND o.rate_client IS NOT NULL
          AND o.rate_client > 0
          AND c.rate_client IS NULL
        ORDER BY c.id DESC
        LIMIT :sample_limit
        """,
    ),
]

_TOTALS_SQL = f"""
    SELECT
        (SELECT COUNT(*) FROM contracts) AS contracts_total,
        (SELECT COUNT(*) FROM contracts WHERE status IN {_LIVE}) AS active_ending,
        (SELECT COUNT(*) FROM contracts WHERE status = 'draft') AS draft,
        (SELECT COUNT(*) FROM contracts WHERE status = 'ended') AS ended,
        (SELECT COUNT(*) FROM client_orders) AS client_orders_total,
        (SELECT COUNT(*) FROM document_signatures) AS signatures_total,
        (SELECT COUNT(*) FROM invoices) AS invoices_total
"""


async def _run_check(
    db: AsyncSession, key: str, severity: str, description: str, sql: str
) -> dict[str, Any]:
    """Execute one anomaly query; never raise — report error inline."""
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(
            db.execute(
                text(sql), {"sample_limit": SAMPLE_LIMIT, "today": business_today()}
            ),
            timeout=CHECK_TIMEOUT_SECONDS,
        )
        rows = result.mappings().all()
        count = int(rows[0]["total_count"]) if rows else 0
        sample = [{k: v for k, v in row.items() if k != "total_count"} for row in rows]
        return {
            "key": key,
            "severity": severity,
            "description": description,
            "count": count,
            "sample": sample,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 — raport ma przeżyć błąd checku
        return {
            "key": key,
            "severity": severity,
            "description": description,
            "count": None,
            "sample": [],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


@router.get(
    "/engagement-inventory",
    summary="Read-only raport anomalii lifecycle współpracy/kontraktu (M5 PR-00)",
)
async def engagement_inventory(
    auth_mode: Annotated[str, Depends(_snapshot_auth)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    started = time.monotonic()

    totals: dict[str, Any]
    try:
        totals_row = (
            (
                await asyncio.wait_for(
                    db.execute(text(_TOTALS_SQL)), timeout=CHECK_TIMEOUT_SECONDS
                )
            )
            .mappings()
            .one()
        )
        totals = dict(totals_row)
    except Exception as exc:  # noqa: BLE001
        totals = {"error": f"{type(exc).__name__}: {exc}"}

    checks = [
        await _run_check(db, key, severity, description, sql)
        for key, severity, description, sql in _CHECKS
    ]

    counted = [c for c in checks if c["count"] is not None]
    return {
        "query_version": QUERY_VERSION,
        "module": "m5-engagement",
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sample_limit": SAMPLE_LIMIT,
        "totals": totals,
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(checks) - len(counted),
            "anomalies_p0": sum(c["count"] for c in counted if c["severity"] == "P0"),
            "anomalies_p1": sum(c["count"] for c in counted if c["severity"] == "P1"),
            "anomalies_p2": sum(c["count"] for c in counted if c["severity"] == "P2"),
        },
        "checks": checks,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "auth_mode": auth_mode,
    }
