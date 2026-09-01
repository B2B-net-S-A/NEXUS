"use client";

import { useCallback, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  RefreshCw,
  RotateCcw,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  DEFAULT_INSIGHTS_OFFSET,
  type InsightsPeriodKind,
  type InsightsPeriodParams,
} from "@/lib/insights-api";

/**
 * Lustro `MAX_CUSTOM_PERIOD_DAYS` z backend/app/analytics/periods.py.
 *
 * Backend odrzuca dłuższy zakres błędem 422 — nie przycina go po cichu. Front
 * musi więc znać ten sufit ZANIM wyśle zapytanie, inaczej przycisk „Wszystko”
 * byłby przyciskiem „Błąd”.
 */
export const INSIGHTS_MAX_CUSTOM_PERIOD_DAYS = 366;

/** Lustro `ANALYTICS_TIMEZONE` — okresy są kalendarzowe, nie kroczące UTC. */
export const INSIGHTS_ANALYTICS_TIMEZONE = "Europe/Warsaw";

/** Domyślny okres, gdy rodzic nie poda własnego (patrz prop `defaultValue`). */
const FALLBACK_DEFAULT: InsightsPeriodParams = {
  period: "month",
  offset: DEFAULT_INSIGHTS_OFFSET,
};

const GRANULARITIES: Array<{ id: InsightsPeriodKind; label: string }> = [
  { id: "week", label: "Tydzień" },
  { id: "month", label: "Miesiąc" },
  { id: "quarter", label: "Kwartał" },
  { id: "year", label: "Rok" },
  // „Wszystko” nie jest osobnym `PeriodKind` — mapuje się na `custom`
  // z zakresem dociętym do sufitu backendu (patrz `buildAllTimePeriod`).
  { id: "custom", label: "Wszystko" },
];

/** Okno zwrócone przez backend — źródło etykiety. */
export interface ResolvedInsightsWindow {
  start: string;
  end: string;
  timezone: string;
  /**
   * Opcjonalne, bo prop jest strukturalny: starsi konsumenci przekazują tu
   * `InsightsPeriod` (ma `kind`), ale kontrakt nie może tego wymagać, żeby nie
   * zerwać wywołań, które podają samo okno.
   */
  kind?: InsightsPeriodKind;
}

/** Dane do eksportu CSV — buduje je RODZIC, bo tylko on wie, co pokazuje. */
export interface InsightsCsvExport {
  /** Nazwa pliku BEZ rozszerzenia i bez okna — okno dokleja picker. */
  filename: string;
  headers: string[];
  /** Każdy wiersz o długości `headers`. `null` → pusta komórka, nie „0”. */
  rows: Array<Array<string | number | null>>;
}

interface Props {
  value: InsightsPeriodParams;
  onChange: (next: InsightsPeriodParams) => void;
  resolved?: ResolvedInsightsWindow | null;
  /**
   * Okres, do którego wraca „Reset”. Opcjonalny, bo każdy panel ma inny
   * domyślny (Rekrutacja: poprzedni miesiąc, Zarząd: bieżący kwartał) — a
   * wpisanie jednego na sztywno cofałoby dwa z trzech paneli w złe miejsce.
   */
  defaultValue?: InsightsPeriodParams;
  /**
   * Brak propu (albo zero wierszy) = przycisk „Eksportuj” się NIE renderuje.
   * Widoczny przycisk oddający pusty plik jest gorszy niż jego brak: wygląda
   * jak utrata danych, a jest brakiem funkcji.
   */
  csv?: InsightsCsvExport | null;
}

/**
 * Pasek narzędzi okresu: granulacja + kotwica (strzałki) + akcje.
 *
 * Zastępuje `PeriodSelector`, który oferował „Ostatnie 7 dni" / „Ostatnie
 * 30 dni" — czyli okna KROCZĄCE, podczas gdy backend liczy KALENDARZOWO.
 * Podpis pod spodem pokazuje realne okno policzone przez serwer, żeby nie
 * trzeba było zgadywać, co właściwie widać.
 *
 * Wszystkie nowe propsy są opcjonalne — komponent jest współdzielony przez trzy
 * panele i istniejące wywołania muszą działać bez zmian.
 */
export function PeriodPicker({
  value,
  onChange,
  resolved,
  defaultValue,
  csv,
}: Props) {
  const queryClient = useQueryClient();
  const offset = value.offset ?? 0;
  const isAllTime = value.period === "custom";

  const shift = (by: number) =>
    onChange({ ...value, offset: offset + by, anchor: undefined });

  const handleGranularity = (kind: InsightsPeriodKind) => {
    // „Wszystko” potrzebuje wprost policzonych dat — `custom` bez date_from /
    // date_to kończy się po stronie backendu błędem 422.
    onChange(
      kind === "custom" ? buildAllTimePeriod() : { period: kind, offset: 0 },
    );
  };

  const handleRefresh = useCallback(() => {
    // Prefiks klucza — react-query dopasowuje po początku tablicy, więc jedno
    // wywołanie odświeża wszystkie sekcje wszystkich trzech zakładek.
    void queryClient.invalidateQueries({ queryKey: ["insights"] });
  }, [queryClient]);

  const handleReset = useCallback(() => {
    onChange(defaultValue ?? FALLBACK_DEFAULT);
  }, [defaultValue, onChange]);

  const handleExport = useCallback(() => {
    if (!csv || csv.rows.length === 0) return;
    downloadCsv(
      `${csv.filename}${windowFilenameSuffix(resolved)}.csv`,
      buildInsightsCsv(csv.headers, csv.rows),
    );
  }, [csv, resolved]);

  const caption = useMemo(
    () => describeWindow(resolved, value.period),
    [resolved, value.period],
  );

  // Sufit ogłaszamy tylko wtedy, gdy realnie obowiązuje. Ostrzeżenie przy
  // krótszym oknie custom mówiłoby o przycięciu, którego nie było.
  const cappedAllTime =
    isAllTime && customSpanDays(value) >= INSIGHTS_MAX_CUSTOM_PERIOD_DAYS;

  const canExport = Boolean(csv && csv.rows.length > 0);

  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <div
          role="group"
          aria-label="Granulacja okresu"
          className="flex overflow-hidden rounded-lg border border-border"
        >
          {GRANULARITIES.map((g) => (
            <button
              key={g.id}
              type="button"
              onClick={() => handleGranularity(g.id)}
              aria-pressed={value.period === g.id}
              className={cn(
                "px-3 py-1.5 text-xs font-medium transition-colors",
                value.period === g.id
                  ? "bg-primary text-primary-foreground"
                  : "bg-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {g.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => shift(-1)}
            // Kotwica nie ma zastosowania do `custom` — backend odrzuca offset
            // razem z jawnym zakresem (422), więc strzałka musi zgasnąć.
            disabled={isAllTime}
            aria-label="Poprzedni okres"
            className="rounded-md border border-border p-1.5 text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => shift(1)}
            // Przyszły okres jest legalny (half-open liczy okres w toku),
            // ale ruch naprzód z bieżącego nie ma sensu — blokujemy.
            disabled={isAllTime || offset >= 0}
            aria-label="Następny okres"
            className="rounded-md border border-border p-1.5 text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        <div className="flex items-center gap-1">
          {canExport && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleExport}
            >
              <Download className="h-3.5 w-3.5" />
              Eksportuj
            </Button>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleRefresh}
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Odśwież
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={handleReset}>
            <RotateCcw className="h-3.5 w-3.5" />
            Reset
          </Button>
        </div>
      </div>

      {caption && (
        <div className="flex flex-col items-end gap-0.5">
          <p className="text-xs font-medium text-foreground tabular-nums">
            {caption.headline}
          </p>
          <p className="text-[11px] text-muted-foreground tabular-nums">
            {caption.range} · {caption.timezone}
          </p>
        </div>
      )}

      {cappedAllTime && (
        <p className="max-w-[22rem] rounded-md bg-warning-muted px-2 py-1 text-right text-[11px] leading-snug text-warning-muted-foreground">
          „Wszystko” = ostatnie {INSIGHTS_MAX_CUSTOM_PERIOD_DAYS} dni. Dłuższego
          okna backend nie policzy, więc to NIE jest cała historia.
        </p>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Okres „Wszystko”
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Najszersze okno, jakie backend przyjmie: ostatnie
 * `INSIGHTS_MAX_CUSTOM_PERIOD_DAYS` dni kalendarzowych, licząc dzisiejszy dzień.
 *
 * Świadomie NIE ustawia `offset` — `resolve_period` odrzuca offset podany razem
 * z jawnym zakresem, a `periodQuery` pomija klucze `undefined`.
 */
export function buildAllTimePeriod(
  now: Date = new Date(),
): InsightsPeriodParams {
  const to = zonedCalendarDate(now, INSIGHTS_ANALYTICS_TIMEZONE);
  // Backend liczy `date_to - date_from + 1`, więc krok wstecz jest o jeden
  // mniejszy niż sufit — inaczej okno miałoby 367 dni i wróciłoby 422.
  const from = addDays(to, -(INSIGHTS_MAX_CUSTOM_PERIOD_DAYS - 1));
  return { period: "custom", date_from: ymd(from), date_to: ymd(to) };
}

/** Długość okna custom w dniach (inclusive, jak liczy backend). 0 = brak dat. */
function customSpanDays(value: InsightsPeriodParams): number {
  if (!value.date_from || !value.date_to) return 0;
  const from = Date.parse(`${value.date_from}T00:00:00Z`);
  const to = Date.parse(`${value.date_to}T00:00:00Z`);
  if (Number.isNaN(from) || Number.isNaN(to)) return 0;
  return Math.floor((to - from) / DAY_MS) + 1;
}

// ─────────────────────────────────────────────────────────────────────────────
// Etykieta okna
// ─────────────────────────────────────────────────────────────────────────────

const DAY_MS = 24 * 60 * 60 * 1000;

export interface WindowCaption {
  /** Nagłówek w stylu DynaReportera — „Tydzień 35/2026 (24–30 sie)”. */
  headline: string;
  /** Dokładne granice okna, zawsze z rokiem. */
  range: string;
  timezone: string;
}

/**
 * Opisz okno zwrócone przez serwer.
 *
 * Okno jest półotwarte [start, end), więc ostatni dzień NALEŻĄCY do okresu to
 * `end − 1 dzień`. Pokazanie surowego `end` sugerowałoby, że sierpień kończy
 * się 1 września.
 */
export function describeWindow(
  resolved: ResolvedInsightsWindow | null | undefined,
  fallbackKind: InsightsPeriodKind,
): WindowCaption | null {
  if (!resolved) return null;
  const timeZone = resolved.timezone || INSIGHTS_ANALYTICS_TIMEZONE;
  const start = parseCalendarDate(resolved.start, timeZone);
  const endExclusive = parseCalendarDate(resolved.end, timeZone);
  if (!start || !endExclusive) return null;

  // Odejmujemy dzień KALENDARZOWO, nie 24 godziny: doba zmiany czasu ma 23 lub
  // 25 godzin, więc arytmetyka na milisekundach gubi tu jeden dzień.
  const last = addDays(endExclusive, -1);
  const kind = resolved.kind ?? fallbackKind;

  return {
    headline: headlineFor(kind, start, last),
    range: `${fmtDayMonthYear(start)} – ${fmtDayMonthYear(last)}`,
    timezone: timeZone,
  };
}

function headlineFor(
  kind: InsightsPeriodKind,
  start: Date,
  last: Date,
): string {
  switch (kind) {
    case "day":
      return fmtDayMonthYear(start);
    case "week": {
      const { week, year } = isoWeek(start);
      return `Tydzień ${week}/${year} (${fmtDayRange(start, last)})`;
    }
    case "month":
      return capitalize(fmtMonthYear(start));
    case "quarter":
      return `Q${Math.floor(start.getUTCMonth() / 3) + 1} ${start.getUTCFullYear()}`;
    case "year":
      return String(start.getUTCFullYear());
    case "custom":
    default:
      return `${fmtDayMonthYear(start)} – ${fmtDayMonthYear(last)}`;
  }
}

/** „24–30 sie” w jednym miesiącu, „31 sie – 6 wrz” na przełomie miesięcy. */
function fmtDayRange(start: Date, last: Date): string {
  const sameMonth =
    start.getUTCFullYear() === last.getUTCFullYear() &&
    start.getUTCMonth() === last.getUTCMonth();
  return sameMonth
    ? `${start.getUTCDate()}–${fmtDayMonth(last)}`
    : `${fmtDayMonth(start)} – ${fmtDayMonth(last)}`;
}

/**
 * Numer tygodnia ISO-8601 wraz z rokiem tygodnia.
 *
 * Rok tygodnia bywa inny niż rok daty (1 stycznia potrafi należeć do tygodnia
 * 52 roku poprzedniego) — dlatego liczymy go z czwartku, a nie z `start`.
 */
export function isoWeek(date: Date): { week: number; year: number } {
  const thursday = new Date(date.getTime());
  const dayNum = thursday.getUTCDay() || 7; // pon = 1 … niedz = 7
  thursday.setUTCDate(thursday.getUTCDate() + 4 - dayNum);
  const year = thursday.getUTCFullYear();
  const jan1 = Date.UTC(year, 0, 1);
  const week = Math.ceil(((thursday.getTime() - jan1) / DAY_MS + 1) / 7);
  return { week, year };
}

// ─────────────────────────────────────────────────────────────────────────────
// Daty kalendarzowe
//
// Wszystkie daty poniżej to „gołe” dni kalendarzowe reprezentowane jako północ
// UTC. Dzięki temu arytmetyka i formatowanie są wolne od DST — strefa wchodzi
// do gry wyłącznie raz, przy odczytaniu dnia z chwili ISO.
// ─────────────────────────────────────────────────────────────────────────────

function calendarFormatter(timeZone: string): Intl.DateTimeFormat {
  const options: Intl.DateTimeFormatOptions = {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  };
  try {
    return new Intl.DateTimeFormat("en-US", { ...options, timeZone });
  } catch {
    // Nieznana strefa z serwera nie może wywalić paska narzędzi.
    return new Intl.DateTimeFormat("en-US", options);
  }
}

function zonedCalendarDate(instant: Date, timeZone: string): Date {
  const parts = calendarFormatter(timeZone).formatToParts(instant);
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((p) => p.type === type)?.value ?? "0");
  return new Date(Date.UTC(get("year"), get("month") - 1, get("day")));
}

function parseCalendarDate(iso: string, timeZone: string): Date | null {
  const instant = new Date(iso);
  if (Number.isNaN(instant.getTime())) return null;
  return zonedCalendarDate(instant, timeZone);
}

function addDays(date: Date, days: number): Date {
  const out = new Date(date.getTime());
  out.setUTCDate(out.getUTCDate() + days);
  return out;
}

function ymd(date: Date): string {
  return date.toISOString().slice(0, 10);
}

const DAY_MONTH = new Intl.DateTimeFormat("pl-PL", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

const DAY_MONTH_YEAR = new Intl.DateTimeFormat("pl-PL", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

const MONTH_YEAR = new Intl.DateTimeFormat("pl-PL", {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});

const fmtDayMonth = (d: Date) => DAY_MONTH.format(d);
const fmtDayMonthYear = (d: Date) => DAY_MONTH_YEAR.format(d);
const fmtMonthYear = (d: Date) => MONTH_YEAR.format(d);

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// ─────────────────────────────────────────────────────────────────────────────
// Eksport CSV
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Separator to średnik, bo pliki lądują w polskim Excelu — przecinek zmusza
 * odbiorcę do kreatora importu przy każdym otwarciu.
 */
export function buildInsightsCsv(
  headers: string[],
  rows: Array<Array<string | number | null>>,
): string {
  const cell = (value: string | number | null | undefined) => {
    if (value === null || value === undefined) return "";
    const text = String(value);
    return /[";\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [headers, ...rows].map((row) => row.map(cell).join(";")).join("\r\n");
}

/** `_2026-08-01_2026-08-31` — żeby dwa eksporty z różnych okien się różniły. */
function windowFilenameSuffix(
  resolved: ResolvedInsightsWindow | null | undefined,
): string {
  if (!resolved) return "";
  const timeZone = resolved.timezone || INSIGHTS_ANALYTICS_TIMEZONE;
  const start = parseCalendarDate(resolved.start, timeZone);
  const endExclusive = parseCalendarDate(resolved.end, timeZone);
  if (!start || !endExclusive) return "";
  return `_${ymd(start)}_${ymd(addDays(endExclusive, -1))}`;
}

function downloadCsv(filename: string, content: string): void {
  // BOM — bez niego Excel czyta UTF-8 jako windows-1250 i psuje polskie znaki.
  const blob = new Blob([`\uFEFF${content}`], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
