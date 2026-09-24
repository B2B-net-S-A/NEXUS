"use client";

/**
 * Panel „Dodaj kandydatów" (Rekrutacja v5, makiety
 * https://claude.ai/artifact/CG4mBk9xcHZAn3y9jcmMeW, zakładka 3).
 *
 * JEDNO wejście do dodawania ludzi do rekrutacji — z nagłówka („＋ Dodaj
 * kandydatów") i z kolumny „Nowi" („Znajdź w bazie (AI)", „Przejrzyj").
 * Zbiera istniejące źródła, niczego nie liczy od nowa:
 *  - „Szukaj w bazie (AI)" — pełny przegląd bazy tej rekrutacji
 *    (`useJobProposals` → `useFullCandidateSearch`, kryteria z wymagań
 *    Championa/requestu, start WYŁĄCZNIE kliknięciem),
 *  - „Propozycje" — skrzynka, podobne projekty, rekomendacje (ta sama scalona
 *    lista co ekran „Do przejrzenia"),
 *  - „Moi ludzie" — `GET /api/my-people/for-job/{id}`,
 *  - „Po nazwisku / z pliku CV" — dotychczasowe okna.
 *
 * Dodanie idzie przez `proposals/bulk` jak dotąd (źródło z pochodzenia
 * wiersza: `full_search`, `proposal_inbox`, `historical`, `recommendation`,
 * `my_people`). Serwer zakłada blokadę 12 h dla dodającego. Ostrzeżenia
 * (NDA, konkurent, ponad budżet) zostają widoczne; weto hiring managera
 * blokuje zaznaczenie — jak w szybkim dodawaniu.
 */

import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Search, Sparkles, UserPlus } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FullCandidateSearchStatus } from "@/components/talent-radar/FullCandidateSearchStatus";
import { apiErrorMessage } from "@/lib/api-error";
import {
  MY_PEOPLE_QUERY_PREFIX,
  useMyPeopleForJob,
  type ForJobRow,
} from "@/lib/api/myPeople";
import type { MatchEligibility } from "@/lib/api";
import { assignErrorMessage } from "@/lib/assign-error";
import { formatReasonCounts, summarizeBulkResult } from "@/lib/bulk-result-summary";
import { proposalsBulkApi } from "@/lib/candidate-search-api";
import { eligibilityBadgeClass } from "@/lib/conflicts";
import { searchIsRunning } from "@/lib/full-candidate-search-api";
import { matchingRequirementsApi, requirementLabels } from "@/lib/matching-requirements";
import {
  DEFAULT_PROPOSAL_FILTERS,
  formatHourlyRate,
  type ProposalEntry,
} from "@/lib/proposals-merge";
import { cn } from "@/lib/utils";

import { RecruitmentSheet } from "./slideovers/RecruitmentSheet";
import { PROPOSAL_SOURCE_LABEL } from "./types";
import { useJobProposals } from "./useJobProposals";

export type AddCandidatesTab = "search" | "proposals" | "my_people" | "by_name";

export interface AddCandidatesPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  initialTab?: AddCandidatesTab;
  budgetHourly: number | null;
  /** Lokalizacja rekrutacji — chip kryteriów. */
  location?: string | null;
  /** Osoby już w rekrutacji (z tablicy) — nie pojawiają się w wynikach. */
  pipelineCandidateIds?: readonly number[];
  readOnly?: boolean;
  /** „Zmień kryteria" — dotychczasowe ręczne wyszukiwanie. */
  onOpenManualSearch: () => void;
  /** „Po nazwisku" — dotychczasowe szybkie dodawanie. */
  onOpenQuickAdd: () => void;
  /** „Z pliku CV" — okno dodania z CV (gdy strona je ma). */
  onOpenFromCv?: () => void;
}

/** Wiersz listy do zaznaczenia — wspólny dla trzech źródeł. */
interface PickRow {
  candidateId: number;
  fullName: string;
  fitScore: number | null;
  rateLabel: string | null;
  availabilityLabel: string | null;
  note: string | null;
  sourceLabel: string | null;
  warnings: Array<{ key: string; label: string; blocking: boolean }>;
}

const WARNING_LABEL: Record<string, string> = {
  hm_veto: "Weto HM",
  over_budget: "Ponad budżet",
  rejected_by_same_client: "Odrzucony przez tego klienta",
};

function eligibilityWarning(eligibility: MatchEligibility | null | undefined) {
  if (!eligibility || eligibility.reason_code === "eligible") return null;
  return {
    key: eligibility.reason_code,
    label:
      eligibility.assignment_allowed === false
        ? `Weto HM: ${eligibility.reason}`
        : eligibility.reason || eligibility.reason_code,
    blocking: eligibility.assignment_allowed === false,
  };
}

function proposalRow(entry: ProposalEntry): PickRow {
  const { row, detail } = entry;
  const source = row.sources.includes("reassign") ? "reassign" : row.sources[0];
  const warnings: PickRow["warnings"] = [];
  const elig = eligibilityWarning(detail.eligibility);
  if (elig) warnings.push(elig);
  for (const code of row.warnings) {
    if (code === "over_budget" || code === "rejected_by_same_client") {
      warnings.push({ key: code, label: WARNING_LABEL[code], blocking: false });
    }
  }
  return {
    candidateId: row.candidateId,
    fullName: row.fullName,
    fitScore: row.fitScore,
    rateLabel: row.rateLabel,
    availabilityLabel: row.availabilityLabel,
    note: row.reason ?? detail.title,
    sourceLabel: source ? PROPOSAL_SOURCE_LABEL[source] : null,
    warnings,
  };
}

function myPeopleRow(row: ForJobRow, budgetHourly: number | null): PickRow {
  const warnings: PickRow["warnings"] = [];
  const elig = eligibilityWarning(row.eligibility);
  if (elig) warnings.push(elig);
  if (budgetHourly != null && row.expected_rate_hourly != null && row.expected_rate_hourly > budgetHourly) {
    warnings.push({ key: "over_budget", label: WARNING_LABEL.over_budget, blocking: false });
  }
  const sent = row.last_sent_client_name
    ? `Wysłany do: ${row.last_sent_client_name}${row.days_since_last_send != null ? ` · ${row.days_since_last_send} dni temu` : ""}`
    : null;
  return {
    candidateId: row.candidate_id,
    fullName: row.full_name,
    fitScore: row.score,
    rateLabel: formatHourlyRate(row.expected_rate_hourly),
    availabilityLabel: row.active_processes > 0 ? `W procesach: ${row.active_processes}` : null,
    note: sent,
    sourceLabel: null,
    warnings,
  };
}

function PickList({
  rows,
  selected,
  onToggle,
  readOnly,
  emptyText,
  label,
}: {
  rows: PickRow[];
  selected: ReadonlySet<number>;
  onToggle: (row: PickRow) => void;
  readOnly: boolean;
  emptyText: string;
  label: string;
}) {
  if (rows.length === 0) {
    return <p className="py-4 text-sm text-muted-foreground">{emptyText}</p>;
  }
  return (
    <ul aria-label={label} className="divide-y divide-border rounded-md border border-border">
      {rows.map((row) => {
        const blocked = row.warnings.some((w) => w.blocking);
        const checked = selected.has(row.candidateId);
        const inputId = `add-candidate-${row.candidateId}`;
        return (
          <li
            key={row.candidateId}
            data-candidate-id={row.candidateId}
            className={cn("flex items-start gap-3 px-3 py-2", checked && "bg-primary/5")}
          >
            <Checkbox
              id={inputId}
              checked={checked}
              disabled={readOnly || blocked}
              onCheckedChange={() => onToggle(row)}
              aria-label={`Zaznacz ${row.fullName}`}
              className="mt-0.5"
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-start justify-between gap-2">
                <label htmlFor={inputId} className="min-w-0 truncate text-sm font-medium text-foreground">
                  {row.fullName}
                </label>
                <span
                  className={cn(
                    "shrink-0 text-xs font-bold tabular-nums",
                    row.fitScore != null ? "text-primary" : "font-normal text-muted-foreground",
                  )}
                  title={row.fitScore != null ? "Dopasowanie do rekrutacji" : "Dopasowania nie policzono"}
                >
                  {row.fitScore != null ? `${Math.round(row.fitScore)}%` : "nie policzono"}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                {[row.rateLabel ?? "stawka —", row.availabilityLabel].filter(Boolean).join(" · ")}
              </p>
              {row.note && <p className="line-clamp-2 text-xs text-muted-foreground">{row.note}</p>}
              {(row.sourceLabel || row.warnings.length > 0) && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {row.sourceLabel && (
                    <span className="rounded bg-muted px-1.5 text-[10.5px] font-semibold text-muted-foreground">
                      {row.sourceLabel}
                    </span>
                  )}
                  {row.warnings.map((w) => (
                    <span
                      key={w.key}
                      className={cn(
                        "rounded px-1.5 text-[10.5px] font-semibold",
                        eligibilityBadgeClass({ assignment_allowed: !w.blocking }),
                      )}
                    >
                      {w.label}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

const TAB_ORDER: AddCandidatesTab[] = ["search", "proposals", "my_people", "by_name"];

export function AddCandidatesPanel(props: AddCandidatesPanelProps) {
  // Treść (i jej zapytania) żyje wyłącznie przy otwartym panelu — wejście na
  // stronę rekrutacji nie może odpalać przeglądu bazy ani „Moich ludzi".
  if (!props.open) return null;
  return <AddCandidatesPanelOpen {...props} />;
}

function AddCandidatesPanelOpen({
  onOpenChange,
  jobId,
  initialTab = "search",
  budgetHourly,
  location = null,
  pipelineCandidateIds,
  readOnly = false,
  onOpenManualSearch,
  onOpenQuickAdd,
  onOpenFromCv,
}: AddCandidatesPanelProps) {
  const queryClient = useQueryClient();
  const { showToast, showError } = useToast();
  const [tab, setTab] = useState<AddCandidatesTab>(initialTab);
  // Zaznaczenie ze wszystkich zakładek naraz — każda osoba pamięta, skąd ją
  // wzięto (źródło w `proposals/bulk`).
  const [selected, setSelected] = useState<Map<number, "proposal" | "my_people">>(() => new Map());

  const proposals = useJobProposals(jobId, {
    filters: DEFAULT_PROPOSAL_FILTERS,
    budgetHourly,
    pipelineCandidateIds,
    readOnly,
  });
  const requirements = useQuery({
    queryKey: ["matching-requirements", jobId],
    queryFn: () => matchingRequirementsApi.get(jobId),
    staleTime: 60_000,
  });
  const myPeople = useMyPeopleForJob(jobId, tab === "my_people");

  const searchRows = useMemo(
    () => proposals.entries.filter((e) => e.detail.origins.includes("run")).map(proposalRow),
    [proposals.entries],
  );
  const proposalRows = useMemo(
    () =>
      proposals.entries
        .filter((e) => e.detail.origins.some((o) => o !== "run"))
        .map(proposalRow),
    [proposals.entries],
  );
  const inJob = useMemo(() => new Set(pipelineCandidateIds ?? []), [pipelineCandidateIds]);
  const myPeopleRows = useMemo(
    () =>
      (myPeople.data?.rows ?? [])
        .filter((r) => !inJob.has(r.candidate_id))
        .map((r) => myPeopleRow(r, budgetHourly)),
    [myPeople.data, inJob, budgetHourly],
  );

  const toggle = useCallback((row: PickRow, origin: "proposal" | "my_people") => {
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(row.candidateId)) next.delete(row.candidateId);
      else next.set(row.candidateId, origin);
      return next;
    });
  }, []);
  const selectedIds = useMemo(() => new Set(selected.keys()), [selected]);

  const addMyPeople = useMutation({
    mutationFn: (ids: number[]) =>
      proposalsBulkApi.add(jobId, { candidate_ids: ids, source: "my_people" }),
  });
  const [adding, setAdding] = useState(false);
  const count = selected.size;

  const addSelected = async () => {
    if (readOnly || count === 0) return;
    const proposalIds: number[] = [];
    const peopleIds: number[] = [];
    selected.forEach((origin, id) => (origin === "my_people" ? peopleIds : proposalIds).push(id));
    setAdding(true);
    try {
      // Propozycje: wspólna ścieżka z ekranem „Do przejrzenia" (źródło
      // i przegląd z pochodzenia wiersza, własny komunikat wyniku).
      if (proposalIds.length > 0) proposals.addToJob(proposalIds);
      if (peopleIds.length > 0) {
        const result = await addMyPeople.mutateAsync(peopleIds);
        const summary = summarizeBulkResult(result);
        const tail = [
          summary.skipped.length ? `pominięto: ${formatReasonCounts(summary.skipped)}` : "",
          summary.warnings.length ? `uwaga: ${formatReasonCounts(summary.warnings)}` : "",
        ]
          .filter(Boolean)
          .join("; ");
        const head = summary.added > 0 ? `Dodano z Moich ludzi: ${summary.added}` : "Nikogo z Moich ludzi nie dodano";
        showToast(tail ? `${head} — ${tail}` : head, summary.added > 0 ? "success" : "error");
        void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
        void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
        void queryClient.invalidateQueries({ queryKey: MY_PEOPLE_QUERY_PREFIX });
      }
      setSelected(new Map());
    } catch (error) {
      showError(assignErrorMessage(error));
    } finally {
      setAdding(false);
    }
  };

  const must = requirementLabels(requirements.data, "must");
  const nice = requirementLabels(requirements.data, "nice");
  const run = proposals.status.run;
  const runData = run.data;
  // Przegląd w toku: drugi start dublowałby trzyminutowy skan.
  const scanning = runData != null && searchIsRunning(runData.state);
  const tabLabel: Record<AddCandidatesTab, string> = {
    search: "Szukaj w bazie (AI)",
    proposals: `Propozycje · ${proposalRows.length}`,
    my_people: myPeople.data ? `Moi ludzie · ${myPeopleRows.length}` : "Moi ludzie",
    by_name: "Po nazwisku / z pliku CV",
  };

  const toolbar = (
    <div role="tablist" aria-label="Skąd dodać" className="flex flex-wrap gap-1 pb-2">
      {TAB_ORDER.map((key) => (
        <button
          key={key}
          type="button"
          role="tab"
          id={`add-candidates-tab-${key}`}
          aria-selected={tab === key}
          aria-controls={`add-candidates-panel-${key}`}
          onClick={() => setTab(key)}
          className={cn(
            "inline-flex h-8 items-center rounded-md px-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            tab === key ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground",
          )}
        >
          {tabLabel[key]}
        </button>
      ))}
    </div>
  );

  const footer = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-xs text-muted-foreground" aria-live="polite" data-testid="add-candidates-summary">
        {count > 0
          ? `${count} zaznaczonych trafi do »Nowych«, zarezerwowanych dla Ciebie na 12 h.`
          : "Zaznacz osoby — trafią do »Nowych«, zarezerwowane dla Ciebie na 12 h."}
      </p>
      <Button
        onClick={addSelected}
        disabled={readOnly || count === 0 || adding || proposals.adding}
        loading={adding || proposals.adding}
        data-testid="add-candidates-submit"
      >
        <UserPlus className="h-4 w-4" aria-hidden="true" />
        Dodaj {count} do Nowych
      </Button>
    </div>
  );

  return (
    <RecruitmentSheet
      open
      onOpenChange={onOpenChange}
      title="Dodaj kandydatów"
      description="Z przeglądu bazy, propozycji, Twoich ludzi albo po nazwisku."
      toolbar={toolbar}
      footer={footer}
      data-testid="add-candidates-panel"
    >
      <div
        role="tabpanel"
        id={`add-candidates-panel-${tab}`}
        aria-labelledby={`add-candidates-tab-${tab}`}
        className="space-y-3"
      >
        {tab === "search" && (
          <>
            <section aria-label="Kryteria" className="space-y-2 rounded-md border border-border p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Kryteria z Championa
                </p>
                <button
                  type="button"
                  onClick={() => {
                    onOpenChange(false);
                    onOpenManualSearch();
                  }}
                  className="text-xs font-semibold text-primary hover:underline"
                >
                  Zmień kryteria
                </button>
              </div>
              {requirements.isError ? (
                <p className="text-xs text-destructive">
                  {apiErrorMessage(requirements.error, "Nie wczytano wymagań rekrutacji.")}
                </p>
              ) : (
                <ul className="flex flex-wrap gap-1" aria-label="Kryteria wyszukiwania">
                  {must.map((m) => (
                    <li key={`m-${m}`} className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                      {m}
                    </li>
                  ))}
                  {nice.map((m) => (
                    <li
                      key={`n-${m}`}
                      className="rounded-full border border-dashed border-border px-2 py-0.5 text-[11px] text-muted-foreground"
                    >
                      {m}
                    </li>
                  ))}
                  {location && (
                    <li className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-foreground">📍 {location}</li>
                  )}
                  {budgetHourly != null && (
                    <li className="rounded-full bg-muted px-2 py-0.5 text-[11px] text-foreground">
                      do {budgetHourly} zł/h
                    </li>
                  )}
                  {requirements.isSuccess && must.length + nice.length === 0 && !location && budgetHourly == null && (
                    <li className="text-xs text-muted-foreground">Rekrutacja nie ma jeszcze wymagań — uzupełnij Championa.</li>
                  )}
                </ul>
              )}
            </section>

            <section aria-label="Przegląd bazy" className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <p className="mr-auto text-xs text-muted-foreground">
                  {scanning
                    ? "Przeglądamy całą bazę — potrwa ok. 3 minut."
                    : proposals.status.latestRun || runData
                      ? "Wyniki ostatniego przeglądu całej bazy."
                      : "Całej bazy jeszcze nie przeszukano."}
                </p>
                {!readOnly && (
                  <Button
                    size="sm"
                    variant={runData ? "outline" : "primary"}
                    loading={run.starting}
                    disabled={run.running || scanning}
                    onClick={proposals.status.startRun}
                  >
                    <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                    {run.runId || proposals.status.latestRun ? "Przeszukaj ponownie" : "Przeszukaj całą bazę"}
                  </Button>
                )}
              </div>
              {proposals.status.engineDegraded && (
                <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
                  Silnik dopasowań AI jest chwilowo niedostępny — brak liczby znaczy „nie policzono”, nie „nie pasuje”.
                </p>
              )}
              {run.error != null && (
                <p role="alert" className="text-xs text-destructive">
                  {apiErrorMessage(run.error, "Nie udało się odczytać przeglądu bazy.")}{" "}
                  <button type="button" className="underline" onClick={proposals.status.retryRun}>
                    Ponów
                  </button>
                </p>
              )}
              {runData && (run.error == null || searchIsRunning(runData.state)) && (
                <FullCandidateSearchStatus
                  data={runData}
                  offset={run.offset}
                  onPage={run.setOffset}
                  fetching={run.fetching}
                  onRestart={readOnly ? undefined : proposals.status.startRun}
                  restarting={run.running}
                  compact
                />
              )}
            </section>
            {runData && !searchIsRunning(runData.state) ? (
              <PickList
                label="Wyniki przeglądu bazy"
                rows={searchRows}
                selected={selectedIds}
                onToggle={(row) => toggle(row, "proposal")}
                readOnly={readOnly}
                emptyText="Przegląd nie znalazł osób spoza rekrutacji, które pasują."
              />
            ) : null}
          </>
        )}

        {tab === "proposals" &&
          (proposals.status.inbox.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {apiErrorMessage(proposals.status.inbox.error, "Nie wczytano propozycji.")}{" "}
              <button type="button" className="underline" onClick={proposals.status.retryEngine}>
                Ponów
              </button>
            </p>
          ) : !proposals.status.settled ? (
            <p role="status" className="text-sm text-muted-foreground">
              Wczytuję propozycje…
            </p>
          ) : (
            <PickList
              label="Propozycje"
              rows={proposalRows}
              selected={selectedIds}
              onToggle={(row) => toggle(row, "proposal")}
              readOnly={readOnly}
              emptyText="Nikt nie czeka w propozycjach."
            />
          ))}

        {tab === "my_people" &&
          (myPeople.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {apiErrorMessage(myPeople.error, "Nie wczytano Twoich ludzi.")}{" "}
              <button type="button" className="underline" onClick={() => void myPeople.refetch()}>
                Ponów
              </button>
            </p>
          ) : !myPeople.isSuccess ? (
            <p role="status" className="text-sm text-muted-foreground">
              Wczytuję Twoich ludzi…
            </p>
          ) : (
            <>
              {myPeople.data.degraded && (
                <p role="alert" className="text-xs text-warning">
                  Dopasowania chwilowo niepoliczone — to nie znaczy, że nikt nie pasuje.
                </p>
              )}
              <PickList
                label="Moi ludzie"
                rows={myPeopleRows}
                selected={selectedIds}
                onToggle={(row) => toggle(row, "my_people")}
                readOnly={readOnly}
                emptyText="Nikt z Twoich ludzi nie pasuje do tej rekrutacji."
              />
            </>
          ))}

        {tab === "by_name" && (
          <div className="grid gap-2 sm:grid-cols-2">
            <button
              type="button"
              disabled={readOnly}
              onClick={() => {
                onOpenChange(false);
                onOpenQuickAdd();
              }}
              className="flex flex-col items-start gap-1 rounded-md border border-border p-3 text-left hover:border-primary/40 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Search className="h-4 w-4 text-primary" aria-hidden="true" />
              <span className="text-sm font-medium text-foreground">Po nazwisku</span>
              <span className="text-xs text-muted-foreground">Nazwisko, e-mail albo telefon z bazy.</span>
            </button>
            {onOpenFromCv && (
              <button
                type="button"
                disabled={readOnly}
                onClick={() => {
                  onOpenChange(false);
                  onOpenFromCv();
                }}
                className="flex flex-col items-start gap-1 rounded-md border border-border p-3 text-left hover:border-primary/40 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <FileUp className="h-4 w-4 text-primary" aria-hidden="true" />
                <span className="text-sm font-medium text-foreground">Z pliku CV</span>
                <span className="text-xs text-muted-foreground">Nowy kandydat z CV.</span>
              </button>
            )}
          </div>
        )}
      </div>
    </RecruitmentSheet>
  );
}
