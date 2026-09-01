"use client";

import { useQuery } from "@tanstack/react-query";
import { GraduationCap, Loader2, TrendingDown } from "lucide-react";
import {
  insightsApi,
  type SeniorityEntry,
  type SeniorityLevel,
  type SeniorityJournalStatus,
  type SeniorityRegression,
  type SeniorityResponse,
} from "@/lib/insights-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { NotAssessable, SectionError } from "./_shared";

const LEVEL_LABEL: Record<SeniorityLevel, string> = {
  junior: "Junior",
  senior: "Senior",
  expert: "Expert",
};

const LEVEL_CLASS: Record<SeniorityLevel, string> = {
  junior: "bg-muted text-muted-foreground border-border",
  senior: "bg-primary/10 text-primary border-primary/20",
  // Tokeny zamiast `amber-*` — te ostatnie nie znają palet soft/kids,
  // a plakietka „expert" stoi na tym samym ekranie co stokenizowane
  // bursztyny wyścigów i ostrzeżeń.
  expert: "bg-warning-muted text-warning-muted-foreground border-warning/25",
};

const ROLE_LABEL: Record<string, string> = {
  sourcer: "Sourcer",
  tac: "TAC",
  recruiter: "Rekruter",
};

/** Polska odmiana po liczbie — „1 placement / 2 placementy / 5 placementów". */
function placementsPl(n: number): string {
  const abs = Math.abs(n);
  if (abs === 1) return "1 placement";
  const last = abs % 10;
  const lastTwo = abs % 100;
  const few = last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14);
  return `${n} ${few ? "placementy" : "placementów"}`;
}

/** Polska odmiana po liczbie — „1 miesiąc / 2 miesiące / 5 miesięcy". */
function monthsPl(n: number): string {
  const abs = Math.abs(n);
  if (abs === 1) return "1 miesiąc";
  const last = abs % 10;
  const lastTwo = abs % 100;
  const few = last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14);
  return `${n} ${few ? "miesiące" : "miesięcy"}`;
}

/**
 * Reguła awansu WYPISANA SŁOWAMI.
 *
 * Sam pasek postępu nie mówi, ile trzeba — a osoba oceniana na tym ekranie ma
 * prawo znać regułę, zamiast odgadywać ją z szerokości paska.
 */
function ruleSentence(placements: number, months: number): string {
  if (placements <= 0 || months <= 0) return "reguła wyłączona w konfiguracji";
  return `${placementsPl(placements)} w ${monthsPl(months)}`;
}

/**
 * Każdy poziom ma DWIE alternatywne reguły połączone przez LUB. Opis wyłącznie
 * podstawowej kazałby ludziom mierzyć się do progu, którego nie muszą
 * osiągnąć — a to jest komunikat o awansie, więc ma być prawdziwy.
 * Reguła wyłączona w konfiguracji znika z opisu zamiast krzyczeć „wyłączona":
 * jedna działająca reguła to poprawny, celowy stan.
 */
function levelRuleSentence(
  placements: number,
  months: number,
  altPlacements: number,
  altMonths: number,
): string {
  const parts = [
    [placements, months] as const,
    [altPlacements, altMonths] as const,
  ]
    .filter(([p, m]) => p > 0 && m > 0)
    .map(([p, m]) => ruleSentence(p, m));
  if (parts.length === 0) return "reguła wyłączona w konfiguracji";
  return parts.join(" lub ");
}

function ProgressBar({ pct }: { pct: number | null }) {
  // `null` to brak progu, nie zero. Pasek o zerowej szerokości czytałby się
  // jako „policzone i wyszło zero”, czyli jako ocena.
  if (pct === null) {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 rounded-full bg-muted overflow-hidden">
        <div
          className="h-2 rounded-full bg-primary transition-all"
          // Szerokość PASKA jest przycięta do 100% — inaczej wyjeżdża poza
          // komórkę. Sama LICZBA obok nie jest przycięta, więc przekroczenie
          // progu zostaje widoczne.
          style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
        />
      </div>
      <span className="tabular-nums text-xs text-muted-foreground">
        {pct.toFixed(0)}%
      </span>
    </div>
  );
}

function SeniorityTable({ data }: { data: SeniorityResponse }) {
  // Osoby z zerem PRZYPISANEJ historii wychodzą z tabeli na osobną listę.
  // „Junior · 0/6” dla kogoś, czyich placementów po prostu nie ma w NEXUSIE,
  // czyta się jak ocena wyniku, a jest stwierdzeniem o brakujących danych.
  const assessable: SeniorityEntry[] = [];
  const noData: SeniorityEntry[] = [];
  for (const entry of data.entries) {
    (entry.first_placement_month === null ? noData : assessable).push(entry);
  }

  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs uppercase text-muted-foreground border-b border-border">
              <th className="text-left font-medium py-2">Osoba</th>
              <th className="text-left font-medium py-2">Poziom</th>
              <th className="text-right font-medium py-2">Placementy</th>
              <th className="text-right font-medium py-2">
                Okno seniora ({data.window.senior.months} mc)
              </th>
              <th className="text-right font-medium py-2">
                Okno eksperta ({data.window.expert.months} mc)
              </th>
              <th className="text-right font-medium py-2">Do awansu</th>
              <th className="text-left font-medium py-2 pl-4">Postęp</th>
            </tr>
          </thead>
          <tbody>
            {assessable.map((e) => (
              <tr key={e.user_id} className="border-b border-border/50">
                <td className="py-2 text-foreground">
                  {e.name}
                  <span className="ml-2 text-xs text-muted-foreground">
                    {ROLE_LABEL[e.role] ?? e.role}
                  </span>
                </td>
                <td className="py-2">
                  <span
                    className={cn(
                      "inline-block rounded-full border px-2 py-0.5 text-xs font-medium",
                      LEVEL_CLASS[e.level],
                    )}
                  >
                    {LEVEL_LABEL[e.level]}
                  </span>
                  {/* Data awansu na seniora jest KOTWICĄ zegara eksperta —
                      do wyższego poziomu liczą się wyłącznie placementy od
                      tego miesiąca w górę. Bez niej kolumna „w oknie eksperta"
                      wygląda na zaniżoną wobec sumy obok. */}
                  {e.senior_since && (
                    <span className="mt-0.5 block text-[11px] text-muted-foreground">
                      {e.expert_since
                        ? `expert od ${e.expert_since}`
                        : `senior od ${e.senior_since}`}
                    </span>
                  )}
                </td>
                <td className="py-2 text-right tabular-nums">
                  {e.total_placements}
                </td>
                <td className="py-2 text-right tabular-nums">
                  {e.placements_in_senior_window}
                </td>
                <td className="py-2 text-right tabular-nums">
                  {e.placements_in_expert_window}
                </td>
                <td className="py-2 text-right tabular-nums">
                  {e.placements_to_next_level ?? "—"}
                </td>
                <td className="py-2 pl-4">
                  <ProgressBar pct={e.progress_pct} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <NotAssessable
        rows={noData.map((e) => ({
          id: e.user_id,
          name: e.name,
          reason: "no_data",
        }))}
        title="Bez przypisanych placementów"
        footnote={
          data.coverage.unattributed_placements > 0 ||
          data.coverage.outside_pool_placements > 0 ? (
            <>
              Poza tabelą zostaje{" "}
              {placementsPl(data.coverage.unattributed_placements)} bez
              przypisanego operatora oraz{" "}
              {placementsPl(data.coverage.outside_pool_placements)} przypisanych
              do kont spoza puli (inne role i konta założone przez import
              Traffita dla operatorów bez odpowiednika w NEXUSIE).
            </>
          ) : null
        }
      />
    </>
  );
}

/**
 * Ścieżka rozwoju — poziom junior / senior / expert z liczby placementów (D6).
 *
 * Zastępuje `dr_user_seniority`, którego writer jest martwy za 409, a czytelnik
 * ukrywał każdego bez zaseedowanego wiersza — czyli pokazywał podzbiór zespołu
 * jako całość.
 *
 * Dwie rzeczy, które ta sekcja MUSI mówić wprost, bo inaczej liczby kłamią:
 *
 * 1. **Reguła awansu słowami** („6 placementów w 6 miesięcy”), nie tylko pasek.
 * 2. **Poziom nie spada.** Okno służy do awansu, nie do cofania — bez tego
 *    zdania pusty licznik bieżącego okna przy poziomie „Senior” wygląda na
 *    błąd, a jest poprawną odpowiedzią.
 */
/**
 * Osoby, którym poziom SPADŁ między obserwacjami dziennika.
 *
 * Musi stać NAD tabelą, bo podważa to, co jest pod nim: jeżeli komuś zabrano
 * placementy, cała kolumna „poziom” opisuje inny stan świata niż wczoraj.
 * Sekcja mówi obok, że „poziom raz osiągnięty zostaje” — spadek jest więc
 * sprzeczny z regułą, którą czytelnik właśnie przeczytał, i nie może być
 * schowany w rozwijanym szczególe.
 *
 * Nie proponuje żadnej akcji, bo żadna nie jest tu poprawna automatycznie:
 * cofnięta atrybucja bywa POPRAWKĄ (import naprawił błędne przypisanie), a
 * bywa awarią. Rozstrzyga człowiek.
 */
function SeniorityRegressions({
  rows,
  journal,
}: {
  rows: SeniorityRegression[] | null;
  journal: SeniorityJournalStatus | null;
}) {
  // `null` = dziennika nie dało się odczytać. Cisza w tym miejscu czyta się
  // jako „nikomu nic nie spadło", więc niewiedza musi być NAPISANA.
  if (rows === null) {
    return (
      <div className="mb-4 rounded-lg border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
        Nie udało się sprawdzić, czy komuś spadł poziom — dziennik obserwacji
        jest chwilowo niedostępny. Poziomy w tabeli poniżej są policzone
        normalnie.
      </div>
    );
  }
  // Pusta lista NIE jest odpowiedzią, dopóki dziennik czegokolwiek nie
  // zaobserwował. Bez tego rozróżnienia zepsuta pętla dobowa w nieskończoność
  // wygląda jak „nikomu nic nie spadło”.
  if (journal && journal.last_observed_at === null) {
    return (
      <div className="mb-4 rounded-lg border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
        Dziennik poziomów nie wykonał jeszcze żadnej obserwacji, więc nie ma
        z czym porównać dzisiejszych poziomów. Spadek zostanie wykryty dopiero
        po pierwszym nocnym przebiegu.
      </div>
    );
  }
  if (rows.length === 0) return null;
  return (
    <div className="mb-4 rounded-lg border border-warning/25 bg-warning-muted p-3 text-warning-muted-foreground">
      <p className="flex items-center gap-2 text-xs font-semibold">
        <TrendingDown className="h-4 w-4 shrink-0" />
        {rows.length === 1
          ? "Jednej osobie spadł poziom"
          : `Spadek poziomu: ${rows.length} os.`}
      </p>
      <ul className="mt-2 space-y-1 text-xs">
        {rows.map((row) => (
          <li key={row.user_id}>
            <strong>{row.name}</strong>: {LEVEL_LABEL[row.previous_level ?? "junior"]}{" "}
            → {LEVEL_LABEL[row.level]}
            {row.previous_total_placements !== null && (
              <>
                {" "}
                ({row.previous_total_placements} → {row.total_placements}{" "}
                placementów)
              </>
            )}
            {row.observed_at && (
              <span className="text-warning-muted-foreground/80">
                {" "}
                · zauważone {row.observed_at.slice(0, 10)}
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[11px] leading-relaxed">
        Poziom nie spada z upływem czasu, więc spadek zawsze znaczy, że zmieniła
        się <strong>historia przypisań</strong> — najczęściej po imporcie, który
        przepisał zaległe zatrudnienia na inną osobę. To może być poprawka albo
        błąd; system nie zgaduje, która to sytuacja.
      </p>
    </div>
  );
}

export function InsightsSeniority() {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: ["insights", "recruitment", "seniority"],
    queryFn: () => insightsApi.seniority(),
  });

  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: (data?.entries.length ?? 0) === 0,
  });

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-xs">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2 mb-1">
        <GraduationCap className="w-5 h-5 text-primary" />
        Ścieżka rozwoju
        {data && (
          <span className="ml-auto text-xs text-muted-foreground font-normal">
            {data.totals.levels.expert} expert · {data.totals.levels.senior}{" "}
            senior · {data.totals.levels.junior} junior
          </span>
        )}
      </h2>

      {data && (
        <p className="text-xs text-muted-foreground mb-4">
          Awans na <strong>Seniora</strong>:{" "}
          {levelRuleSentence(
            data.thresholds.senior_placements,
            data.thresholds.senior_window_months,
            data.thresholds.senior_alt_placements,
            data.thresholds.senior_alt_window_months,
          )}
          . Awans na <strong>Eksperta</strong>:{" "}
          {levelRuleSentence(
            data.thresholds.expert_placements,
            data.thresholds.expert_window_months,
            data.thresholds.expert_alt_placements,
            data.thresholds.expert_alt_window_months,
          )}
          . Poziom raz osiągnięty <strong>zostaje</strong> — okno służy do
          awansu, nie do cofania, więc pusty licznik bieżącego okna przy wyższym
          poziomie jest poprawną odpowiedzią, a nie błędem.
        </p>
      )}

      {data && (
        <SeniorityRegressions
          rows={data.regressions ?? null}
          journal={data.journal ?? null}
        />
      )}

      {viewState === "loading" ? (
        <div className="py-8 flex items-center justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Ścieżka rozwoju"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          Brak osób w rolach sourcer / TAC / rekruter.
        </p>
      ) : data ? (
        <SeniorityTable data={data} />
      ) : null}

      {data && (
        <p className="mt-3 text-xs text-muted-foreground">
          Poziom jest liczony przy każdym odczycie z liczby placementów
          (pierwsze zatrudnienie na parę kandydat × rekrutacja), nie
          przechowywany. Zmienia się więc wtedy, gdy zmienia się historia
          przypisań — na przykład po imporcie zaległych danych — a nie tylko po
          nowym zatrudnieniu. Stan na {data.as_of}.
        </p>
      )}
    </section>
  );
}
