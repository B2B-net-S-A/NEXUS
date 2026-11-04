"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChampionsSection } from "@/components/insights/sections/ChampionsSection";
import { CompetitionPeriodSelect } from "@/components/insights/sections/CompetitionPeriod";
import { CompetitionTiesAdmin } from "@/components/insights/sections/CompetitionTiesAdmin";
import { InsightsRaces } from "@/components/insights/sections/InsightsRaces";
import { insightsApi } from "@/lib/insights-api";
import {
  monthPeriodOptions,
  quarterPeriodOptions,
  racesApi,
  type CompetitionPeriodOption,
} from "@/lib/insights-races-api";
import { reportHref } from "@/lib/insights-reports";
import { ViewHeader } from "./ViewKit";

/**
 * Rywalizacja — pierwsza zakładka dla każdego (decyzja Artura 24.09.2026:
 * „Liga Mistrzów i wyścigi miesięczne — bardzo ważne, żeby to było").
 *
 * Bez wspólnego paska okresu: konkursy rozstrzygają się w kwartale i miesiącu
 * według regulaminu, więc Liga ma własny wybór kwartału, a wyścigi — miesiąca
 * (decyzja Artura 15.10.2026: rozliczona historia od stycznia 2026, okresy do
 * 11.10.2026 z DynaReportera). Wybór żyje w stanie ekranu, nie w adresie;
 * `null` = trwający okres, czyli zapytanie dokładnie takie jak przed wyborem.
 * Hall of Fame i ścieżka rozwoju stoją tu jako dwa krótkie paski; pełne
 * tabele są w Raportach.
 */
export function RywalizacjaView() {
  const [quarter, setQuarter] = useState<string | null>(null);
  const [month, setMonth] = useState<string | null>(null);
  const quarterOptions = useMemo(() => quarterPeriodOptions(), []);
  const monthOptions = useMemo(() => monthPeriodOptions(), []);

  return (
    <div className="space-y-6">
      <ViewHeader
        question="Kto wygrywa i o co gramy?"
        lede="Liga Mistrzów liczy cały kwartał, wyścigi — miesiąc. Wybierz okres, żeby zobaczyć rozliczone wyniki. Twój wiersz jest podświetlony."
      />
      <CompetitionTiesAdmin />

      <ChampionsSection
        period={quarter}
        action={
          <CompetitionPeriodSelect
            label="Kwartał"
            value={selectedValue(quarterOptions, quarter)}
            options={quarterOptions}
            onChange={(value) => setQuarter(asPeriod(quarterOptions, value))}
          />
        }
      />

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <h2 className="text-base font-semibold text-foreground">
            Wyścigi miesiąca
          </h2>
          <CompetitionPeriodSelect
            label="Miesiąc"
            value={selectedValue(monthOptions, month)}
            options={monthOptions}
            onChange={(value) => setMonth(asPeriod(monthOptions, value))}
          />
        </div>
        <InsightsRaces month={month} />
      </section>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <HallOfFameStrip />
        <SeniorityStrip />
      </div>
    </div>
  );
}

/** Wartość listy: wybrany okres albo trwający, gdy nic nie wybrano. */
function selectedValue(
  options: readonly CompetitionPeriodOption[],
  period: string | null,
): string {
  return period ?? options.find((option) => option.current)?.value ?? "";
}

/** Trwający okres wraca jako `null` — zapytanie bez `period`, jak dotąd. */
function asPeriod(
  options: readonly CompetitionPeriodOption[],
  value: string,
): string | null {
  return options.find((option) => option.value === value)?.current
    ? null
    : value;
}

function Strip({
  eyebrow,
  headline,
  detail,
  href,
  linkLabel,
  onRetry,
}: {
  eyebrow: string;
  headline: string;
  detail: string | null;
  href: string;
  linkLabel: string;
  /** Awaria zapytania — przycisk „Ponów”. Awaria ≠ ładowanie („…”). */
  onRetry?: () => void;
}) {
  return (
    <section className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl border border-border bg-card px-4 py-3 shadow-xs">
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {eyebrow}
        </p>
        <p className="text-sm font-semibold text-foreground">{headline}</p>
      </div>
      {detail ? (
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">{detail}</p>
      ) : (
        <span className="flex-1" />
      )}
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="text-sm font-semibold text-primary hover:underline"
        >
          Ponów
        </button>
      ) : null}
      <Link
        href={href}
        className="text-sm font-semibold text-primary hover:underline"
      >
        {linkLabel}
      </Link>
    </section>
  );
}

/** Nagłówek paska: awaria mówi to wprost, zamiast wisieć na „…” (audyt 24.09.2026). */
export function stripHeadline(
  state: { isSuccess: boolean; isError: boolean },
  ready: () => string,
): string {
  if (state.isError) return "Nie udało się wczytać";
  if (!state.isSuccess) return "…";
  return ready();
}

function HallOfFameStrip() {
  const { data, isSuccess, isError, refetch } = useQuery({
    queryKey: ["insights", "hall-of-fame", "all-time"],
    queryFn: () => racesApi.hallOfFameAllTime(),
    staleTime: 5 * 60 * 1000,
  });
  const ranking = data?.full_ranking ?? [];
  const [first, ...rest] = ranking;
  return (
    <Strip
      eyebrow="Hall of Fame"
      headline={stripHeadline({ isSuccess, isError }, () =>
        first
          ? `${first.name} · ${first.metric_value} placementów`
          : "Brak placementów w historii",
      )}
      detail={
        rest.length
          ? rest
              .slice(0, 2)
              .map((e, i) => `${i + 2}. ${e.name} ${e.metric_value}`)
              .join(" · ")
          : null
      }
      href={reportHref("hall-of-fame")}
      linkLabel="Cały ranking →"
      onRetry={isError ? () => void refetch() : undefined}
    />
  );
}

function SeniorityStrip() {
  const { data, isSuccess, isError, refetch } = useQuery({
    queryKey: ["insights", "recruitment", "seniority"],
    queryFn: () => insightsApi.seniority(),
    staleTime: 5 * 60 * 1000,
  });
  const levels = data?.totals.levels;
  const closeToPromotion = (data?.entries ?? []).filter(
    (e) => e.placements_to_next_level === 1,
  ).length;
  return (
    <Strip
      eyebrow="Ścieżka rozwoju"
      headline={stripHeadline({ isSuccess: isSuccess && !!levels, isError }, () =>
        levels
          ? `${levels.junior} Junior · ${levels.senior} Senior · ${levels.expert} Expert`
          : "…",
      )}
      detail={
        closeToPromotion
          ? `${peopleAre(closeToPromotion)} o 1 placement od awansu`
          : null
      }
      href={reportHref("sciezka")}
      linkLabel="Kto i ile →"
      onRetry={isError ? () => void refetch() : undefined}
    />
  );
}

/** „1 osoba jest", „3 osoby są", „5 osób jest". */
function peopleAre(n: number): string {
  if (n === 1) return "1 osoba jest";
  const lastTwo = n % 100;
  const last = n % 10;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) {
    return `${n} osoby są`;
  }
  return `${n} osób jest`;
}
