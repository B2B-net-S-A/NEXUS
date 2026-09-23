import { Badge } from "@/components/ui/badge";
import type { QcStatus } from "@/lib/api/boardTasks";
import { QC_STATUS_LABEL } from "@/lib/cv-qc";

const QC_BADGE: Record<QcStatus, "success" | "danger" | "warning" | "outline"> = {
  passed: "success",
  failed: "danger",
  overridden: "warning",
  unchecked: "outline",
};

/** Wynik QC CV pary na liście (przegląd DL, kolejka Cpro). Brak statusu = nic. */
export function QcStatusBadge({
  row,
}: {
  row: { qc_status?: QcStatus | null; qc_blocking_failed?: number | null };
}) {
  if (!row.qc_status) return null;
  const label =
    row.qc_status === "failed" && row.qc_blocking_failed
      ? `QC: ${row.qc_blocking_failed} do poprawy`
      : QC_STATUS_LABEL[row.qc_status];
  return (
    <Badge size="sm" variant={QC_BADGE[row.qc_status]}>
      {label}
    </Badge>
  );
}
