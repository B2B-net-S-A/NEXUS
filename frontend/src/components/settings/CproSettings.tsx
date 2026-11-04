"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  fetchCproLog,
  saveCproRule,
  type CproEventKind,
  type CproLogRow,
  type CproOutcome,
  type CproRuleKey,
} from "@/lib/cpro-events-api";
import { formatDayMonthPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

const KIND_LABEL: Record<CproEventKind, string> = {
  closed: "Request zamknięty",
  rejected: "Klient odrzucił",
  interview: "Klient chce rozmowy",
  interview_withdrawn: "Rozmowa wycofana",
  slots_changed: "Zmienione terminy",
  unknown: "Nieczytelny mail",
};

const OUTCOME_CLASS: Record<CproOutcome, string> = {
  done: "bg-success-muted text-success-muted-foreground",
  already: "bg-muted text-muted-foreground",
  notified: "bg-primary/10 text-primary",
  manual: "bg-warning-muted text-warning-muted-foreground",
};

const OUTCOME_LABEL: Record<CproOutcome, string> = {
  done: "Zrobione",
  already: "Bez zmian",
  notified: "Powiadomiono",
  manual: "Do ręcznego",
};

const RULES: { key: CproRuleKey; label: string; action: string }[] = [
  { key: "closed", label: "Request zamknięty w CPro", action: "Zamknij rekrutację i powiadom rekruterów" },
  { key: "rejected", label: "Klient odrzucił osobę", action: "Przenieś kartę do „Zamknięci” i powiadom prowadzącego" },
  { key: "interview", label: "Klient chce rozmowy", action: "Powiadom Delivery Leada i prowadzącego" },
];

const HOUR = new Intl.DateTimeFormat("pl-PL", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

function moment(iso: string): string {
  return `${formatDayMonthPl(iso)} ${HOUR.format(new Date(iso))}`;
}

function LogRow({ row }: { row: CproLogRow }) {
  const title = `${row.request ? `${row.request} · ` : ""}${row.job_title ?? "brak rekrutacji w NEXUSIE"}`;
  return (
    <tr className="border-t border-border align-top">
      <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{moment(row.at)}</td>
      <td className="whitespace-nowrap px-3 py-2 font-medium text-foreground">{KIND_LABEL[row.kind]}</td>
      <td className="max-w-[260px] px-3 py-2">
        {row.job_id !== null ? (
          <Link
            href={row.candidate_id !== null ? `/jobs/${row.job_id}?candidate=${row.candidate_id}` : `/jobs/${row.job_id}`}
            className="block truncate text-foreground underline-offset-2 hover:underline"
            title={title}
          >
            {title}
          </Link>
        ) : (
          <span className="block truncate text-foreground">{title}</span>
        )}
        {row.person ? (
          <span className="block truncate text-xs text-muted-foreground">
            {row.person}
            {row.detail ? ` · „${row.detail}”` : ""}
          </span>
        ) : row.detail ? (
          <span className="block truncate text-xs text-muted-foreground">powód w CPro: {row.detail}</span>
        ) : null}
      </td>
      <td className="px-3 py-2">
        <span className={cn("inline-flex rounded-full px-2 py-0.5 text-xs font-medium", OUTCOME_CLASS[row.outcome])}>
          {OUTCOME_LABEL[row.outcome]}
        </span>
        <span className="mt-0.5 block text-xs text-muted-foreground">{row.outcome_text}</span>
      </td>
    </tr>
  );
}

/** Dziennik zdarzeń CPro i wyłączniki reguł (02.11.2026). */
export function CproSettings() {
  const queryClient = useQueryClient();
  const [onlyManual, setOnlyManual] = useState(false);
  const log = useQuery({
    queryKey: ["cpro-log", onlyManual],
    queryFn: () => fetchCproLog(onlyManual),
  });
  const save = useMutation({
    mutationFn: ({ key, on }: { key: CproRuleKey; on: boolean }) => saveCproRule(key, on),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["cpro-log"] }),
  });

  if (log.isError) {
    return (
      <div className="rounded-lg border border-border bg-card px-4 py-6 text-sm">
        <p className="text-foreground">{apiErrorMessage(log.error, "Nie udało się wczytać dziennika CPro.")}</p>
        <Button type="button" size="sm" variant="outline" className="mt-3" onClick={() => void log.refetch()}>
          Ponów
        </Button>
      </div>
    );
  }
  if (!log.isSuccess) {
    return <p className="text-sm text-muted-foreground">Wczytuję dziennik…</p>;
  }

  const data = log.data;
  const stale = data.mailboxes.filter((box) => box.stale);
  return (
    <>
      {stale.length > 0 ? (
        <p role="alert" className="rounded-lg border border-warning/40 bg-warning-muted px-4 py-2.5 text-sm text-warning-muted-foreground">
          <strong>Skrzynka nie synchronizuje się od ponad godziny: {stale.map((box) => box.name).join(", ")}.</strong> NEXUS
          nie zobaczy maili CPro, które przyszły tylko do tej osoby.
        </p>
      ) : null}
      {!data.enabled ? (
        <p role="alert" className="rounded-lg border border-warning/40 bg-warning-muted px-4 py-2.5 text-sm text-warning-muted-foreground">
          Odczyt maili CPro jest wyłączony na serwerze.
        </p>
      ) : null}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {(
          [
            ["Zamknięte requesty", data.counts.closed],
            ["Odrzucone osoby", data.counts.rejected],
            ["Prośby o rozmowę", data.counts.interview],
            ["Do ręcznego", data.counts.manual],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="rounded-lg border border-border bg-card px-4 py-2.5">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="text-xl font-semibold text-foreground tabular-nums">{value}</p>
          </div>
        ))}
      </div>

      <section className="rounded-lg border border-border bg-card">
        <h2 className="border-b border-border px-4 py-2 text-sm font-semibold text-foreground">Co NEXUS robi sam</h2>
        <ul className="divide-y divide-border">
          {RULES.map((rule) => {
            const on = data.rules[rule.key];
            return (
              <li key={rule.key} className="flex flex-wrap items-center gap-3 px-4 py-2 text-sm">
                <span className="w-56 shrink-0 font-medium text-foreground">{rule.label}</span>
                <span className="min-w-0 flex-1 text-muted-foreground">{rule.action}</span>
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-xs font-medium",
                    on ? "bg-success-muted text-success-muted-foreground" : "bg-muted text-muted-foreground",
                  )}
                >
                  {on ? "Włączone" : "Wyłączone"}
                </span>
                {data.can_edit ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={save.isPending}
                    onClick={() => save.mutate({ key: rule.key, on: !on })}
                  >
                    {on ? "Wyłącz" : "Włącz"}
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
        {save.isError ? (
          <p role="alert" className="border-t border-border px-4 py-2 text-sm text-destructive">
            {apiErrorMessage(save.error, "Nie udało się zapisać zmiany.")}
          </p>
        ) : null}
      </section>

      <section className="rounded-lg border border-border bg-card">
        <div className="flex items-center gap-2 border-b border-border px-4 py-2">
          <h2 className="flex-1 text-sm font-semibold text-foreground">Dziennik</h2>
          <Button type="button" size="sm" variant={onlyManual ? "outline" : "primary"} onClick={() => setOnlyManual(false)}>
            Wszystko
          </Button>
          <Button type="button" size="sm" variant={onlyManual ? "primary" : "outline"} onClick={() => setOnlyManual(true)}>
            Do ręcznego
          </Button>
        </div>
        {data.rows.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-muted-foreground">
            {onlyManual ? "Nic nie czeka na ręczne sprawdzenie." : "Nie ma jeszcze zdarzeń z CPro."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="px-3 py-1.5 font-medium">Kiedy</th>
                  <th className="px-3 py-1.5 font-medium">Co przyszło</th>
                  <th className="px-3 py-1.5 font-medium">Rekrutacja</th>
                  <th className="px-3 py-1.5 font-medium">Co zrobił NEXUS</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <LogRow key={row.id} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
