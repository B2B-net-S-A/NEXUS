"use client";

import { useEffect, useState } from "react";
import { FileBarChart } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { apiErrorMessage } from "@/lib/api-error";
import { useReports } from "@/lib/competence-reports/api";
import {
  formatDeadline,
  formatWhen,
  statusChips,
  type ReportListItem,
  type ReportScope,
  type ReportStatusFilter,
} from "@/lib/competence-reports/logic";
import { resolveViewState } from "@/lib/view-state";
import { cn } from "@/lib/utils";

import { ReportDetailSheet } from "./ReportDetailSheet";
import { CHIP_VARIANT, DEADLINE_CLASS } from "./tones";

const SCOPE_OPTIONS = [
  { value: "mine", label: "Moje" },
  { value: "all", label: "Wszystkie" },
] as const satisfies readonly { value: ReportScope; label: string }[];

const STATUS_OPTIONS = [
  { value: "open", label: "Do wysłania" },
  { value: "sent", label: "Wysłane" },
  { value: "", label: "Wszystkie stany" },
] as const satisfies readonly { value: ReportStatusFilter; label: string }[];

/** Licznik odświeża się co minutę bez pytania API. */
function useNow(intervalMs = 60_000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/**
 * „Raporty ze strony” (N6, 25.11.2026): raporty kompetencji dla osób, które
 * wysłały CV z warunkami na nowej stronie. Bez reakcji rekrutera raport wychodzi
 * sam przed upływem 24 godzin; tu można go obejrzeć, poprawić, wysłać wcześniej
 * albo wstrzymać. Kolejność: najbliższy termin na górze.
 */
export function ReportQueue() {
  const [scope, setScope] = useState<ReportScope>("mine");
  const [status, setStatus] = useState<ReportStatusFilter>("open");
  const [openId, setOpenId] = useState<number | null>(null);
  const now = useNow();
  const query = useReports(scope, status);
  const items = query.data ?? [];
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: items.length === 0,
    isSuccess: query.isSuccess,
  });

  return (
    <div className="space-y-4">
      <PageHeader
        title="Raporty ze strony"
        description="Raporty kompetencji dla osób, które wysłały CV z warunkami. Bez Twojej reakcji raport wychodzi sam przed upływem 24 godzin od zgłoszenia."
        density="compact"
      />

      <div className="flex flex-wrap items-center gap-3">
        <SegmentedRadio
          label="Czyje raporty"
          value={scope}
          onChange={setScope}
          options={SCOPE_OPTIONS}
          size="sm"
        />
        <SegmentedRadio
          label="Stan raportu"
          value={status}
          onChange={setStatus}
          options={STATUS_OPTIONS}
          size="sm"
        />
      </div>

      {viewState === "loading" ? (
        <p className="text-sm text-muted-foreground">Ładowanie…</p>
      ) : viewState === "empty" ? (
        <EmptyState
          icon={FileBarChart}
          title={status === "open" ? "Nic nie czeka na wysyłkę" : "Brak raportów"}
          description={
            scope === "mine"
              ? "Nie masz raportów z tym stanem. Raporty bez opiekuna i raporty innych osób są w „Wszystkie”."
              : "Raport powstaje, gdy ktoś wyśle CV z warunkami przez formularz na stronie."
          }
        />
      ) : viewState !== "ready" ? (
        <QueryStateNotice
          state={viewState}
          description={
            viewState === "error"
              ? apiErrorMessage(query.error, "Nie udało się wczytać raportów.")
              : undefined
          }
          onRetry={() => void query.refetch()}
        />
      ) : (
        <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full min-w-[960px] text-sm" data-testid="competence-report-queue">
            <thead className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Termin</th>
                <th scope="col" className="px-3 py-2 font-medium">Kandydat</th>
                <th scope="col" className="px-3 py-2 font-medium">Warunki</th>
                <th scope="col" className="px-3 py-2 font-medium">Stan</th>
                <th scope="col" className="px-3 py-2 font-medium">Opiekun</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((item) => (
                <QueueRow key={item.id} item={item} now={now} onOpen={() => setOpenId(item.id)} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ReportDetailSheet reportId={openId} now={now} onClose={() => setOpenId(null)} />
    </div>
  );
}

function QueueRow({ item, now, onOpen }: { item: ReportListItem; now: Date; onOpen: () => void }) {
  const deadline = formatDeadline(item, now);
  return (
    <tr
      className="cursor-pointer hover:bg-muted/60"
      onClick={onOpen}
      data-testid={`competence-report-row-${item.id}`}
    >
      <td className="whitespace-nowrap px-3 py-2.5 align-top">
        <span className={cn("block font-medium tabular-nums", DEADLINE_CLASS[deadline.tone])}>
          {deadline.text}
        </span>
        <span className="block text-xs text-muted-foreground tabular-nums">
          {item.sent_at ? `wysłany ${formatWhen(item.sent_at)}` : formatWhen(item.send_due_at)}
        </span>
      </td>
      <td className="px-3 py-2.5 align-top">
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onOpen();
          }}
          className="text-left font-medium text-foreground hover:text-primary hover:underline"
        >
          {item.candidate.name}
        </button>
        <span className="block text-xs text-muted-foreground">
          {item.role_label ?? "rola po odczycie CV"}
        </span>
      </td>
      <td className="max-w-[22rem] px-3 py-2.5 align-top text-muted-foreground">
        <span className="line-clamp-2" title={item.conditions_summary}>
          {item.conditions_summary}
        </span>
      </td>
      <td className="px-3 py-2.5 align-top">
        <span className="flex flex-wrap gap-1">
          {statusChips(item).map((chip) => (
            <Badge key={chip.label} variant={CHIP_VARIANT[chip.tone]}>
              {chip.label}
            </Badge>
          ))}
        </span>
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 align-top">
        {item.owner ? (
          <span className="text-foreground">{item.owner.name}</span>
        ) : (
          <span className="text-muted-foreground">bez opiekuna</span>
        )}
      </td>
    </tr>
  );
}
