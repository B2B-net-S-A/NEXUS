"use client";

/**
 * Segment „Propozycje z bazy" — jedna lista osób SPOZA rekrutacji z kolumną
 * „Źródło" (dawne: AI Matching, Podobne projekty, Rekomendowani, Targ, nowe CV).
 *
 * Trzy rzeczy, których ten widok pilnuje:
 *  - przegląd bazy startuje WYŁĄCZNIE kliknięciem (to kilkuminutowy skan);
 *  - awaria silnika dopasowań renderuje się jako awaria, nigdy jako „brak
 *    propozycji" — pustka czyta się jak „w bazie nikogo takiego nie ma";
 *  - pusty stan wisi na `isSuccess`, nie na `!isLoading` (przerwa między
 *    ponowieniami react-query wygląda jak pusta lista).
 */

import { useCallback, useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { FullCandidateSearchStatus } from "@/components/talent-radar/FullCandidateSearchStatus";
import { useCanVerifyRequirements } from "@/components/talent-radar/RequirementVerificationDialog";
import { apiErrorMessage } from "@/lib/api-error";
import { searchFailed, searchIsRunning } from "@/lib/full-candidate-search-api";
import {
  DEFAULT_PROPOSAL_FILTERS,
  type ProposalRateFilter,
  type ProposalSourceFilter,
  type ProposalViewFilters,
} from "@/lib/proposals-merge";
import { cn } from "@/lib/utils";

import { PeopleTable } from "./PeopleTable";
import { ProposalPanel } from "./ProposalPanel";
import { PROPOSAL_SOURCE_LABEL, type PersonRow, type ProposalSource } from "./types";
import { useCanAddToRecruitment } from "./useCanAddToRecruitment";
import { useJobProposals } from "./useJobProposals";

export interface ProposalsSegmentProps {
  jobId: number;
  budgetHourly: number | null;
  /** Osoby już w rekrutacji (z kanbana rodzica) — nie pojawiają się w propozycjach. */
  pipelineCandidateIds?: readonly number[];
  readOnly?: boolean;
  canOpenProfile?: boolean;
  onOpenManualSearch: () => void;
  onOpenQuickAdd: () => void;
  onWriteEmail?: (candidateId: number) => void;
  /** Narzędzia AI administratora dla aktywnej osoby (żyją w stronie rekrutacji). */
  renderAdminTools?: (candidateId: number) => ReactNode;
  /** `false`, gdy panel renderuje rodzic (wtedy słucha `onActiveCandidateChange`). */
  showPanel?: boolean;
  onActiveCandidateChange?: (candidateId: number | null) => void;
}

const SOURCE_PILLS: ProposalSourceFilter[] = [
  "all",
  ...(Object.keys(PROPOSAL_SOURCE_LABEL) as ProposalSource[]),
];

const RATE_OPTIONS: ReadonlyArray<readonly [ProposalRateFilter, string]> = [
  ["all", "Wszystkie"],
  ["in", "Mieści się"],
  ["over", "Powyżej"],
  ["unknown", "Brak danych"],
];

const pillClass = (active: boolean) =>
  cn(
    "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
    active
      ? "border-primary bg-primary text-primary-foreground"
      : "border-border bg-card text-foreground hover:bg-muted",
  );

function formatWhen(iso: string | null): string {
  if (!iso) return "data nieznana";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "data nieznana";
  return date.toLocaleString("pl-PL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function ProposalsSegment({
  jobId,
  budgetHourly,
  pipelineCandidateIds,
  readOnly = false,
  canOpenProfile = true,
  onOpenManualSearch,
  onOpenQuickAdd,
  onWriteEmail,
  renderAdminTools,
  showPanel = true,
  onActiveCandidateChange,
}: ProposalsSegmentProps) {
  const router = useRouter();
  const canAdd = useCanAddToRecruitment() && !readOnly;
  const canVerify = useCanVerifyRequirements() && !readOnly;
  const [filters, setFilters] = useState<ProposalViewFilters>(DEFAULT_PROPOSAL_FILTERS);
  const [criteriaOpen, setCriteriaOpen] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<Set<string | number>>(new Set());
  const [activeKey, setActiveKey] = useState<string | null>(null);

  const proposals = useJobProposals(jobId, { filters, budgetHourly, pipelineCandidateIds, readOnly });
  const { rows, entries, status, sourceCounts } = proposals;
  const run = status.run;
  const runData = run.data;
  const patch = useCallback(
    (next: Partial<ProposalViewFilters>) => setFilters((prev) => ({ ...prev, ...next })),
    [],
  );

  // Aktywny wiersz liczy się WZGLĘDEM widocznej listy: odfiltrowana osoba nie
  // może zostać w panelu bez podświetlonego wiersza.
  const activeEntry = useMemo(
    () => entries.find((e) => e.row.key === activeKey) ?? entries[0] ?? null,
    [entries, activeKey],
  );
  const changeActive = useCallback(
    (row: PersonRow) => {
      setActiveKey(row.key);
      onActiveCandidateChange?.(row.candidateId);
    },
    [onActiveCandidateChange],
  );
  // Akcje zbiorcze działają tylko na zaznaczonych WIDOCZNYCH po filtrach.
  const selectedIds = useMemo(
    () => rows.filter((r) => selectedKeys.has(r.key)).map((r) => r.candidateId),
    [rows, selectedKeys],
  );
  const clearSelection = () => setSelectedKeys(new Set());

  const skillOptions = useMemo(() => {
    if (runData?.criteria?.must?.length) return runData.criteria.must;
    const seen = new Set<string>();
    for (const e of entries) for (const r of e.detail.requirements) if (r.level === "must") seen.add(r.label);
    return Array.from(seen).slice(0, 12);
  }, [runData, entries]);

  const busy = proposals.adding || proposals.dismissing || proposals.shortlisting;
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (!activeEntry || !canAdd || busy || event.metaKey || event.ctrlKey || event.altKey) return;
    if (target.closest("input, textarea, select, [contenteditable='true'], [role='dialog']")) return;
    const key = event.key.toLowerCase();
    if (key === "d" && activeEntry.detail.eligibility?.assignment_allowed !== false) {
      event.preventDefault();
      proposals.addToJob([activeEntry.row.candidateId]);
    } else if (key === "p") {
      event.preventDefault();
      proposals.dismiss([activeEntry.row.candidateId]);
    }
  };

  const runFinished = !!runData && !searchIsRunning(runData.state) && !searchFailed(runData.state);
  const filtersActive = JSON.stringify(filters) !== JSON.stringify(DEFAULT_PROPOSAL_FILTERS);

  // ── Pusty stan: cztery różne zdania, nigdy jedno „brak propozycji" ────────
  let empty: ReactNode = null;
  if (rows.length === 0) {
    if (status.inbox.isError) {
      empty = (
        <div role="alert" className="space-y-2">
          <p>Nie udało się wczytać propozycji: {apiErrorMessage(status.inbox.error, "błąd serwera")}.</p>
          <Button variant="outline" size="sm" onClick={status.inbox.retry}>Spróbuj ponownie</Button>
        </div>
      );
    } else if (status.engineDegraded) {
      empty = (
        <p role="alert">
          Silnik dopasowań jest chwilowo niedostępny, więc nie wiemy, kto pasuje do tej rekrutacji. To NIE znaczy,
          że w bazie nikogo nie ma — spróbuj ponownie za kilka minut albo użyj „Szukaj ręcznie".
        </p>
      );
    } else if (run.running) {
      empty = <p role="status">Przegląd bazy trwa — propozycje pojawią się po jego zakończeniu.</p>;
    } else if (status.inbox.isSuccess && proposals.totalBeforeFilters > 0) {
      empty = (
        <div className="space-y-2">
          <p>Żadna propozycja nie pasuje do ustawionych filtrów.</p>
          <Button variant="outline" size="sm" onClick={() => setFilters(DEFAULT_PROPOSAL_FILTERS)}>Wyczyść filtry</Button>
        </div>
      );
    } else if (status.inbox.isSuccess && runData && searchFailed(runData.state)) {
      empty = <p>Przegląd bazy został przerwany — uruchom go ponownie, żeby zobaczyć propozycje.</p>;
    } else if (status.inbox.isSuccess && runFinished) {
      empty = (
        <p>
          Przegląd bazy nie znalazł nikogo spoza rekrutacji, kto przeszedłby filtry. Przyczyny wykluczeń są
          w podsumowaniu przeglądu powyżej.
        </p>
      );
    } else if (status.inbox.isSuccess && !run.runId && !status.latestRun) {
      empty = (
        <div className="space-y-2">
          <p>Tej rekrutacji nie przeglądano jeszcze pod kątem całej bazy.</p>
          {!readOnly && <Button size="sm" loading={run.starting} onClick={status.startRun}>Uruchom przegląd bazy</Button>}
        </div>
      );
    } else if (status.inbox.isSuccess) {
      empty = <p>Wszystkie propozycje zostały już dodane do rekrutacji albo pominięte. Nowe pojawią się z nowymi CV i po kolejnym przeglądzie.</p>;
    }
  }

  const footer = (
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-semibold">Zaznaczono {selectedIds.length}</span>
      {canAdd && (
        <>
          <Button size="sm" variant="outline" disabled={busy || selectedIds.length === 0} onClick={() => { proposals.addToJob(selectedIds); clearSelection(); }}>
            Dodaj do rekrutacji
          </Button>
          <Button size="sm" variant="outline" disabled={busy || selectedIds.length === 0} onClick={() => { proposals.dismiss(selectedIds); clearSelection(); }}>
            Pomiń
          </Button>
          <Button size="sm" variant="outline" disabled={busy || selectedIds.length === 0} onClick={() => { proposals.addToShortlist(selectedIds); clearSelection(); }}>
            Do shortlisty
          </Button>
        </>
      )}
      <Button
        size="sm"
        variant="outline"
        disabled={selectedIds.length < 2}
        onClick={() => router.push(`/candidates/compare?ids=${encodeURIComponent(selectedIds.join(","))}&job=${jobId}`)}
      >
        Porównaj
      </Button>
      <span className="ml-auto text-xs opacity-80">
        {rows.length} {filtersActive ? `z ${proposals.totalBeforeFilters} ` : ""}propozycji
        {status.inbox.hidden > 0 ? ` · ukryto ${status.inbox.hidden} (globalna czarna lista)` : ""}
      </span>
    </div>
  );

  return (
    <div className="flex min-w-0 flex-col gap-3" onKeyDown={onKeyDown}>
      {/* ── Pasek stanu przeglądu bazy ───────────────────────────────────── */}
      <section aria-label="Przegląd bazy" className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <p className="mr-auto text-sm text-muted-foreground">
            {status.latestRun
              ? `Ostatni przegląd: ${formatWhen(status.latestRun.completed_at)} · ${status.latestRun.origin === "auto" ? "automatyczny" : status.latestRun.own ? "Twój" : "ręczny"}${status.latestRun.state === "partial" ? " · niepełny" : ""}`
              : "Ostatni przegląd: jeszcze nie było"}
          </p>
          {!readOnly && (
            <Button size="sm" loading={run.starting} disabled={run.running} onClick={status.startRun}>
              {run.runId || status.latestRun ? "Uruchom ponownie" : "Przeszukaj całą bazę"}
            </Button>
          )}
          {!readOnly && (
            <Button size="sm" variant="outline" loading={status.recommendations.regenerating} disabled={status.recommendations.pending} onClick={status.recommendations.regenerate}>
              Odśwież rekomendacje
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={onOpenManualSearch}>Szukaj ręcznie</Button>
          {!readOnly && <Button size="sm" variant="outline" onClick={onOpenQuickAdd}>Dodaj po nazwisku</Button>}
        </div>

        {status.engineDegraded && (
          <div role="alert" className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
            Silnik dopasowań AI jest chwilowo niedostępny. Lista poniżej może być niepełna, a brak liczby w kolumnie
            „Dop." znaczy „nie policzono", nie „nie pasuje".
          </div>
        )}

        {/* Chwilowy błąd odczytu w trakcie skanu nie chowa postępu — skan trwa na serwerze. */}
        {run.error != null && (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-warning/40 bg-warning-muted p-3 text-sm text-warning-muted-foreground">
            <span>
              {runData && searchIsRunning(runData.state) && !run.needsNewRun
                ? `Chwilowo nie udało się odświeżyć postępu: ${apiErrorMessage(run.error, "błąd sieci")}. Przegląd trwa dalej — ponawiamy automatycznie.`
                : `Nie udało się odczytać przeglądu bazy: ${apiErrorMessage(run.error, "błąd serwera")}`}
            </span>
            {!readOnly && (
              <Button size="sm" variant="outline" onClick={status.retryRun}>
                {run.needsNewRun ? "Uruchom ponownie" : "Spróbuj ponownie"}
              </Button>
            )}
          </div>
        )}
        {runData && (run.error == null || searchIsRunning(runData.state)) && (
          <FullCandidateSearchStatus
            data={runData}
            offset={run.offset}
            onPage={run.setOffset}
            fetching={run.fetching}
            onRestart={readOnly ? undefined : status.startRun}
            restarting={run.running}
          />
        )}
        {!runData && run.loading && <p role="status" className="text-sm text-muted-foreground">Wczytuję przegląd całej bazy…</p>}
        {status.recommendations.stale && (
          <p className="text-xs text-warning-muted-foreground">Wymagania rekrutacji zmieniły się od ostatnich rekomendacji — odśwież je.</p>
        )}
        {status.similar.hiddenIneligible > 0 && (
          <p className="text-xs text-muted-foreground">Podobne projekty: ukryto {status.similar.hiddenIneligible} według reguł dopuszczalności.</p>
        )}
      </section>

      {/* ── Filtry widoku ────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Źródło propozycji">
        {SOURCE_PILLS.map((source) => (
          <button key={source} type="button" aria-pressed={filters.source === source} className={pillClass(filters.source === source)} onClick={() => patch({ source })}>
            {source === "all" ? "Wszystkie" : PROPOSAL_SOURCE_LABEL[source]}
            <span className="tabular-nums opacity-80">{sourceCounts[source] ?? 0}</span>
          </button>
        ))}
        <span aria-hidden className="mx-1 h-5 w-px bg-border" />
        <button type="button" aria-pressed={filters.onlyNew} className={pillClass(filters.onlyNew)} onClick={() => patch({ onlyNew: !filters.onlyNew })}>Tylko nowe</button>
        <button type="button" aria-pressed={filters.inBudget} className={pillClass(filters.inBudget)} onClick={() => patch({ inBudget: !filters.inBudget })}>W budżecie</button>
        <button type="button" aria-pressed={filters.availableNow} className={pillClass(filters.availableNow)} onClick={() => patch({ availableNow: !filters.availableNow })}>Dostępni od razu</button>
        <button type="button" aria-expanded={criteriaOpen} aria-controls={`proposal-criteria-${jobId}`} className="ml-auto text-xs font-medium text-primary hover:underline" onClick={() => setCriteriaOpen((v) => !v)}>
          Dopasuj kryteria
        </button>
      </div>

      {criteriaOpen && (
        <div id={`proposal-criteria-${jobId}`} className="grid gap-4 rounded-xl border border-border bg-card p-4 text-sm md:grid-cols-2 xl:grid-cols-4">
          <div className="space-y-1.5">
            <label htmlFor={`proposal-min-score-${jobId}`} className="flex justify-between text-[11px] font-medium text-muted-foreground">
              <span>Próg dopasowania</span>
              <span className="tabular-nums text-foreground">≥ {filters.minScore}</span>
            </label>
            <input id={`proposal-min-score-${jobId}`} type="range" min={0} max={100} step={5} value={filters.minScore} onChange={(e) => patch({ minScore: Number(e.target.value) })} className="w-full accent-primary" />
            <p className="text-[11px] text-muted-foreground">Osoby bez policzonego dopasowania zostają na liście.</p>
          </div>
          <div className="space-y-1.5" role="group" aria-label="Stawka wobec budżetu">
            <div className="text-[11px] font-medium text-muted-foreground">Stawka wobec budżetu</div>
            <div className="flex flex-wrap gap-1">
              {RATE_OPTIONS.map(([value, label]) => (
                <button key={value} type="button" aria-pressed={filters.rate === value} className={pillClass(filters.rate === value)} onClick={() => patch({ rate: value })}>{label}</button>
              ))}
            </div>
          </div>
          <div className="space-y-1.5">
            <label htmlFor={`proposal-location-${jobId}`} className="text-[11px] font-medium text-muted-foreground">Lokalizacja</label>
            <input id={`proposal-location-${jobId}`} type="text" value={filters.location} onChange={(e) => patch({ location: e.target.value })} placeholder="np. Warszawa" className="h-8 w-full rounded-md border border-border bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" />
          </div>
          <div className="space-y-1.5" role="group" aria-label="Wymaganie">
            <div className="text-[11px] font-medium text-muted-foreground">Musi mieć</div>
            {skillOptions.length === 0 ? (
              <p className="text-[11px] text-muted-foreground">Brak wymagań — uzupełnij zlecenie.</p>
            ) : (
              <div className="flex flex-wrap gap-1">
                {skillOptions.map((skill) => (
                  <button key={skill} type="button" aria-pressed={filters.skill === skill} className={pillClass(filters.skill === skill)} onClick={() => patch({ skill: filters.skill === skill ? null : skill })}>{skill}</button>
                ))}
              </div>
            )}
          </div>
          {filtersActive && (
            <button type="button" className="justify-self-start text-xs text-primary hover:underline" onClick={() => setFilters(DEFAULT_PROPOSAL_FILTERS)}>Wyczyść filtry</button>
          )}
        </div>
      )}

      {/* ── Tabela + panel ───────────────────────────────────────────────── */}
      <div className="flex min-w-0 items-start gap-4">
        <div className="min-w-0 flex-1 space-y-2">
          <PeopleTable
            variant="proposal"
            jobId={jobId}
            rows={rows}
            selectedKeys={selectedKeys}
            onSelectionChange={setSelectedKeys}
            activeKey={activeEntry?.row.key ?? null}
            onActiveChange={changeActive}
            footer={footer}
            loading={status.inbox.isLoading && rows.length === 0}
            empty={empty}
            readOnly={readOnly}
          />
          {status.inbox.hasMore && (
            <Button variant="outline" size="sm" loading={status.inbox.loadingMore} onClick={status.inbox.loadMore}>
              Pokaż więcej propozycji
            </Button>
          )}
        </div>
        {showPanel && (
          <ProposalPanel
            jobId={jobId}
            entry={activeEntry}
            budgetHourly={budgetHourly}
            readOnly={readOnly}
            canAdd={canAdd}
            canVerify={canVerify}
            canOpenProfile={canOpenProfile}
            busy={busy}
            onAdd={(id) => proposals.addToJob([id])}
            onShortlist={(id) => proposals.addToShortlist([id])}
            onDismiss={(id) => proposals.dismiss([id])}
            onWriteEmail={onWriteEmail}
            onVerified={() => { if (run.runId) void run.refresh(); }}
            adminTools={activeEntry && renderAdminTools ? renderAdminTools(activeEntry.row.candidateId) : undefined}
          />
        )}
      </div>
    </div>
  );
}
