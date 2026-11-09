import { Badge } from "@/components/ui/badge";
import type { QcStatus } from "@/lib/api/boardTasks";
import { qcStateText, type QcStateTone, type QcStateView } from "@/lib/cv-qc";

const QC_BADGE: Record<QcStatus, "success" | "danger" | "warning" | "outline"> = {
  passed: "success",
  failed: "danger",
  overridden: "warning",
  unchecked: "outline",
};

const TONE_VARIANT: Record<QcStateTone, "success" | "info" | "warning" | "danger" | "outline"> = {
  ok: "success",
  info: "info",
  wait: "warning",
  urgent: "danger",
  neutral: "outline",
};

/** Wynik QC CV pary na liście (przegląd DL, kolejka Cpro). Brak statusu = nic. */
export function QcStatusBadge({
  row,
  size = "sm",
}: {
  row: {
    qc_status?: QcStatus | null;
    qc_blocking_failed?: number | null;
    qc_state?: QcStateView | null;
  };
  size?: "sm" | "lg";
}) {
  if (!row.qc_status) return null;
  const state = row.qc_state ?? null;
  return (
    <Badge size={size} variant={state ? TONE_VARIANT[state.tone] : QC_BADGE[row.qc_status]} title={state?.hint ?? undefined}>
      {qcStateText({ status: row.qc_status, blocking_failed: row.qc_blocking_failed ?? 0, qc_state: state })}
    </Badge>
  );
}
