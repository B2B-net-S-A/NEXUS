"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pause } from "lucide-react";

import { useOptionalToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  holdSignalText,
  recruiterMovesText,
  type HoldCheckItem,
  type HoldSignal,
} from "@/lib/job-hold";
import { answerHoldCheck, useHoldChecks } from "@/lib/job-hold-api";
import { cn } from "@/lib/utils";

import { JobHoldDialog } from "./JobHoldDialog";

export interface HoldChecksPanelProps {
  /** Konto, które w ogóle dostaje pytania (DL, HoR, admin). */
  enabled: boolean;
  /** HoR i admin: wszystkie rekrutacje (`?all=true`), DL — swoje. */
  all?: boolean;
  className?: string;
}

/**
 * Panel „Czy te rekrutacje nadal trwają?” (decyzja Artura 26.11.2026,
 * makieta m5) na pulpicie DL i na `/jobs/daily`: rekrutacje „Szukamy”,
 * przy których coś mówi, że klient mógł je wstrzymać — zgłoszenie
 * rekrutera, notatka „on hold”, zejście z P1 przy dalszej pracy, cisza DL.
 * Pusta lista = panelu nie ma; awaria = komunikat, nie pusta lista.
 */
export function HoldChecksPanel({ enabled, all = false, className }: HoldChecksPanelProps) {
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  const query = useHoldChecks(enabled, all);
  const [holdFor, setHoldFor] = useState<HoldCheckItem | null>(null);
  const answer = useMutation({
    mutationFn: (jobId: number) => answerHoldCheck(jobId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["hold-checks"] });
      toast?.showSuccess("Zapisane: szukamy dalej. Rekruterzy, którzy pytali, dostali odpowiedź.");
    },
    onError: (error) =>
      toast?.showError(apiErrorMessage(error, "Nie udało się zapisać odpowiedzi.")),
  });

  if (!enabled) return null;
  if (query.isError) {
    return (
      <section
        className={cn("rounded-xl border border-border bg-card px-4 py-3", className)}
        data-testid="hold-checks-error"
      >
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(query.error, "Nie udało się sprawdzić, czy rekrutacje nadal trwają.")}
        </p>
      </section>
    );
  }
  if (!query.isSuccess || query.data.items.length === 0) return null;

  return (
    <>
      <HoldChecksPanelView
        className={className}
        items={query.data.items}
        total={query.data.total}
        busyJobId={answer.isPending ? (answer.variables ?? null) : null}
        onSearching={(item) => answer.mutate(item.job_id)}
        onHold={setHoldFor}
      />
      {holdFor ? (
        <JobHoldDialog
          jobId={holdFor.job_id}
          jobTitle={holdFor.title}
          open
          onOpenChange={(open) => {
            if (!open) setHoldFor(null);
          }}
        />
      ) : null}
    </>
  );
}

export interface HoldChecksPanelViewProps {
  items: HoldCheckItem[];
  total: number;
  busyJobId?: number | null;
  onSearching: (item: HoldCheckItem) => void;
  onHold: (item: HoldCheckItem) => void;
  className?: string;
}

const SIGNAL_TONE: Record<HoldSignal["kind"], string> = {
  report: "font-semibold text-warning-muted-foreground",
  note: "text-warning-muted-foreground",
  parked_still_working: "text-muted-foreground",
  dl_silent: "text-muted-foreground",
};

export function HoldChecksPanelView({
  items,
  total,
  busyJobId = null,
  onSearching,
  onHold,
  className,
}: HoldChecksPanelViewProps) {
  return (
    <section
      className={cn("@container rounded-xl border border-border bg-card", className)}
      data-testid="hold-checks-panel"
      aria-labelledby="hold-checks-title"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-border px-4 py-2.5">
        <h2 id="hold-checks-title" className="text-sm font-bold text-foreground">
          Czy te rekrutacje nadal trwają?{" "}
          <span className="font-normal text-muted-foreground">
            {total} do potwierdzenia · 1 klik
          </span>
        </h2>
        <span className="text-xs text-muted-foreground">Rekruterzy nad nimi pracują</span>
      </header>
      <ul className="divide-y divide-border">
        {items.map((item) => {
          const [first] = item.signals;
          const moves = recruiterMovesText(item);
          const busy = busyJobId === item.job_id;
          return (
            <li
              key={item.job_id}
              className="flex flex-col gap-2 px-4 py-2.5 @2xl:flex-row @2xl:items-center"
              data-testid="hold-check-row"
            >
              <div className="min-w-0 flex-1">
                <p className="flex min-w-0 items-baseline gap-2 text-sm">
                  {item.reference ? (
                    <span className="shrink-0 rounded bg-muted px-1.5 font-mono text-xs text-foreground">
                      {item.reference}
                    </span>
                  ) : null}
                  <span className="truncate font-semibold text-foreground">
                    {item.title}
                    {item.client_name ? ` · ${item.client_name}` : ""}
                  </span>
                </p>
                <p className="text-xs leading-snug">
                  {first ? (
                    <span className={SIGNAL_TONE[first.kind]}>{holdSignalText(first)}</span>
                  ) : null}
                  {moves ? (
                    <span className="text-muted-foreground">
                      {first ? " · " : ""}
                      {moves}
                    </span>
                  ) : null}
                  {item.signals.length > 1 ? (
                    <span
                      className="text-muted-foreground"
                      title={item.signals.slice(1).map(holdSignalText).join("\n")}
                    >
                      {" "}
                      · +{item.signals.length - 1}
                    </span>
                  ) : null}
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  loading={busy}
                  onClick={() => onSearching(item)}
                  data-testid="hold-check-searching"
                >
                  Szukamy
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => onHold(item)}
                  data-testid="hold-check-hold"
                >
                  <Pause className="h-3.5 w-3.5" aria-hidden="true" />
                  Wstrzymana…
                </Button>
                <Button asChild size="sm" variant="ghost">
                  <Link href={`/jobs/${item.job_id}`}>Otwórz</Link>
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
