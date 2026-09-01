"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Award, Loader2, Medal, Trophy } from "lucide-react";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import {
  COMPETITION_TYPES,
  COMPETITION_TYPE_LABEL,
  formatMonthPl,
  racesApi,
  type CompetitionHistoryResponse,
  type CompetitionTypeKey,
  type HallOfFameResponse,
} from "@/lib/insights-races-api";
import { count, money } from "./InsightsFormat";
import { SectionError } from "./_shared";

/**
 * Hall of Fame — dwie różne rzeczy, które w DynaReporterze siedziały pod jedną
 * ikoną 🏅 i dlatego bywały mylone:
 *
 * 1. **Wszech czasów** — żywy ranking po placementach z całej historii
 *    (`/api/competitions/current?type=hall_of_fame`). Zmienia się z każdym
 *    zatrudnieniem.
 * 2. **Zamknięte okresy** — podia ZAMROŻONE w `competition_winners`
 *    (`/api/competitions/history`). Nie zmieniają się nigdy, bo to zapis
 *    tego, komu przyznano nagrodę.
 *
 * Trzymanie ich w jednej sekcji, ale w dwóch osobno podpisanych blokach, jest
 * świadome: liczba obok nazwiska znaczy w każdym z nich co innego, a wspólny
 * nagłówek bez tego rozróżnienia sugerowałby, że pierwsza lista jest listą
 * zwycięzców. Nie jest — zwycięzcą zostaje się przez zamknięcie okresu.
 *
 * Każdy blok ma WŁASNE zapytanie i własny stan widoku. Awaria historii nie może
 * wygasić rankingu all-time, a pusta historia nie może wyglądać jak awaria:
 * `competition_winners` zapełnia dopiero `POST /api/competitions/freeze`, więc
 * „brak zamkniętych okresów" jest tu normalnym, spodziewanym stanem.
 */

const MEDAL: Record<number, { emoji: string; className: string }> = {
  1: { emoji: "🥇", className: "text-warning" },
  2: { emoji: "🥈", className: "text-muted-foreground" },
  3: { emoji: "🥉", className: "text-warning-muted-foreground" },
};

function RankBadge({ rank }: { rank: number }) {
  const medal = MEDAL[rank];
  return (
    <span
      className={cn(
        "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold",
        medal ? "bg-muted" : "bg-muted text-muted-foreground",
      )}
      aria-hidden="true"
    >
      {medal ? medal.emoji : rank}
    </span>
  );
}

/** Etykieta okresu: `2026-08` → „Sierpień 2026", `Q3 2026` → bez zmian. */
function periodLabel(period: string): string {
  return formatMonthPl(period);
}

// ── Blok 1: ranking all-time ────────────────────────────────────────────

function AllTimeBlock() {
  const { data, isPending, isSuccess, isError, error, refetch } =
    useQuery<HallOfFameResponse>({
      queryKey: ["insights", "hall-of-fame", "all-time"],
      queryFn: () => racesApi.hallOfFameAllTime(),
      staleTime: 10 * 60 * 1000,
    });

  const ranking = data?.full_ranking ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: ranking.length === 0,
  });

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <h3 className="flex items-center gap-2 text-sm font-bold text-foreground">
        <Trophy className="h-4 w-4 text-warning" aria-hidden="true" />
        Wszech czasów — placementy
      </h3>
      {/* Podpis MUSI unieść trzy rzeczy, bo bez nich lista kłamie
          w sposób niewidoczny:

          1. To TOP 5, nie pełny ranking (`hall_of_fame(db, limit=5)`).
             Lista bez tej informacji czyta się jako komplet, a osoba na
             szóstym miejscu widzi, że „jej nie ma w rankingu".
          2. Poza rankingiem stoi realny kawał dorobku — konta
             administracyjne, które domykają pipeline masowo. Liczba przychodzi
             z serwera (`scope`), a nie jest tu wpisana: wpisana rozjechałaby
             się przy pierwszej zmianie w bazie.
          3. Ten ranking liczy TAK SAMO jak „Analiza placementów"
             (definicja D2), ale INACZEJ niż „Wyścig Placementów" obok, który
             wypłaca nagrodę i dlatego został przy atrybucji konkursowej.
             Dwie sąsiadujące tabele z inną regułą muszą to powiedzieć, bo
             inaczej różnica wygląda na błąd jednej z nich. */}
      <p className="mt-0.5 text-xs text-muted-foreground">
        Ranking żywy, <strong>TOP 5</strong>, liczony z całej historii. To NIE
        jest lista zwycięzców — nagrodę przyznaje dopiero zamknięcie okresu.
      </p>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Placement liczony <strong>tak samo jak w „Analizie placementów"</strong>{" "}
        — pierwsze wejście pary (kandydat, rekrutacja) na etap „Zatrudniony",
        przypisane osobie, która ten etap przesunęła. „Wyścig Placementów" obok
        liczy <strong>inaczej</strong> (atrybucja konkursowa), bo wypłaca
        nagrodę.
      </p>

      <div className="mt-3">
        {viewState === "loading" ? (
          <div className="flex items-center justify-center py-8">
            <Loader2
              className="h-5 w-5 animate-spin text-muted-foreground"
              aria-label="Ładowanie"
            />
          </div>
        ) : isBlockingViewState(viewState) ? (
          <SectionError
            label="Hall of Fame — wszech czasów"
            error={error}
            onRetry={() => void refetch()}
          />
        ) : viewState === "empty" ? (
          <p className="py-6 text-center text-xs text-muted-foreground">
            Nikt nie ma jeszcze odnotowanego placementu. To pusty ranking, nie
            błąd pobierania.
          </p>
        ) : (
          <ol className="space-y-2">
            {ranking.map((entry, index) => (
              <li
                key={entry.user_id}
                className="flex items-center gap-3 rounded-lg border border-border px-3 py-2"
              >
                <RankBadge rank={index + 1} />
                <span className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
                  {entry.name}
                  {/* Ranking WSZECH CZASÓW zostawia byłych pracowników —
                      odejście z firmy nie cofa tego, co ktoś osiągnął — ale
                      wiersz bez chipa sugerowałby, że ta osoba wciąż tu
                      pracuje. Ta sama reguła co w tabeli „Performance per
                      osoba" dwie sekcje wyżej. */}
                  {entry.is_active === false && (
                    <span className="ml-2 rounded-full border border-border bg-muted px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                      były pracownik
                    </span>
                  )}
                </span>
                <span className="shrink-0 text-sm font-extrabold text-foreground">
                  {count(entry.metric_value)}
                  <span className="ml-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    plac.
                  </span>
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>

      {/* Ile dorobku stoi POZA rankingiem. Bez tego zdania TOP 5 czyta się
          jako całość bazy, a po przejściu na atrybucję D2 poza rankingiem
          zostaje ponad połowa placementów — domkniętych przez konta
          administracyjne, które nie rekrutują. Liczby z serwera; gdy nic nie
          odpada, zdanie się nie renderuje (zero to nie jest informacja). */}
      {data?.scope && data.scope.outside_role_placements > 0 && (
        <p className="mt-3 border-t border-border/60 pt-2 text-[11px] text-muted-foreground">
          W rankingu {count(data.scope.ranked_placements)} placementów ról
          rekrutacyjnych i delivery. Poza nim:{" "}
          <strong>{count(data.scope.outside_role_placements)}</strong>{" "}
          domkniętych przez konta administracyjne
          {data.scope.unattributed_placements > 0 && (
            <> i {count(data.scope.unattributed_placements)} bez autora</>
          )}
          .
        </p>
      )}
    </div>
  );
}

// ── Blok 2: zamrożone podia ─────────────────────────────────────────────

function FrozenPeriodsBlock() {
  const [type, setType] = useState<CompetitionTypeKey>(
    "monthly_recommendations",
  );
  const { data, isPending, isSuccess, isError, error, refetch } =
    useQuery<CompetitionHistoryResponse>({
      queryKey: ["insights", "hall-of-fame", "history", type],
      queryFn: () => racesApi.history(type),
      staleTime: 10 * 60 * 1000,
    });

  const periods = data?.periods ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: periods.length === 0,
  });

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <h3 className="flex items-center gap-2 text-sm font-bold text-foreground">
        <Award className="h-4 w-4 text-primary" aria-hidden="true" />
        Zamknięte okresy — zwycięzcy
      </h3>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Podium zamrożone w chwili zamknięcia okresu. Późniejsze zmiany w danych
        już go nie ruszają.
      </p>

      <div
        className="mt-3 flex flex-wrap gap-1.5"
        role="tablist"
        aria-label="Konkurs"
      >
        {COMPETITION_TYPES.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={key === type}
            onClick={() => setType(key)}
            className={cn(
              "rounded-md border px-2.5 py-1 text-xs font-medium",
              key === type
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border text-muted-foreground hover:bg-accent",
            )}
          >
            {COMPETITION_TYPE_LABEL[key]}
          </button>
        ))}
      </div>

      <div className="mt-3">
        {viewState === "loading" ? (
          <div className="flex items-center justify-center py-8">
            <Loader2
              className="h-5 w-5 animate-spin text-muted-foreground"
              aria-label="Ładowanie"
            />
          </div>
        ) : isBlockingViewState(viewState) ? (
          <SectionError
            label="Hall of Fame — zamknięte okresy"
            error={error}
            onRetry={() => void refetch()}
          />
        ) : viewState === "empty" ? (
          <p className="py-6 text-center text-xs text-muted-foreground">
            Żaden okres tego konkursu nie został jeszcze zamknięty. Podium
            trafia tutaj dopiero po zamknięciu okresu przez administratora —
            pusto tu znaczy „nikomu jeszcze nie przyznano nagrody", a nie „nikt
            nie wygrał".
          </p>
        ) : (
          <ul className="space-y-3">
            {periods.map((entry) => (
              <li key={entry.period}>
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  {periodLabel(entry.period)}
                </p>
                <ol className="mt-1 space-y-1.5">
                  {entry.top3.map((winner) => (
                    <li
                      key={`${entry.period}:${winner.user_id}:${winner.rank}`}
                      className="flex items-center gap-3 rounded-lg border border-border px-3 py-2"
                    >
                      <RankBadge rank={winner.rank} />
                      <span className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
                        {winner.user_name}
                      </span>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {count(winner.metric_value)}
                      </span>
                      {/* `null` nagrody renderujemy jako „—": zero PLN byłoby
                          werdyktem „nagrody nie było", a to inna informacja. */}
                      <span className="shrink-0 text-xs font-bold text-success-muted-foreground">
                        {money(winner.prize_pln)}
                      </span>
                    </li>
                  ))}
                </ol>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function InsightsHallOfFame() {
  return (
    <section aria-label="Hall of Fame" className="space-y-3">
      <div className="flex items-center gap-2">
        <Medal className="h-5 w-5 text-warning" aria-hidden="true" />
        <h2 className="text-base font-bold text-foreground">Hall of Fame</h2>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <AllTimeBlock />
        <FrozenPeriodsBlock />
      </div>
    </section>
  );
}
