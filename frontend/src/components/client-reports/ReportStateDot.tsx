import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { STATE_LABELS, type ReportState } from "@/lib/api/client-reports";

const TONES: Record<ReportState, StatusDotTone> = {
  overdue: "danger",
  today: "warning",
  todo: "info",
  sent: "success",
  no_date: "neutral",
};

export function ReportStateDot({ state, note }: { state: ReportState; note?: string }) {
  return (
    <StatusDot tone={TONES[state]} note={note}>
      {STATE_LABELS[state]}
    </StatusDot>
  );
}
