"use client";

import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Award, ChevronDown, ChevronRight, Loader2, Users } from "lucide-react";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { KpiCard, SectionError } from "./_shared";
import { count, DefinitionNote, pct } from "./InsightsFormat";

interface Props {
  period: InsightsPeriodParams;
}

/** Ile miesięcy wstecz pokazuje rozwinięty wiersz DL. */
const TREND_MONTHS = 6;

/**
 * Ranking Delivery Leadów na `/api/insights/delivery-leads`.
 *
 * Wchodzi w miejsce `DLRevenueLeaderboard.tsx`, który czytał
 * `/api/admin/clients-overview/by-dl` — endpoint na `FinanceReadUser`, czyli
 * pod D7 (każda zalogowana rola widzi /insights) kończący się dla większości
 * firmy czerwonym „Błąd ładowania leaderboardu DL.". Ta sekcja mierzy co
 * innego niż tamta: DOSTARCZANIE (zapytania, wakaty, placementy, hit ratio),
 * nie przychód lifetime per DL. Przychód per klient wraz z „Head DL" jest
 * w rankingu klientów obok; pełny widok pieniędzy per DL zostaje na swojej
 * własnej, finansowej powierzchni.
 *
 * Trzy rzeczy, które ta sekcja MUSI napisać na ekranie, bo inaczej liczby
 * kłamią przez przemilczenie:
 * 1. ranking obejmuje wyłącznie `body_leasing` — nie zsumuje się do lejka;
 * 2. otwarty pipeline to snapshot „na teraz", nie okno;
 * 3. hit ratio miesza kohorty (placementy w oknie ÷ zapytania z okna).
 */
export function InsightsDeliveryLeads({ period }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.deliveryLeads(period),
    queryFn: () => insightsBoardApi.deliveryLeads(period),
  });

  const rows = data?.per_dl ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: rows.length === 0,
  });

  const unattributed = data?.unattributed;
  const hasUnattributed =
    !!unattributed &&
    (unattributed.requests > 0 ||
      unattributed.placements > 0 ||
      unattributed.open_requests > 0);

  return (
    <section className="space-y-3">
      <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
        <Users className="h-5 w-5 text-primary" />
        Delivery Leadzi — dostarczanie
        {data && (
          <span className="ml-auto text-xs font-normal text-muted-foreground">
            Tylko rekrutacje typu {data.recruitment_type}
          </span>
        )}
      </h2>

      {viewState === "loading" ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Delivery Leadzi"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : !data ? null : (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <KpiCard
              label="Placementy"
              value={count(data.overall.total_placements)}
              sub={`${count(data.overall.total_requests)} zapytań · ${count(
                data.overall.total_vacancies,
              )} wakatów`}
              icon={Users}
              color="blue"
            />
            <KpiCard
              label="Hit ratio (agregat)"
              value={pct(data.overall.hit_ratio)}
              sub="Suma placementów ÷ suma zapytań"
              icon={Award}
              color="green"
            />
            <KpiCard
              label="Średnia po DL"
              value={pct(data.overall.avg_hit_ratio)}
              sub={`${count(data.overall.dl_with_hit_ratio)} z ${count(
                data.overall.dl_count,
              )} DL ma policzalny wskaźnik`}
              icon={Award}
              color="indigo"
            />
            <KpiCard
              label="Otwarty pipeline"
              value={count(data.overall.total_open_requests)}
              sub={`${count(
                data.overall.total_open_vacancies,
              )} wolnych wakatów — stan na teraz`}
              icon={Users}
              color="orange"
            />
          </div>

          <DefinitionNote>
            Hit ratio miesza kohorty: licznik to placementy OSIĄGNIĘTE w tym
            oknie, mianownik to zapytania UTWORZONE w tym oknie — placement
            zwykle domyka zapytanie starsze niż okno. Dlatego wynik potrafi
            przekroczyć 100% i nie jest to błąd.
          </DefinitionNote>
          <DefinitionNote>
            Kolumny „Otwarte” to snapshot na teraz, nie okno — otwarte zapytanie
            nie ma daty zamknięcia, więc przycięcie go do okresu nie opisywałoby
            niczego.
          </DefinitionNote>

          {viewState === "empty" ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              Brak Delivery Leadów z aktywnością w tym oknie.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead className="border-b border-border bg-muted/50">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">
                      Delivery Lead
                    </th>
                    <th className="px-3 py-2 text-right font-medium">
                      Zapytania
                    </th>
                    <th className="px-3 py-2 text-right font-medium">Wakaty</th>
                    <th className="px-3 py-2 text-right font-medium">
                      Placementy
                    </th>
                    <th className="px-3 py-2 text-right font-medium">
                      Hit ratio
                    </th>
                    <th className="px-3 py-2 text-right font-medium">
                      Fill rate
                    </th>
                    <th className="px-3 py-2 text-right font-medium">
                      Otwarte (teraz)
                    </th>
                    <th className="px-3 py-2 text-center font-medium">Cel</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const open = expanded === r.user_id;
                    return (
                      <Fragment key={r.user_id}>
                        <tr className="border-b border-border hover:bg-accent/30">
                          <td className="px-3 py-2">
                            <button
                              type="button"
                              onClick={() =>
                                setExpanded(open ? null : r.user_id)
                              }
                              aria-expanded={open}
                              className="flex items-center gap-1 text-left font-medium hover:text-primary"
                            >
                              {open ? (
                                <ChevronDown className="h-3.5 w-3.5" />
                              ) : (
                                <ChevronRight className="h-3.5 w-3.5" />
                              )}
                              {r.name}
                            </button>
                            {/* Nie filtrujemy po `is_active` — konta DL bywają
                                nieaktywne, a historia firmy nie może się
                                zmieniać od przestawienia flagi konta. */}
                            {!r.is_active && (
                              <span className="ml-1 text-xs text-muted-foreground">
                                (konto nieaktywne)
                              </span>
                            )}
                            {r.clients.length > 0 && (
                              <div
                                className="mt-0.5 truncate text-xs text-muted-foreground"
                                title={r.clients.join(", ")}
                              >
                                {r.clients.join(", ")}
                              </div>
                            )}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {r.total_requests}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {r.total_vacancies}
                          </td>
                          <td className="px-3 py-2 text-right font-medium tabular-nums">
                            {r.placements}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {pct(r.hit_ratio)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {pct(r.fill_rate)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {r.open_requests} / {r.open_vacancies}
                          </td>
                          <td className="px-3 py-2 text-center">
                            {/* `null` = nie da się ocenić (brak zapytań w oknie).
                                To NIE jest „nie osiągnął" — pod D7 ten wiersz
                                widzi cała firma. */}
                            {r.target_achieved === null ? (
                              <span
                                className="cursor-help text-muted-foreground"
                                title="Brak zapytań w tym oknie — nie ma czego oceniać."
                              >
                                —
                              </span>
                            ) : r.target_achieved ? (
                              <Award className="inline-block h-4 w-4 text-amber-500" />
                            ) : (
                              <span className="text-xs text-muted-foreground">
                                poniżej {data.hit_ratio_target_pct}%
                              </span>
                            )}
                          </td>
                        </tr>
                        {open && (
                          <tr className="border-b border-border bg-muted/30">
                            <td colSpan={8} className="px-3 py-3">
                              <DeliveryLeadTrend
                                dlId={r.user_id}
                                name={r.name}
                              />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Org-level, NIGDY w czyimś wierszu. Bez tej linijki suma kolumny
              po cichu nie zgadza się z lejkiem i nikt nie wie dlaczego. */}
          {hasUnattributed && unattributed && (
            <p className="text-xs text-muted-foreground">
              Bez przypisanego Delivery Leada: {count(unattributed.requests)}{" "}
              zapytań, {count(unattributed.vacancies)} wakatów,{" "}
              {count(unattributed.placements)} placementów,{" "}
              {count(unattributed.open_requests)} otwartych. To rekrutacje bez
              `delivery_lead_id`, których klient nie ma głównego opiekuna — nie
              wchodzą do żadnego wiersza wyżej.
            </p>
          )}
        </>
      )}
    </section>
  );
}

/**
 * Trend jednego DL — każdy miesiąc w SWOIM oknie.
 *
 * Komponent MONTUJE SIĘ dopiero po rozwinięciu wiersza, więc zapytanie leci
 * raz na kliknięcie, a nie raz na Delivery Leada przy wejściu na zakładkę.
 *
 * To jest konsument naprawy `reports.py:898-945`, gdzie górna granica miesiąca
 * była liczona i wyrzucana — seria wychodziła KUMULATYWNA (każdy punkt = ogon
 * do dziś), czyli z definicji malejąca, i czytało się to jak zapaść wydajności.
 */
function DeliveryLeadTrend({ dlId, name }: { dlId: number; name: string }) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.deliveryLeadTrend(dlId, TREND_MONTHS),
    queryFn: () => insightsBoardApi.deliveryLeadTrend(dlId, TREND_MONTHS),
  });

  const months = data?.trend ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: months.length === 0,
  });

  if (viewState === "loading") {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Ładowanie trendu…
      </div>
    );
  }
  if (isBlockingViewState(viewState)) {
    return (
      <SectionError
        label={`Trend — ${name}`}
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }
  if (viewState === "empty" || !data) {
    return (
      <p className="text-xs text-muted-foreground">
        Brak miesięcy w serii dla tego Delivery Leada.
      </p>
    );
  }

  const max = Math.max(...months.map((m) => m.placements), 1);

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Ostatnie {data.months} miesięcy · każdy punkt to OSOBNE okno, seria nie
        jest kumulatywna.
      </p>
      <div className="flex items-end gap-2">
        {months.map((m) => (
          <div
            key={m.month}
            className="flex flex-1 flex-col items-center gap-1"
          >
            <div className="flex h-16 w-full items-end">
              <div
                className={cn(
                  "w-full rounded-t bg-primary/70",
                  m.placements === 0 && "bg-muted-foreground/25",
                )}
                style={{
                  height: `${Math.max((m.placements / max) * 100, 4)}%`,
                }}
                title={`${m.month}: ${m.placements} placementów, ${m.requests} zapytań, hit ratio ${pct(m.hit_ratio)}`}
              />
            </div>
            <span className="text-[10px] tabular-nums text-muted-foreground">
              {m.month.slice(5)}
            </span>
            <span className="text-[10px] font-medium tabular-nums text-foreground">
              {m.placements}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
