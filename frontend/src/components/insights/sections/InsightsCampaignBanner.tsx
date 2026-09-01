"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarClock, Target, TrendingDown, TrendingUp } from "lucide-react";
import {
  insightsCampaignApi,
  insightsCampaignQueryKeys,
} from "@/lib/insights-campaign-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { SectionError } from "./_shared";

interface Props {
  className?: string;
}

/** `null` to „nie policzone" i renderuje się jako „—", nigdy jako 0. */
function pct(value: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toLocaleString("pl-PL", { maximumFractionDigits: 1 })}%`;
}

/** Data kampanii po polsku: „1 lipca 2026". */
function formatDay(iso: string): string {
  const parsed = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleDateString("pl-PL", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

/**
 * Odmiana „dzień/dni" — „zostało 1 dni" czyta się jak usterka renderowania.
 *
 * Polski ma tu tylko dwie formy: „1 dzień" i „N dni" dla całej reszty
 * (2, 5, 22, 101 — wszystkie „dni"). Rozbudowana logika liczebników nie ma
 * czego rozróżnić.
 */
function daysLabel(days: number): string {
  return days === 1 ? "dzień" : "dni";
}

/**
 * Baner kampanii rekrutacyjnej — odpowiednik banera z DynaReportera.
 *
 * Cztery reguły, które ten komponent realizuje i których złamanie jest
 * defektem, nie kwestią gustu:
 *
 * 1. **Brak kampanii → NIC.** Nie pusty baner z zerami: ramka z napisem
 *    „0 / 0" twierdzi, że kampania trwa i idzie fatalnie. Kampanii po prostu
 *    nie ma.
 * 2. **Awaria ≠ pustka.** 403/500 renderuje `SectionError`, nie zniknięcie
 *    banera — inaczej niedziałający serwer wygląda jak „szefowie odwołali
 *    kampanię".
 * 3. **`progress_pct` NIE jest przycinane.** Pasek nie może być szerszy niż
 *    tor, więc przycinamy SZEROKOŚĆ — ale liczba obok pokazuje prawdę
 *    (150%), a przekroczenie celu dostaje własny podpis.
 * 4. **`null` to „—", nie 0.** Cel równy zeru nie daje procentu; wpisanie
 *    tam „0%" twierdziłoby, że policzyliśmy i wyszło zero.
 *
 * Definicje liczników („co to jest placement", „co to jest rezygnacja")
 * przychodzą z serwera i są wypisane pod kaflami. Trzy różne „rezygnacje"
 * w jednej aplikacji to ta sama klasa pomyłki, którą D2 zamyka dla
 * placementów — kafel bez definicji ją odtwarza.
 */
export function InsightsCampaignBanner({ className }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsCampaignQueryKeys.active(),
    queryFn: () => insightsCampaignApi.active(),
  });

  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: data === null,
  });

  // Kolejność jest istotna: awaria nie może przebrać się za brak kampanii.
  if (viewState === "loading") return null;
  if (isBlockingViewState(viewState)) {
    return (
      <SectionError
        label="Kampania rekrutacyjna"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }
  if (viewState === "empty" || !data) return null;

  const {
    name,
    emoji,
    start_date,
    end_date,
    target_net,
    days_remaining,
    placements,
    resignations,
    net,
    progress_pct,
    remaining_to_target,
    placements_definition_note,
    resignations_definition_note,
    net_definition_note,
  } = data;

  // Szerokość paska przycinamy do [0, 100] — tor ma stałą długość i ujemny
  // albo 150-procentowy `width` po prostu nie istnieje w CSS. Liczba obok
  // NIE jest przycinana: to ona niesie wynik.
  const barPct =
    progress_pct === null ? 0 : Math.min(100, Math.max(0, progress_pct));
  const exceeded = remaining_to_target < 0;

  return (
    <section
      aria-label={`Kampania: ${name}`}
      className={cn(
        "rounded-xl border border-warning/40 bg-linear-to-r from-warning to-warning/85",
        "p-5 text-warning-foreground shadow-xs",
        className,
      )}
    >
      <header className="flex flex-wrap items-start gap-3">
        {emoji ? (
          <span
            aria-hidden="true"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-warning-foreground/15 text-xl"
          >
            {emoji}
          </span>
        ) : null}
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold">{name}</h2>
          <p className="text-sm opacity-90">
            {formatDay(start_date)} – {formatDay(end_date)}
          </p>
        </div>
        <div className="flex items-center gap-1.5 text-sm font-semibold">
          <CalendarClock className="h-4 w-4" aria-hidden="true" />
          <span>
            {days_remaining.toLocaleString("pl-PL")} {daysLabel(days_remaining)}
          </span>
        </div>
      </header>

      <div className="mt-4 flex flex-wrap items-end justify-between gap-2">
        <p className="flex items-center gap-1.5 text-sm font-medium">
          <Target className="h-4 w-4" aria-hidden="true" />
          Cel: +{target_net.toLocaleString("pl-PL")} kontraktorów (netto)
        </p>
        <p className="text-xl font-bold tabular-nums">
          {net.toLocaleString("pl-PL")} / {target_net.toLocaleString("pl-PL")}
        </p>
      </div>

      <div
        role="progressbar"
        aria-valuenow={net}
        aria-valuemin={0}
        aria-valuemax={target_net}
        aria-valuetext={`${net} z ${target_net} (${pct(progress_pct)})`}
        className="mt-2 h-5 w-full overflow-hidden rounded-full bg-warning-foreground/20"
      >
        <div
          className="h-5 rounded-full bg-warning-foreground/85 transition-all duration-500"
          style={{ width: `${barPct}%` }}
        />
      </div>
      <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="font-medium">
          {exceeded
            ? `Cel przekroczony o ${Math.abs(remaining_to_target).toLocaleString("pl-PL")}`
            : `Zostało ${remaining_to_target.toLocaleString("pl-PL")} do celu`}
          <span className="opacity-80"> · {pct(progress_pct)}</span>
        </span>
        <span className="opacity-90">{net_definition_note}</span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <CampaignTile
          label="Placementy"
          value={placements}
          icon={TrendingUp}
          note={placements_definition_note}
        />
        <CampaignTile
          label="Rezygnacje"
          value={resignations}
          icon={TrendingDown}
          note={resignations_definition_note}
        />
      </div>

      {/*
        Definicje jadą z serwera i są tu wypisane DOSŁOWNIE. Zwinięte, bo
        zdanie o rezygnacjach ma pięć linijek i wypchnęłoby baner; ale
        obecne, bo „49" i „19" bez definicji to dwie liczby, o które nie da
        się zapytać.
      */}
      <details className="mt-3 text-xs">
        <summary className="cursor-pointer font-medium opacity-90">
          Jak liczymy te liczby?
        </summary>
        <dl className="mt-2 space-y-1.5 opacity-90">
          <div>
            <dt className="inline font-semibold">Placementy: </dt>
            <dd className="inline">{placements_definition_note}</dd>
          </div>
          <div>
            <dt className="inline font-semibold">Rezygnacje: </dt>
            <dd className="inline">{resignations_definition_note}</dd>
          </div>
        </dl>
      </details>
    </section>
  );
}

function CampaignTile({
  label,
  value,
  icon: Icon,
  note,
}: {
  label: string;
  value: number;
  icon: typeof TrendingUp;
  /** Pełna definicja z serwera — wchodzi w `title`, a nie w treść kafla. */
  note: string;
}) {
  return (
    <div
      title={note}
      className="rounded-lg border border-warning-foreground/20 bg-warning-foreground/10 p-3"
    >
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide opacity-90">
        <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        {label}
      </p>
      <p className="mt-1 text-2xl font-bold tabular-nums">
        {value.toLocaleString("pl-PL")}
      </p>
    </div>
  );
}
