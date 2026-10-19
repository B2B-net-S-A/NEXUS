"use client";

import { personInitials } from "@/components/hr/people/hr-format";
import { Badge } from "@/components/ui/badge";
import {
  HANDOVER_ERROR_LABELS,
  type LifecycleCase,
  type TransferKind,
  type WorkRow,
} from "@/lib/api/hr-lifecycle";
import { CALM_SUBLINE } from "@/lib/calm-table";

import {
  goesWithRecruitments,
  isLiveStatus,
  reportsSummary,
  workLayout,
} from "./lifecycle-format";
import { ReceiverSelect } from "./ReceiverSelect";

/**
 * „Komu przekazać” (makieta 19.10.2026): wiersz na rodzaj pracy z liczbą
 * i przejmującym (awatar), praca idąca z rekrutacjami jako podpis pod nimi,
 * rodzaje z zerem zwinięte do jednej linijki pigułek.
 */
export function WorkTable({ data }: { data: LifecycleCase }) {
  const layout = workLayout(data.work ?? []);
  const editable = data.can_manage && isLiveStatus(data.status) && !data.handover_executed_at;
  const along = layout.withRecruitments
    .map((row) => `${row.label.toLowerCase()} ${row.count}`)
    .join(", ");
  return (
    <section
      className="min-w-0 flex-[999_1_640px] overflow-hidden rounded-lg border border-border bg-card"
      aria-labelledby="off-work"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <h2 id="off-work" className="text-sm font-semibold">
          Komu przekazać
        </h2>
        <span className="text-xs text-muted-foreground">
          Co {data.person_name} ma w NEXUSIE · zmiana działa w dniu przekazania
        </span>
      </div>
      <ul>
        {layout.rows.map((row) => (
          <li
            key={row.kind}
            className="grid grid-cols-[minmax(0,1fr)_56px] items-center gap-x-3 gap-y-2 border-t border-border/60 px-4 py-2.5 sm:grid-cols-[minmax(0,1fr)_56px_minmax(200px,240px)]"
          >
            <div className="min-w-0">
              <p className="font-medium text-foreground">{row.label}</p>
              <p className="text-xs text-muted-foreground">
                {row.kind === "recruitments" && along ? `z nimi idą: ${along}` : row.note}
              </p>
              <HandoverOutcome row={row} />
            </div>
            <span className="text-center text-lg font-bold tabular-nums">{row.count ?? "—"}</span>
            <div className="col-span-2 sm:col-span-1">
              <ReceiverCell caseId={data.id} row={row} editable={editable} />
            </div>
          </li>
        ))}
      </ul>
      {layout.empty.length ? (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-border/60 bg-muted/40 px-4 py-2.5">
          <span className="text-xs text-muted-foreground">Nic do przekazania:</span>
          {layout.empty.map((row) => (
            <Badge key={row.kind} variant="neutral" size="sm" className="h-auto py-0.5">
              {row.label.toLowerCase()} · 0
            </Badge>
          ))}
        </div>
      ) : null}
    </section>
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

function Avatar({ name }: { name: string }) {
  return (
    <span
      aria-hidden
      className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary"
    >
      {personInitials(name)}
    </span>
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
    // Zastępstwa zmienia osoba na urlopie albo Kadry we wniosku (uwaga w wierszu).
    return (
      <span className="text-sm text-muted-foreground">
        {goesWithRecruitments(row.kind) ? "idzie z rekrutacjami" : "poza przekazaniem"}
      </span>
    );
  }
  if (editable && row.status !== "done") {
    return (
      <div className="flex items-center gap-2">
        {row.receiver_name ? <Avatar name={row.receiver_name} /> : null}
        <ReceiverSelect
          caseId={caseId}
          kind={row.kind as TransferKind}
          receiverId={row.receiver_user_id}
          receiverName={row.receiver_name}
          label={row.label}
        />
      </div>
    );
  }
  return row.receiver_name ? (
    <span className="flex items-center gap-2 text-sm">
      <Avatar name={row.receiver_name} />
      {row.receiver_name}
    </span>
  ) : (
    <span className="text-sm text-muted-foreground">—</span>
  );
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
