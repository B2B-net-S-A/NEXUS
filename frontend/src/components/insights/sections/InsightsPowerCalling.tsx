"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Loader2, PhoneCall } from "lucide-react";

import {
  DEFAULT_POWER_CALLING_OFFSET_WEEKS,
  POWER_CALLING_MAX_OFFSET_WEEKS,
  POWER_CALLING_MIN_OFFSET_WEEKS,
  insightsActivityApi,
  insightsActivityQueryKeys,
  pctOf,
  type PowerCallingEntry,
} from "@/lib/insights-activity-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { DefinitionNote, barWidth, count, pct } from "./InsightsFormat";
import { Degraded, NotAssessable, SectionError } from "./_shared";

interface Props {
  /** Startowy tydzień. 0 = bieżący, 1 = poprzedni (domyślny). */
  defaultOffsetWeeks?: number;
}

/** Liczba dziesiętna po polsku albo „—”. `null` NIGDY nie staje się zerem. */
function decimal(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("pl-PL", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  });
}

function clampOffset(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_POWER_CALLING_OFFSET_WEEKS;
  return Math.min(
    POWER_CALLING_MAX_OFFSET_WEEKS,
    Math.max(POWER_CALLING_MIN_OFFSET_WEEKS, Math.trunc(value)),
  );
}

/**
 * Werdykt progu. TRZY stany, nie dwa.
 *
 * `null` znaczy „nie wiemy" — i musi wyglądać inaczej niż `false`. Zlanie tych
 * dwóch stanów w jeden czerwony znacznik jest dokładnie tym defektem, dla
 * którego backend rozbił odpowiedź na trzy listy: tydzień urlopu daje zero
 * weryfikacji i wygląda identycznie jak tydzień lenistwa.
 */
function TargetStatus({ meets }: { meets: boolean | null }) {
  if (meets === null || meets === undefined) {
    return (
      <span
        className="text-muted-foreground"
        title="Nie wiemy — brak mianownika dni roboczych dla tej osoby."
      >
        —
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex rounded-md px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        meets
          ? "bg-success-muted text-success-muted-foreground"
          : "bg-destructive-muted text-destructive-muted-foreground",
      )}
    >
      {meets ? "Spełnia próg" : "Poniżej progu"}
    </span>
  );
}

function EntryRow({
  entry,
  targetPerDay,
}: {
  entry: PowerCallingEntry;
  targetPerDay: number;
}) {
  // Realizacja progu liczona TUTAJ, a nie z `progress_pct`: backend przycina
  // tamto pole do 100 (`min(100, ...)`), więc 133% wyglądałoby jak równe sto.
  // Pasek wolno przyciąć (nie ma jak wyjść poza tor), liczbę obok — nie.
  const achieved = pctOf(entry.per_day, targetPerDay);

  return (
    <tr className="border-b border-border/50">
      <td className="py-2 pr-2">
        <div className="font-medium text-foreground">{entry.name}</div>
        <div className="text-xs text-muted-foreground">
          {entry.primary_category?.name_pl ?? entry.role}
        </div>
      </td>
      <td className="py-2 px-2 text-right tabular-nums">
        {count(entry.verifications_week)}
      </td>
      <td className="py-2 px-2 text-right">
        <div className="tabular-nums font-medium text-foreground">
          {entry.per_day === null
            ? "—"
            : `${decimal(entry.per_day, 2)} / dzień`}
        </div>
        {/* Rachunek pod spodem, żeby dało się go sprawdzić wzrokiem —
            bez mianownika „2,6 / dzień” jest liczbą nie do zweryfikowania. */}
        <div className="text-xs text-muted-foreground tabular-nums">
          ({count(entry.verifications_week)} wer. / {decimal(entry.workdays)}{" "}
          dni)
        </div>
      </td>
      <td className="py-2 px-2">
        <div className="flex items-center gap-2">
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className={cn(
                "h-2 rounded-full",
                entry.meets_target
                  ? "bg-success-muted-foreground"
                  : "bg-primary",
              )}
              style={{ width: `${barWidth(achieved)}%` }}
            />
          </div>
          <span className="w-12 text-right text-xs tabular-nums text-muted-foreground">
            {pct(achieved, 0)}
          </span>
        </div>
      </td>
      <td className="py-2 pl-2 text-right">
        <TargetStatus meets={entry.meets_target} />
      </td>
    </tr>
  );
}

function EntryTable({
  entries,
  targetPerDay,
}: {
  entries: PowerCallingEntry[];
  targetPerDay: number;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-xs uppercase text-muted-foreground">
            <th className="py-2 pr-2 text-left font-medium">Osoba</th>
            <th className="py-2 px-2 text-right font-medium">Weryfikacje</th>
            <th className="py-2 px-2 text-right font-medium">
              Na dzień roboczy
            </th>
            <th className="py-2 px-2 text-left font-medium w-40">
              Realizacja progu
            </th>
            <th className="py-2 pl-2 text-right font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <EntryRow key={e.user_id} entry={e} targetPerDay={targetPerDay} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Group({
  title,
  tone,
  entries,
  targetPerDay,
}: {
  title: string;
  tone: "below" | "met";
  entries: PowerCallingEntry[];
  targetPerDay: number;
}) {
  // Pusta grupa się NIE renderuje: nagłówek „Poniżej progu" nad zerem wierszy
  // czyta się jak lista, która się nie doczytała.
  if (entries.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "inline-flex rounded-md px-2 py-0.5 text-xs font-semibold",
            tone === "below"
              ? "bg-destructive-muted text-destructive-muted-foreground"
              : "bg-success-muted text-success-muted-foreground",
          )}
        >
          {title}
        </span>
        <span className="text-xs text-muted-foreground">{entries.length}</span>
      </div>
      <EntryTable entries={entries} targetPerDay={targetPerDay} />
    </div>
  );
}

/**
 * Power Calling — weryfikacje tygodniowo per sourcer/TAC/rekruter.
 *
 * Ekran wskazuje ludzi palcem, więc trzy rzeczy są tu warunkiem poprawności,
 * a nie kwestią układu:
 *
 * 1. **Trzeci stan jest osobny i neutralny.** `not_assessable` (brak danych
 *    o dniach roboczych albo zero dni roboczych — czyli urlop) idzie na dół,
 *    bez czerwieni i bez sąsiedztwa z „poniżej progu". Zero weryfikacji
 *    w tygodniu urlopu wygląda identycznie jak zero z lenistwa; jedyną
 *    uczciwą reakcją jest nie oceniać.
 * 2. **`meets_target === null` to „nie wiemy", nie „nie spełnia".**
 * 3. **Mianownik jest widoczny.** Obok „2,6 / dzień" stoi „(13 wer. / 5 dni)",
 *    żeby rachunek dało się sprawdzić bez wchodzenia do bazy.
 *
 * Sekcja ma WŁASNY wybór tygodnia i świadomie nie przyjmuje `InsightsPeriodParams`:
 * endpoint zna wyłącznie `offset_weeks` (tydzień ISO), więc podpięcie go pod
 * `PeriodPicker` obiecywałoby miesiąc/kwartał, których backend nie policzy.
 */
export function InsightsPowerCalling({
  defaultOffsetWeeks = DEFAULT_POWER_CALLING_OFFSET_WEEKS,
}: Props = {}) {
  const [offsetWeeks, setOffsetWeeks] = useState(() =>
    clampOffset(defaultOffsetWeeks),
  );

  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsActivityQueryKeys.powerCalling(offsetWeeks),
    queryFn: () => insightsActivityApi.powerCalling(offsetWeeks),
  });

  const below = data?.below_target ?? [];
  const met = data?.met_target ?? [];
  const notAssessable = data?.not_assessable ?? [];

  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: (data?.total_count ?? 0) === 0,
  });

  const shift = (by: number) =>
    setOffsetWeeks((prev) => clampOffset(prev + by));

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-xs">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
            <PhoneCall className="h-5 w-5 text-primary" />
            Power Calling
          </h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {data
              ? `${data.week_label} · ${data.date_from} – ${data.date_to}`
              : "Raport tygodniowy"}
          </p>
        </div>

        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => shift(1)}
            disabled={offsetWeeks >= POWER_CALLING_MAX_OFFSET_WEEKS}
            aria-label="Poprzedni tydzień"
            className="rounded-md border border-border p-1.5 text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => shift(-1)}
            disabled={offsetWeeks <= POWER_CALLING_MIN_OFFSET_WEEKS}
            aria-label="Następny tydzień"
            className="rounded-md border border-border p-1.5 text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      {viewState === "loading" ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Power Calling"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          W tym tygodniu nikt z sourcerów, TAC-ów ani rekruterów nie odnotował
          weryfikacji (etapy: nowy, screening, prep call).
        </p>
      ) : (
        <div className="space-y-5">
          {/* Mianownik NIE pochodzi z NEXUSA — bez tego zdania czytelnik zostaje
              z kolumną samych „—” i nie wie, czy to awaria, czy brak integracji. */}
          {data?.workdays_source === "unavailable" && (
            <Degraded
              status="unavailable"
              reason={
                "Dni robocze pochodzą z COMPASSA, a integracja nie dowiozła danych " +
                "za ten tydzień — dlatego NIKT nie jest oceniony i wszyscy są na " +
                "liście nieocenianych. Liczby weryfikacji poniżej są prawdziwe; " +
                "brakuje wyłącznie mianownika."
              }
            />
          )}

          <Group
            title="Poniżej progu"
            tone="below"
            entries={below}
            targetPerDay={data?.target_per_day ?? 0}
          />
          <Group
            title="Próg spełniony"
            tone="met"
            entries={met}
            targetPerDay={data?.target_per_day ?? 0}
          />

          {/* Na końcu i wizualnie osobno — sąsiedztwo z „poniżej progu"
              wystarczy, żeby brak danych przeczytać jako słaby wynik. */}
          <NotAssessable
            title="Nieoceniani w tym tygodniu"
            rows={notAssessable.map((e) => ({
              id: e.user_id,
              name: e.name,
              reason: e.reason,
              // Liczba bezwzględna jest znana i uczciwa; brakuje tylko
              // mianownika, więc podajemy ją jako kontekst, nie jako wynik.
              hint: `${e.verifications_week} wer. w tym tygodniu`,
            }))}
            footnote="Brak mianownika to nie jest wynik. Te osoby nie są liczone ani do „poniżej progu”, ani do „próg spełniony”."
          />

          {data?.requirement_text && (
            <DefinitionNote>{data.requirement_text}</DefinitionNote>
          )}
        </div>
      )}
    </section>
  );
}
