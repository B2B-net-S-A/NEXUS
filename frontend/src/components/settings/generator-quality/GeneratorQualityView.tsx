"use client";

/**
 * Ustawienia → „Jakość generatora CV” (decyzja Artura 02.11.2026). Widok bez
 * zapytań; kontener: `app/settings/jakosc-generatora/page.tsx`. Pokazuje, co
 * rekruterzy zgłaszają przy pobraniu oryginału po złym wyniku generatora.
 */

import Link from "next/link";

import { DataTable, EmptyState, PageHeader, QueryStateNotice, StatCard, type DataTableColumn } from "@/components/ds";
import { cvFeedbackReasonLabel } from "@/lib/cv-download-access";
import type { GeneratorFeedbackEntry, GeneratorFeedbackSummary } from "@/lib/cv-generator-feedback";

export type GeneratorQualityLoad =
  | { status: "loading" }
  | { status: "error"; forbidden: boolean; message: string }
  | { status: "success"; summary: GeneratorFeedbackSummary };

export const QUALITY_PERIODS = [7, 30, 90] as const;

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("pl-PL", {
    timeZone: "Europe/Warsaw",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

const COLUMNS: DataTableColumn<GeneratorFeedbackEntry>[] = [
  { key: "date", header: "Kiedy", render: (row) => formatDate(row.created_at) },
  { key: "author", header: "Kto", render: (row) => row.author_name ?? "—" },
  {
    key: "person",
    header: "Kandydat i rekrutacja",
    render: (row) => (
      <div className="max-w-[15rem]">
        <Link href={`/candidates/${row.candidate_id}`} className="font-medium text-primary hover:underline">
          {row.candidate_name || `Kandydat ${row.candidate_id}`}
        </Link>
        {row.job_id != null ? (
          <p className="truncate text-xs text-muted-foreground">
            <Link href={`/jobs/${row.job_id}`} className="hover:underline">
              {row.job_title ?? `Rekrutacja ${row.job_id}`}
            </Link>
            {row.client_name ? ` · ${row.client_name}` : ""}
          </p>
        ) : null}
      </div>
    ),
  },
  {
    key: "reasons",
    header: "Co było źle",
    render: (row) => (
      <div className="max-w-sm space-y-1 whitespace-normal text-sm">
        <p>
          {row.generation_status === "failed" ? "Błąd generacji · " : ""}
          {row.reasons.map(cvFeedbackReasonLabel).join(", ")}
        </p>
        {row.detail ? <p className="whitespace-pre-line text-xs text-muted-foreground">{row.detail}</p> : null}
      </div>
    ),
  },
];

export function GeneratorQualityView({
  load,
  days,
  onDaysChange,
  onRetry,
}: {
  load: GeneratorQualityLoad;
  days: number;
  onDaysChange: (days: number) => void;
  onRetry: () => void;
}) {
  const header = (
    <PageHeader
      title="Jakość generatora CV"
      description="Co rekruterzy zgłaszają, gdy pobierają oryginał CV po złym wyniku generatora."
      actions={
        <div className="flex gap-1 rounded-md border border-border p-0.5" role="group" aria-label="Okres">
          {QUALITY_PERIODS.map((period) => (
            <button
              key={period}
              type="button"
              aria-pressed={days === period}
              onClick={() => onDaysChange(period)}
              className={
                days === period
                  ? "rounded bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary"
                  : "rounded px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
              }
            >
              {period} dni
            </button>
          ))}
        </div>
      }
    />
  );

  if (load.status === "loading") {
    return (
      <div className="mx-auto max-w-7xl space-y-5">
        {header}
        <p className="text-sm text-muted-foreground">Wczytuję zgłoszenia…</p>
      </div>
    );
  }
  if (load.status === "error") {
    return (
      <div className="mx-auto max-w-7xl space-y-5">
        {header}
        <QueryStateNotice
          state={load.forbidden ? "forbidden" : "error"}
          description={load.message}
          onRetry={load.forbidden ? undefined : onRetry}
        />
      </div>
    );
  }

  const { summary } = load;
  const topReason = summary.reasons[0];
  return (
    <div className="mx-auto max-w-7xl space-y-5">
      {header}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label="Zgłoszenia" value={summary.total} />
        <StatCard label="Gotowe CV z generatora" value={summary.generations_ready} />
        <StatCard
          label="Najczęstszy powód"
          value={topReason ? topReason.count : "—"}
          sub={topReason ? cvFeedbackReasonLabel(topReason.code) : undefined}
        />
      </div>
      {summary.total === 0 ? (
        <EmptyState
          title="Jeszcze nikt nie zgłosił uwag"
          description="Zgłoszenie powstaje, gdy osoba z rolą rekrutera pobiera oryginał CV po wyniku generatora."
        />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-semibold">Powody</h2>
              <ul className="space-y-1 text-sm">
                {summary.reasons.map((reason) => (
                  <li key={reason.code} className="flex justify-between gap-3">
                    <span>{cvFeedbackReasonLabel(reason.code)}</span>
                    <span className="tabular-nums text-muted-foreground">{reason.count}</span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-semibold">Klienci</h2>
              <ul className="space-y-1 text-sm">
                {summary.clients.map((client) => (
                  <li key={client.client_id ?? "brak"} className="flex justify-between gap-3">
                    <span>{client.client_name ?? "Bez klienta"}</span>
                    <span className="tabular-nums text-muted-foreground">{client.count}</span>
                  </li>
                ))}
              </ul>
            </section>
          </div>
          <DataTable columns={COLUMNS} rows={summary.entries} getRowKey={(row) => row.id} />
        </>
      )}
    </div>
  );
}
