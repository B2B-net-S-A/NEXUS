"use client";

import { useQuery } from "@tanstack/react-query";
import { Mail } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { fetchCproLog, type CproEventKind, type CproLogRow, type CproOutcome } from "@/lib/cpro-events-api";
import { formatDayMonthPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

// PROTOTYP do makiety (02.11.2026): dziennik zdarzeń CPro i wyłączniki.

const KIND_LABEL: Record<CproEventKind, string> = {
  closed: "Request zamknięty",
  rejected: "Klient odrzucił",
  interview: "Klient chce rozmowy",
  withdrawn: "Rozmowa wycofana",
};

const OUTCOME_CLASS: Record<CproOutcome, string> = {
  done: "bg-success-muted text-success-muted-foreground",
  already: "bg-muted text-muted-foreground",
  notified: "bg-primary/10 text-primary",
  manual: "bg-warning-muted text-warning-muted-foreground",
};

const OUTCOME_LABEL: Record<CproOutcome, string> = {
  done: "Zrobione",
  already: "Już było",
  notified: "Powiadomiono",
  manual: "Do ręcznego",
};

const RULES: { label: string; action: string; on: boolean }[] = [
  { label: "Request zamknięty w CPro", action: "Zamknij rekrutację i powiadom rekruterów", on: true },
  { label: "Klient odrzucił osobę", action: "Przenieś kartę do „Zamknięci” i powiadom prowadzącego", on: true },
  { label: "Klient chce rozmowy", action: "Powiadom Delivery Leada i prowadzącego", on: true },
];

const HOUR = new Intl.DateTimeFormat("pl-PL", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

function Row({ row }: { row: CproLogRow }) {
  return (
    <tr className="border-t border-border align-top">
      <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
        {formatDayMonthPl(row.at)} {HOUR.format(new Date(row.at))}
      </td>
      <td className="whitespace-nowrap px-3 py-2 font-medium text-foreground">{KIND_LABEL[row.kind]}</td>
      <td className="max-w-[260px] px-3 py-2">
        <span className="block truncate text-foreground">
          {row.request ? `${row.request} · ` : ""}
          {row.job_title ?? "brak rekrutacji w NEXUSIE"}
        </span>
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

export default function CproSettingsPage() {
  const log = useQuery({ queryKey: ["cpro-log"], queryFn: fetchCproLog });
  const [onlyManual, setOnlyManual] = useState(false);
  const rows = (log.data?.rows ?? []).filter((row) => !onlyManual || row.outcome === "manual");

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
          <Mail className="h-5 w-5 text-primary" aria-hidden />
          CPro (Nordea)
        </h1>
        <p className="text-sm text-muted-foreground">
          Zmiany z maili CPro w skrzynkach Delivery Leadów. NEXUS czyta tylko maile od noreply@onevms.se z linkiem do
          nordea.onevms.se.
        </p>
      </div>

      {log.data ? (
        <div className="grid grid-cols-4 gap-3">
          {[
            ["Zamknięte requesty", log.data.counts.closed],
            ["Odrzucone osoby", log.data.counts.rejected],
            ["Prośby o rozmowę", log.data.counts.interview],
            ["Do ręcznego", log.data.counts.manual],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg border border-border bg-card px-4 py-2.5">
              <p className="text-xs text-muted-foreground">
                {label} od {log.data.since}
              </p>
              <p className="text-xl font-semibold text-foreground tabular-nums">{value}</p>
            </div>
          ))}
        </div>
      ) : null}

      <section className="rounded-lg border border-border bg-card">
        <h2 className="border-b border-border px-4 py-2 text-sm font-semibold text-foreground">Co NEXUS robi sam</h2>
        <ul className="divide-y divide-border">
          {RULES.map((rule) => (
            <li key={rule.label} className="flex items-center gap-3 px-4 py-2 text-sm">
              <span className="w-56 shrink-0 font-medium text-foreground">{rule.label}</span>
              <span className="min-w-0 flex-1 text-muted-foreground">{rule.action}</span>
              <span className="rounded-full bg-success-muted px-2 py-0.5 text-xs font-medium text-success-muted-foreground">
                Włączone
              </span>
              <Button type="button" size="sm" variant="outline">
                Wyłącz
              </Button>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-lg border border-border bg-card">
        <div className="flex items-center gap-2 border-b border-border px-4 py-2">
          <h2 className="flex-1 text-sm font-semibold text-foreground">Dziennik</h2>
          <Button type="button" size="sm" variant={onlyManual ? "outline" : "default"} onClick={() => setOnlyManual(false)}>
            Wszystko
          </Button>
          <Button type="button" size="sm" variant={onlyManual ? "default" : "outline"} onClick={() => setOnlyManual(true)}>
            Do ręcznego
          </Button>
        </div>
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
            {rows.map((row, index) => (
              <Row key={`${row.at}-${index}`} row={row} />
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
