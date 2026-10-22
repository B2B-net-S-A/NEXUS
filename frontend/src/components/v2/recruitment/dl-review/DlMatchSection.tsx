"use client";

/**
 * „Pasuje też do Twoich rekrutacji” (Match, 22.10.2026) — sekcja przeglądu DL-a
 * i okna „Wyślij też do…”. Delivery Lead zaznacza inne swoje rekrutacje,
 * a akceptacja wysyła osobę także tam: „CV wysłane”, u Nordei kolejka Cpro.
 * Połączone z tą rekrutacją („Podobne rekrutacje”) są zaznaczone od razu,
 * reszta czeka na decyzję DL-a. Makiety: https://claude.ai/artifact/HTjysWg2TjaDvxvCtjd1RV.
 */

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import { BOARD_COLUMN_LABEL, type BoardColumnKey } from "@/lib/board-stages";
import { formatHourly, parseRateInput } from "@/lib/dl-review-margin";
import {
  dlMatchApi,
  dlMatchKeys,
  type DlMatchJob,
  type DlMatchSendResult,
  type DlMatchSuggestions,
  type DlMatchTarget,
} from "@/lib/dl-match-api";
import { cn } from "@/lib/utils";

const STALE_MS = 5 * 60 * 1000;

export interface DlMatchRowState {
  checked: boolean;
  /** Stawka wpisana przy tej rekrutacji; `null` = jak w głównej rekrutacji. */
  rate: string | null;
}

export type DlMatchSelection = Record<number, DlMatchRowState>;

/** Zaznaczone od razu: rekrutacje połączone z tą, do których da się wysłać. */
export function initialSelection(jobs: readonly DlMatchJob[]): DlMatchSelection {
  const out: DlMatchSelection = {};
  for (const job of jobs) out[job.job_id] = { checked: job.linked && job.sendable, rate: null };
  return out;
}

export function rowRate(state: DlMatchRowState | undefined, fallbackRate: string): string {
  return state?.rate ?? fallbackRate;
}

/**
 * Co pójdzie do serwera: zaznaczone, wysyłalne, ze stawką. Zaznaczone bez
 * stawki liczy `missingRate` — przycisk akceptacji czeka, aż DL ją wpisze.
 */
export function matchTargets(
  jobs: readonly DlMatchJob[],
  selection: DlMatchSelection,
  fallback: { rate: string; unit: string; currency: string },
): { targets: DlMatchTarget[]; missingRate: number } {
  const targets: DlMatchTarget[] = [];
  let missingRate = 0;
  for (const job of jobs) {
    const state = selection[job.job_id];
    if (!state?.checked || !job.sendable) continue;
    const value = parseRateInput(rowRate(state, fallback.rate));
    if (value == null || value <= 0) {
      missingRate += 1;
      continue;
    }
    targets.push({
      job_id: job.job_id,
      client_rate_value: value,
      client_rate_unit: fallback.unit,
      client_rate_currency: fallback.currency,
    });
  }
  return { targets, missingRate };
}

/** Jedno zdanie po wysyłce: ile poszło, a co nie i dlaczego. */
export function summarizeResults(results: readonly DlMatchSendResult[]): {
  sent: string | null;
  problems: string[];
} {
  const sent = results.filter((r) => r.status === "sent");
  const label = (r: DlMatchSendResult) => r.title ?? `#${r.job_id}`;
  const cpro = sent.filter((r) => r.destination === "cpro").length;
  const parts: string[] = [];
  if (sent.length > cpro) parts.push(`do klienta: ${sent.length - cpro}`);
  if (cpro > 0) parts.push(`do kolejki Cpro: ${cpro}`);
  const overridden = sent.filter((r) => r.qc === "overridden").length;
  return {
    sent: sent.length
      ? `Match: wysłano też do ${sent.length} rekrutacji (${parts.join(", ")})` +
        (overridden ? ` · QC przepuszczone w ${overridden}` : "")
      : null,
    problems: results
      .filter((r) => r.status !== "sent")
      .map((r) =>
        r.status === "verified_only"
          ? `${label(r)}: dodano na „Zweryfikowany”, wysyłka nie przeszła — ${r.reason ?? "odmowa"}`
          : `${label(r)}: ${r.reason ?? "nie wysłano"}`,
      ),
  };
}

function budgetHint(job: DlMatchJob): string | null {
  const max = job.budget_max_hourly != null ? Number(job.budget_max_hourly) : null;
  if (max == null || !Number.isFinite(max)) return null;
  return `budżet do ${formatHourly(max)}`;
}

function columnLabel(column: string): string {
  return BOARD_COLUMN_LABEL[column as BoardColumnKey] ?? column;
}

export interface DlMatchModel {
  query: ReturnType<typeof useQuery<DlMatchSuggestions>>;
  jobs: DlMatchJob[];
  selection: DlMatchSelection;
  toggle: (jobId: number, checked: boolean) => void;
  setRate: (jobId: number, rate: string) => void;
  reset: () => void;
}

/** Lista i zaznaczenie — stan żyje u rodzica (przegląd albo okno). */
export function useDlMatch(candidateId: number, fromJobId: number, enabled: boolean): DlMatchModel {
  const query = useQuery({
    queryKey: dlMatchKeys.one(fromJobId, candidateId),
    queryFn: () => dlMatchApi.suggestions(candidateId, fromJobId),
    enabled: enabled && candidateId > 0 && fromJobId > 0,
    staleTime: STALE_MS,
  });
  const jobs = useMemo(() => query.data?.jobs ?? [], [query.data]);
  const [edits, setEdits] = useState<{ key: string; selection: DlMatchSelection } | null>(null);
  const key = `${fromJobId}:${candidateId}:${jobs.map((j) => j.job_id).join(",")}`;
  // Zaznaczenie startuje od listy z serwera i zeruje się przy innej osobie.
  const selection = edits?.key === key ? edits.selection : initialSelection(jobs);
  const update = useCallback(
    (jobId: number, patch: Partial<DlMatchRowState>) =>
      setEdits((prev) => {
        const base = prev?.key === key ? prev.selection : initialSelection(jobs);
        const row = base[jobId] ?? { checked: false, rate: null };
        return { key, selection: { ...base, [jobId]: { ...row, ...patch } } };
      }),
    [jobs, key],
  );
  return {
    query,
    jobs,
    selection,
    toggle: (jobId, checked) => update(jobId, { checked }),
    setRate: (jobId, rate) => update(jobId, { rate, checked: true }),
    reset: () => setEdits(null),
  };
}

export interface DlMatchSectionProps {
  model: DlMatchModel;
  /** Stawka z głównej decyzji — podpowiedź w każdym wierszu. */
  fallbackRate: string;
  disabled?: boolean;
  className?: string;
}

export function DlMatchSection({ model, fallbackRate, disabled = false, className }: DlMatchSectionProps) {
  const { query, jobs, selection } = model;
  const alreadyIn = query.data?.already_in ?? [];
  if (query.isSuccess && jobs.length === 0 && alreadyIn.length === 0) return null;
  const checkedCount = jobs.filter((j) => selection[j.job_id]?.checked && j.sendable).length;

  return (
    <section
      aria-label="Pasuje też do Twoich rekrutacji"
      className={cn("space-y-1 rounded-lg border border-primary/40 bg-primary/5 p-3", className)}
      data-testid="dl-match-section"
    >
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-xs font-semibold text-foreground">Pasuje też do Twoich rekrutacji</h3>
        {jobs.length > 0 ? (
          <span className="text-[11px] text-muted-foreground">
            {checkedCount} z {jobs.length}
          </span>
        ) : null}
      </div>
      {query.isLoading ? (
        <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Loader2 className="size-3 animate-spin" aria-hidden /> Sprawdzam Twoje inne rekrutacje…
        </p>
      ) : query.isError ? (
        <p role="alert" className="text-[11px] text-destructive">
          Nie udało się sprawdzić innych rekrutacji.{" "}
          <button type="button" className="font-medium underline" onClick={() => void query.refetch()}>
            Ponów
          </button>
        </p>
      ) : (
        <>
          {query.data?.status === "unavailable" ? (
            <p className="text-[11px] text-muted-foreground">
              Ocena dopasowania chwilowo nie działa — widać tylko rekrutacje połączone z tą.
            </p>
          ) : null}
          <ul className="divide-y divide-border/60">
            {jobs.map((job) => {
              const state = selection[job.job_id];
              const checked = Boolean(state?.checked) && job.sendable;
              const name = [job.client_reference, job.title].filter(Boolean).join(" · ");
              const rateLabel = job.destination === "cpro" ? "Stawka do Cpro" : "Stawka do klienta";
              const budget = budgetHint(job);
              return (
                <li
                  key={job.job_id}
                  className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 py-2"
                  data-testid={`dl-match-row-${job.job_id}`}
                >
                  <Checkbox
                    checked={checked}
                    disabled={disabled || !job.sendable}
                    onCheckedChange={(value) => model.toggle(job.job_id, value === true)}
                    aria-label={`Wyślij też do: ${name}`}
                  />
                  <div className="min-w-0">
                    <p className="truncate text-xs font-semibold text-foreground" title={name}>
                      {name}
                      {job.client_name ? (
                        <span className="font-normal text-muted-foreground"> · {job.client_name}</span>
                      ) : null}
                    </p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground">
                      {job.score != null ? (
                        <span className="font-semibold text-success-muted-foreground">≈ {job.score}%</span>
                      ) : null}
                      {job.linked ? (
                        <span className="rounded-full bg-primary/10 px-1.5 font-medium text-primary">połączona</span>
                      ) : null}
                      {job.gap_must.length > 0 ? (
                        <span className="rounded-full bg-warning-muted px-1.5 font-medium text-warning-muted-foreground">
                          brak w CV: {job.gap_must.join(", ")}
                        </span>
                      ) : null}
                      <span
                        className={cn(
                          "rounded-full px-1.5 font-medium",
                          job.destination === "cpro"
                            ? "bg-warning-muted text-warning-muted-foreground"
                            : "bg-success-muted text-success-muted-foreground",
                        )}
                      >
                        {job.destination === "cpro" ? "→ kolejka Cpro" : "→ CV wysłane"}
                      </span>
                      {!job.sendable ? <span>szablon bez etapu wysyłki</span> : null}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-0.5">
                    <input
                      inputMode="decimal"
                      aria-label={`${rateLabel}: ${name}`}
                      className="h-8 w-20 rounded-md border border-input bg-background px-2 text-xs tabular-nums"
                      value={rowRate(state, fallbackRate)}
                      onChange={(e) => model.setRate(job.job_id, e.target.value)}
                      disabled={disabled || !job.sendable}
                      placeholder="stawka"
                    />
                    {budget ? <span className="text-[10px] text-muted-foreground">{budget}</span> : null}
                  </div>
                </li>
              );
            })}
            {alreadyIn.map((row) => (
              <li key={`in-${row.job_id}`} className="flex items-center justify-between gap-2 py-2 text-[11px] text-muted-foreground">
                <span className="min-w-0 truncate">
                  {[row.client_reference, row.title].filter(Boolean).join(" · ")} — już jest: {columnLabel(row.column)}
                </span>
                <Link href={`/jobs/${row.job_id}`} className="shrink-0 font-medium text-primary hover:underline">
                  Otwórz
                </Link>
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-muted-foreground">
            Twoje rekrutacje (portfel), wynik ≥ 70%. To samo CV, bez arkusza i pytań; proces zaliczy się Tobie.
            Rekruter tej rekrutacji dostanie prośbę, żeby dał znać kandydatowi.
          </p>
        </>
      )}
    </section>
  );
}
