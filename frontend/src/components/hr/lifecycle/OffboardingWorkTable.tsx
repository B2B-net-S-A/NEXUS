"use client";

import {
  HANDOVER_ERROR_LABELS,
  type LifecycleCase,
  type TransferKind,
  type WorkRow,
} from "@/lib/api/hr-lifecycle";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";

import { isLiveStatus, reportsSummary } from "./lifecycle-format";
import { ReceiverSelect } from "./ReceiverSelect";

export function WorkTable({ data }: { data: LifecycleCase }) {
  const rows = data.work ?? [];
  const editable = data.can_manage && isLiveStatus(data.status) && !data.handover_executed_at;
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className={CALM_ROW}>
            <th className={`${CALM_HEAD} px-3 py-2 text-left`}>Co {data.person_name} ma w NEXUSIE</th>
            <th className={`${CALM_HEAD} px-3 py-2 text-right`}>Ile</th>
            <th className={`${CALM_HEAD} px-3 py-2 text-left`}>Przekaż do</th>
            <th className={`${CALM_HEAD} px-3 py-2 text-left`}>Uwagi</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.kind} className={CALM_ROW}>
              <td className="px-3 py-2 font-medium text-foreground">{row.label}</td>
              <td className={`${CALM_AMOUNT} px-3 py-2`}>{row.count ?? "—"}</td>
              <td className="px-3 py-2">
                <ReceiverCell caseId={data.id} row={row} editable={editable} />
              </td>
              <td className="px-3 py-2 text-muted-foreground">
                {row.note}
                <HandoverOutcome row={row} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Podwładni odchodzącej osoby — kto zostanie ich przełożonym (D5, etap 2). */
export function ReportsNote({ data }: { data: LifecycleCase }) {
  const text = reportsSummary(data.work ?? []);
  if (!text) return null;
  return (
    <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-foreground">
      {text}
    </p>
  );
}

function ReceiverCell({
  caseId,
  row,
  editable,
}: {
  caseId: number;
  row: WorkRow;
  editable: boolean;
}) {
  if (!row.transferable) {
    return <span className="text-muted-foreground">idzie z rekrutacjami</span>;
  }
  if (editable && row.status !== "done") {
    return (
      <ReceiverSelect
        caseId={caseId}
        kind={row.kind as TransferKind}
        receiverId={row.receiver_user_id}
        receiverName={row.receiver_name}
        label={row.label}
      />
    );
  }
  return <span>{row.receiver_name ?? "—"}</span>;
}

function HandoverOutcome({ row }: { row: WorkRow }) {
  if (row.status === "done") {
    const moved = row.result
      ? Object.values(row.result).reduce((sum, value) => Math.max(sum, value), 0)
      : 0;
    return <span className={CALM_SUBLINE}>Przekazane · {moved}</span>;
  }
  if (row.status === "failed") {
    return (
      <span className={`${CALM_SUBLINE} text-destructive`}>
        {HANDOVER_ERROR_LABELS[row.error ?? "error"] ?? HANDOVER_ERROR_LABELS.error}
      </span>
    );
  }
  return null;
}
