import { Badge } from "@/components/ui/badge";
import type { QcStatus } from "@/lib/api/boardTasks";
import { clientFormStateBadge, type ClientFormState } from "@/lib/client-form-badge";
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

/** Wynik QC CV pary na liście (przegląd DL, kolejka Cpro). Brak statusu = nic.
 *  Para u klienta z formularzem CV (`client_form`) dostaje stan formularza —
 *  QC CV firmowego jej nie dotyczy (23.11.2026). */
export function QcStatusBadge({
  row,
  size = "sm",
  className,
}: {
  row: {
    qc_status?: QcStatus | null;
    qc_blocking_failed?: number | null;
    qc_state?: QcStateView | null;
    client_form?: ClientFormState | null;
  };
  size?: "sm" | "lg";
  /** Np. zawijanie w wąskiej komórce tabeli. */
  className?: string;
}) {
  if (row.client_form) {
    const form = clientFormStateBadge(row.client_form);
    return (
      <Badge
        size={size}
        variant={TONE_VARIANT[form.tone]}
        title={form.title}
        className={className}
        data-testid="client-form-status-badge"
      >
        {form.label}
      </Badge>
    );
  }
  if (!row.qc_status) return null;
  const state = row.qc_state ?? null;
  return (
    <Badge
      size={size}
      variant={state ? TONE_VARIANT[state.tone] : QC_BADGE[row.qc_status]}
      title={state?.hint ?? undefined}
      className={className}
    >
      {qcStateText({ status: row.qc_status, blocking_failed: row.qc_blocking_failed ?? 0, qc_state: state })}
    </Badge>
  );
}
