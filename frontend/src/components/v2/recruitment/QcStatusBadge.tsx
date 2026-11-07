import { Badge } from "@/components/ui/badge";
import type { QcStatus } from "@/lib/api/boardTasks";
import { qcStateText } from "@/lib/cv-qc";

const QC_BADGE: Record<QcStatus, "success" | "danger" | "warning" | "outline"> = {
  passed: "success",
  failed: "danger",
  overridden: "warning",
  unchecked: "outline",
};

/**
 * Wynik QC CV pary na liście (przegląd DL, kolejka Cpro). Brak statusu = nic.
 * Zdane QC z blokującym „sprawdź ręcznie” (R1, 07.11.2026) jest bursztynowe,
 * nie zielone — tego nikt nie sprawdził.
 */
export function QcStatusBadge({
  row,
}: {
  row: {
    qc_status?: QcStatus | null;
    qc_blocking_failed?: number | null;
    qc_manual?: readonly string[] | null;
    qc_gaps?: readonly string[] | null;
  };
}) {
  if (!row.qc_status) return null;
  const manual = row.qc_manual ?? [];
  const gaps = row.qc_gaps ?? [];
  const label = qcStateText({
    status: row.qc_status,
    blocking_failed: row.qc_blocking_failed ?? 0,
    manual_checks: manual,
    candidate_gaps: gaps,
  });
  const attention = row.qc_status === "passed" && (manual.length > 0 || gaps.length > 0);
  const variant = attention ? "warning" : QC_BADGE[row.qc_status];
  const title =
    gaps.length > 0
      ? `Kandydat nie ma: ${gaps.join(", ")} — o wysyłce decyduje Delivery Lead`
      : manual.length > 0
        ? `Sprawdź ręcznie: ${manual.join(", ")}`
        : undefined;
  return (
    <Badge size="sm" variant={variant} title={title}>
      {label}
    </Badge>
  );
}
