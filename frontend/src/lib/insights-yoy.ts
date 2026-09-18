/**
 * Arytmetyka tabel rok-do-roku Rady — czyste funkcje, zero JSX.
 *
 * Backend zwraca WYŁĄCZNIE liczby (miesiąc × rok). Delta, kolumna „Ocena"
 * i wiersz podsumowania są przekształceniem tych liczb i mieszkają tutaj —
 * osobno od komponentu, bo dowodem ich poprawności ma być test na wartościach,
 * a nie zrzut ekranu. To ta sama lekcja co z PR #1316: komponent bywa poprawny,
 * a martwe jest jego PODŁĄCZENIE, więc testujemy warstwę, która naprawdę
 * przenosi znaczenie.
 *
 * Dwie decyzje, które łatwo cofnąć nieświadomie:
 *
 * 1. **Podsumowanie roku BIEŻĄCEGO porównuje się z tymi samymi miesiącami roku
 *    poprzedniego (YTD), nie z całym rokiem.** Dziewięć miesięcy 2026 obok
 *    dwunastu miesięcy 2025 daje spadek, którego nie ma. To jedyne miejsce,
 *    gdzie mianownik porównania jest INNY niż wartość wypisana w komórce obok
 *    — i dlatego wiersz musi to mówić.
 * 2. **Stany się UŚREDNIAJĄ, przepływy SUMUJĄ, WSKAŹNIKI liczą się od nowa.**
 *    Reguła przychodzi z serwera (`aggregate`) i nie ma tu własnej listy metryk.
 *    W DynaReporterze tej reguły nie było i kolumna „udział top klienta"
 *    sumowała się do 874%.
 * 3. **Wskaźnik za rok to Σlicznik / Σmianownik, nie średnia miesięcznych
 *    procentów.** Mianowniki miesięcy różnią się pięciokrotnie, więc miesiąc
 *    z 9 zamkniętymi rekrutacjami ważył tyle samo co miesiąc z 200. Zmierzone
 *    na produkcji (audyt 18.09.2026): hit ratio 2024 pokazywane 14,57% przy
 *    realnych 17,4% (134/770), 2025 — 16,58% przy realnych 14,5% (195/1342).
 *    Delta zmieniała znak: „+2,0 pp, Lepiej" zamiast „−2,9 pp, Gorzej".
 *    Liczności zbioru (`distinct`) nie da się złożyć z miesięcy w ogóle:
 *    klient obsłużony w marcu i w lipcu to jeden klient, nie dwóch.
 */

import type {
  InsightsYoYAggregate,
  InsightsYoYMetric,
} from "@/lib/insights-api";

/** Ocena zmiany rok do roku — steruje kolorem i słowem w kolumnie „Ocena". */
export type YoYVerdict = "better" | "worse" | "flat" | "unknown";

export interface YoYDelta {
  /** Zmiana w punktach procentowych (dla `pct`) albo procentowo (reszta). */
  value: number | null;
  /** `pp` = punkty procentowe, `pct` = zmiana względna. */
  mode: "pp" | "pct";
  verdict: YoYVerdict;
}

/**
 * Zmiana między dwiema wartościami tej samej metryki.
 *
 * Dla metryk procentowych liczymy różnicę w PUNKTACH procentowych, nie zmianę
 * względną: „hit ratio wzrosło o 50%" przy 20% → 30% jest prawdą arytmetyczną
 * i myli każdego, kto to czyta. Reszta metryk idzie zmianą względną.
 *
 * `null` przy braku którejkolwiek wartości albo przy zerowym mianowniku —
 * wzrost „o nieskończoność" nie jest liczbą, a 0 czytałoby się jako „bez zmian".
 */
export function yoyDelta(
  previous: number | null | undefined,
  current: number | null | undefined,
  opts: { unit: string; lowerIsBetter: boolean },
): YoYDelta {
  const mode: "pp" | "pct" = opts.unit === "pct" ? "pp" : "pct";
  if (previous === null || previous === undefined) {
    return { value: null, mode, verdict: "unknown" };
  }
  if (current === null || current === undefined) {
    return { value: null, mode, verdict: "unknown" };
  }
  if (mode === "pct" && previous === 0) {
    return { value: null, mode, verdict: "unknown" };
  }
  const raw =
    mode === "pp"
      ? current - previous
      : ((current - previous) / previous) * 100;
  const value = Math.round(raw * 10) / 10;
  return { value, mode, verdict: verdictFor(value, opts.lowerIsBetter) };
}

/**
 * Słowo w kolumnie „Ocena".
 *
 * Zero to „bez zmian", nigdy „Lepiej". DynaReporter oceniał `+0,0%` jako
 * „Lepiej" — dwie identyczne liczby dostawały zieloną plakietkę poprawy.
 */
export function verdictFor(
  delta: number | null,
  lowerIsBetter: boolean,
): YoYVerdict {
  if (delta === null) return "unknown";
  if (delta === 0) return "flat";
  const improved = lowerIsBetter ? delta < 0 : delta > 0;
  return improved ? "better" : "worse";
}

export const VERDICT_LABEL: Record<YoYVerdict, string> = {
  better: "Lepiej",
  worse: "Gorzej",
  flat: "Bez zmian",
  unknown: "—",
};

/** Ile miesięcy danego roku ma policzoną wartość (od stycznia, bez dziur). */
export function coveredMonths(series: Array<number | null>): number {
  let n = 0;
  for (const value of series) {
    if (value === null || value === undefined) break;
    n += 1;
  }
  return n;
}

/**
 * Podsumowanie roku — suma albo średnia, wg reguły z serwera.
 *
 * `limitMonths` zawęża zakres do porównania YTD: podsumowanie roku
 * poprzedniego liczone dla tych samych miesięcy, co niepełny rok bieżący.
 * Bez tego dziewięć miesięcy stoi obok dwunastu i pokazuje spadek, którego nie
 * ma. Średnia liczy się z miesięcy POLICZONYCH, nigdy z dwunastu na sztywno —
 * dzielenie przez 12 przy dziewięciu miesiącach zaniża wynik o jedną czwartą.
 */
export function aggregateSeries(
  series: Array<number | null>,
  aggregate: InsightsYoYAggregate,
  limitMonths?: number,
): number | null {
  const scope =
    limitMonths === undefined
      ? series
      : series.slice(0, Math.max(0, limitMonths));
  const values = scope.filter(
    (v): v is number => v !== null && v !== undefined,
  );
  if (values.length === 0) return null;
  const total = values.reduce((a, b) => a + b, 0);
  const result = aggregate === "sum" ? total : total / values.length;
  return Math.round(result * 100) / 100;
}

/**
 * Wskaźnik za rok: Σlicznik / Σmianownik, przeliczony od nowa.
 *
 * Liczymy WYŁĄCZNIE z miesięcy, w których znane są OBIE składowe — miesiąc
 * z licznikiem bez mianownika (albo odwrotnie) zawyżałby albo zaniżał wynik
 * w zależności od tego, której połowy brakuje. Zerowy mianownik to `null`,
 * nie zero: „nie było czego zamykać" znaczy co innego niż „nic nie zamknięto".
 *
 * `scale` = 100 dla metryk procentowych (backend podaje je w procentach),
 * 1 dla ilorazów mianowanych (PLN na godzinę).
 */
export function aggregateRatio(
  numerator: Array<number | null>,
  denominator: Array<number | null>,
  scale: number,
  limitMonths?: number,
): number | null {
  const cut = (series: Array<number | null>) =>
    limitMonths === undefined
      ? series
      : series.slice(0, Math.max(0, limitMonths));
  const num = cut(numerator);
  const den = cut(denominator);
  let sumNum = 0;
  let sumDen = 0;
  let months = 0;
  for (let i = 0; i < Math.max(num.length, den.length); i += 1) {
    const n = num[i];
    const d = den[i];
    if (n === null || n === undefined || d === null || d === undefined)
      continue;
    sumNum += n;
    sumDen += d;
    months += 1;
  }
  if (months === 0 || sumDen === 0) return null;
  return Math.round((sumNum / sumDen) * scale * 100) / 100;
}

export interface YoYRow {
  monthIndex: number;
  label: string;
  values: Array<number | null>;
  /**
   * Delta i ocena. W wierszu miesiąca TRWAJĄCEGO porównanie z ostatnim rokiem
   * jest wygaszone (`value: null`, `verdict: "unknown"`): kilka dni danych obok
   * pełnego miesiąca roku poprzedniego to „spadek" o dziesiątki procent,
   * którego nie ma.
   */
  deltas: YoYDelta[];
  /** Ten miesiąc jeszcze trwa — wartość jest niepełna, nie słaba. */
  partial: boolean;
}

export interface YoYSummary {
  values: Array<number | null>;
  deltas: YoYDelta[];
  /**
   * Ile PEŁNYCH miesięcy objęło porównanie z ostatnim rokiem (YTD). Miesiąc
   * trwający jest wyłączony z obu lat — 1 lutego to 1 (styczeń), nie 2.
   */
  comparedMonths: number;
  /** Czy porównanie zostało zawężone — wtedy wiersz musi o tym napisać. */
  ytd: boolean;
  /**
   * Czy z porównania wyłączono miesiąc, który jeszcze trwa. Przy
   * `comparedMonths === 0` (styczeń w toku) ostatniej delty nie ma w ogóle.
   */
  excludesPartialMonth: boolean;
}

export interface YoYTable {
  rows: YoYRow[];
  summary: YoYSummary;
}

/**
 * Cała tabela jednej metryki: wiersze miesięcy + wiersz podsumowania.
 *
 * `years` przychodzi rosnąco, więc delta `i` porównuje rok `i` z `i+1` — tak
 * jak kolumny na ekranie („Δ 24→25", „Δ 25→26").
 */
export function buildYoYTable(
  metric: InsightsYoYMetric,
  years: number[],
  monthLabels: string[],
  partialMonth: { year: number; month: number } | null,
  componentSeries?: Record<string, Record<string, Array<number | null>>>,
): YoYTable {
  const columns = years.map((y) => metric.series[String(y)] ?? []);
  const opts = { unit: metric.unit, lowerIsBetter: metric.lower_is_better };
  const lastYear = years[years.length - 1];
  // Numer (1–12) miesiąca, który jeszcze trwa W OSTATNIM roku siatki — albo
  // `null`, gdy żaden (wszystkie lata zamknięte albo trwający rok poza siatką).
  const partialMonthNumber: number | null =
    partialMonth !== null &&
    partialMonth.year === lastYear &&
    partialMonth.month >= 1 &&
    partialMonth.month <= 12
      ? partialMonth.month
      : null;
  const neutral = (mode: "pp" | "pct"): YoYDelta => ({
    value: null,
    mode,
    verdict: "unknown",
  });

  const rows: YoYRow[] = monthLabels.map((label, monthIndex) => {
    const values = columns.map((col) => col[monthIndex] ?? null);
    const partial =
      partialMonthNumber !== null && partialMonthNumber - 1 === monthIndex;
    return {
      monthIndex,
      label,
      values,
      deltas: values.slice(0, -1).map((prev, i) => {
        const delta = yoyDelta(prev, values[i + 1], opts);
        // Para z rokiem, w którym ten miesiąc jeszcze TRWA: bez oceny i bez
        // liczby. „−95%" pierwszego dnia miesiąca to kalendarz, nie wynik.
        const involvesPartial = partial && i === values.length - 2;
        return involvesPartial ? neutral(delta.mode) : delta;
      }),
      partial,
    };
  });

  // Zakres YTD wyznacza OSTATNI rok siatki: to on bywa niepełny. Miesiąc
  // TRWAJĄCY nie wchodzi do porównania — ani w roku bieżącym, ani w tym samym
  // miesiącu roku poprzedniego. Bez tego 1 lutego zestawiał styczeń + jeden
  // dzień lutego z pełnym styczniem i lutym, czyli „−45%", którego nie ma.
  const covered = coveredMonths(columns[columns.length - 1] ?? []);
  const excludesPartialMonth =
    partialMonthNumber !== null && partialMonthNumber <= covered;
  const comparedMonths =
    excludesPartialMonth && partialMonthNumber !== null
      ? partialMonthNumber - 1
      : covered;
  const ytd = excludesPartialMonth || (covered > 0 && covered < 12);

  // Wartość w komórce podsumowania opisuje CAŁY rok — to jest liczba, którą
  // czytelnik chce zobaczyć dla roku zamkniętego. Zawężony jest tylko MIANOWNIK
  // porównania, i tylko dla pary z ostatnim rokiem. Przy `comparedMonths === 0`
  // (styczeń w toku) porównywać nie ma czego — delta to „—", nie −100%.
  const summarize = (limit?: number): Array<number | null> => {
    if (metric.aggregate === "distinct") {
      // Liczności zbioru nie da się zawęzić do N miesięcy bez samego zbioru,
      // więc porównanie YTD dla tej metryki nie istnieje — rok jest rokiem.
      return years.map((y) => metric.yearly?.[String(y)] ?? null);
    }
    if (metric.aggregate === "ratio") {
      const parts = componentSeries ?? {};
      const num = parts[metric.components?.numerator ?? ""] ?? {};
      const den = parts[metric.components?.denominator ?? ""] ?? {};
      const scale = metric.unit === "pct" ? 100 : 1;
      return years.map((y) =>
        aggregateRatio(
          num[String(y)] ?? [],
          den[String(y)] ?? [],
          scale,
          limit,
        ),
      );
    }
    return columns.map((col) => aggregateSeries(col, metric.aggregate, limit));
  };

  const values = summarize();
  const ytdValues = summarize(ytd ? comparedMonths : undefined);
  const deltas = values.slice(0, -1).map((_, i) => {
    const isLastPair = i === values.length - 2;
    const previous = isLastPair && ytd ? ytdValues[i] : values[i];
    const current = isLastPair && ytd ? ytdValues[i + 1] : values[i + 1];
    return yoyDelta(previous, current, opts);
  });

  return {
    rows,
    summary: { values, deltas, comparedMonths, ytd, excludesPartialMonth },
  };
}

/** Kolejność i nagłówki grup — spis treści sekcji i zarazem kontrakt `group`. */
export const YOY_GROUPS = [
  { id: "finanse", label: "Finanse" },
  { id: "hr", label: "HR" },
  { id: "dywersyfikacja", label: "Dywersyfikacja placementów" },
  { id: "operacyjne", label: "Wskaźniki operacyjne" },
] as const;
