/**
 * Czysta logika widoków Insights (przebudowa 24.09.2026): zdania, delty,
 * najsłabsze przejście lejka, okno porównania.
 *
 * Widoki pokazują kilka liczb i JEDNO zdanie wniosku. Zdanie buduje kod tutaj,
 * a nie komponent — inaczej reguła „co jest wnioskiem" żyłaby w JSX-ie i nie
 * dałaby się przetestować bez renderu.
 */

export type Tone = "good" | "bad" | "neutral";

export interface Delta {
  text: string;
  tone: Tone;
}

/** „▲ 4 więcej niż w sierpniu" / „▼ 9% mniej…" / „bez zmian". `null` = brak danych. */
export function countDelta(
  current: number | null | undefined,
  previous: number | null | undefined,
  previousLabel: string,
  opts: { lowerIsBetter?: boolean } = {},
): Delta | null {
  if (current == null || previous == null) return null;
  const diff = current - previous;
  if (diff === 0) return { text: `tyle samo co ${previousLabel}`, tone: "neutral" };
  const up = diff > 0;
  const better = opts.lowerIsBetter ? !up : up;
  const abs = Math.abs(diff);
  return {
    text: `${up ? "▲" : "▼"} ${abs} ${up ? "więcej" : "mniej"} niż ${previousLabel}`,
    tone: better ? "good" : "bad",
  };
}

/** Procent przejścia z kroku na krok; `null` = zerowy mianownik (nie 0%). */
export function stepConversions(counts: readonly number[]): Array<number | null> {
  return counts.map((value, i) => {
    if (i === 0) return null;
    const prev = counts[i - 1];
    if (!prev) return null;
    return Math.round((100 * value) / prev);
  });
}

export interface FunnelStep {
  label: string;
  count: number;
  /** Procent przejścia z poprzedniego kroku; `null` dla pierwszego. */
  conversion: number | null;
}

export function buildSteps(
  labels: readonly string[],
  counts: readonly number[],
): FunnelStep[] {
  const conv = stepConversions(counts);
  return labels.map((label, i) => ({
    label,
    count: counts[i] ?? 0,
    conversion: conv[i] ?? null,
  }));
}

/**
 * Indeks kroku z najniższym przejściem. Pomija pierwszy krok i kroki bez
 * mianownika. Remis → wcześniejszy krok (to on odcina resztę lejka).
 */
export function weakestStepIndex(steps: readonly FunnelStep[]): number | null {
  let best: number | null = null;
  let bestValue = Infinity;
  for (let i = 1; i < steps.length; i += 1) {
    const value = steps[i].conversion;
    if (value !== null && value < bestValue) {
      best = i;
      bestValue = value;
    }
  }
  return best;
}

export function weakestStepSentence(
  steps: readonly FunnelStep[],
  opts: { previous?: readonly FunnelStep[]; previousLabel?: string } = {},
): string | null {
  const i = weakestStepIndex(steps);
  if (i === null) return null;
  const from = steps[i - 1].label;
  const to = steps[i].label;
  const prev = opts.previous?.[i]?.conversion;
  const tail =
    prev != null && opts.previousLabel
      ? ` (${opts.previousLabel} ${prev}%)`
      : "";
  return `Najwięcej osób odpada między etapem „${from}” a „${to}” — przechodzi ${steps[i].conversion}%${tail}.`;
}

/**
 * Krok, na którym osoba traci najwięcej względem zespołu (w punktach
 * procentowych). Zwraca `null`, gdy żadna różnica nie przekracza progu —
 * zdanie „jesteś gorszy o 1 pp" byłoby szumem.
 */
export function biggestGapVsTeam(
  mine: readonly FunnelStep[],
  team: readonly FunnelStep[],
  minGapPp = 5,
): { index: number; mine: number; team: number } | null {
  let result: { index: number; mine: number; team: number } | null = null;
  let widest = 0;
  for (let i = 1; i < mine.length; i += 1) {
    const own = mine[i].conversion;
    const t = team[i]?.conversion;
    if (own === null || t == null) continue;
    const gap = t - own;
    if (gap >= minGapPp && gap > widest) {
      widest = gap;
      result = { index: i, mine: own, team: t };
    }
  }
  return result;
}

export function gapSentence(
  mine: readonly FunnelStep[],
  team: readonly FunnelStep[],
): string | null {
  const gap = biggestGapVsTeam(mine, team);
  if (!gap) return null;
  const from = mine[gap.index - 1].label;
  const to = mine[gap.index].label;
  return `Najwięcej tracisz między etapem „${from}” a „${to}”: ${gap.mine}%, w zespole ${gap.team}%.`;
}

function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/**
 * Ten sam odcinek poprzedniego miesiąca: 1–24 września → 1–24 sierpnia.
 * Gdy poprzedni miesiąc jest krótszy (31 marca → luty), koniec to jego
 * ostatni dzień. Porównanie 24 dni z pełnym miesiącem dałoby spadek, którego
 * nie ma.
 */
export function previousSameStretch(today: Date): {
  date_from: string;
  date_to: string;
} {
  const firstPrev = new Date(today.getFullYear(), today.getMonth() - 1, 1);
  const lastPrev = new Date(today.getFullYear(), today.getMonth(), 0);
  const end = new Date(
    firstPrev.getFullYear(),
    firstPrev.getMonth(),
    Math.min(today.getDate(), lastPrev.getDate()),
  );
  return { date_from: isoDate(firstPrev), date_to: isoDate(end) };
}

const MONTHS_LOCATIVE = [
  "styczniu",
  "lutym",
  "marcu",
  "kwietniu",
  "maju",
  "czerwcu",
  "lipcu",
  "sierpniu",
  "wrześniu",
  "październiku",
  "listopadzie",
  "grudniu",
];

const MONTHS_GENITIVE = [
  "stycznia",
  "lutego",
  "marca",
  "kwietnia",
  "maja",
  "czerwca",
  "lipca",
  "sierpnia",
  "września",
  "października",
  "listopada",
  "grudnia",
];

/** „sierpnia" — dopełniacz nazwy miesiąca (0 = styczeń). */
export function monthGenitive(monthIndex: number): string {
  return MONTHS_GENITIVE[((monthIndex % 12) + 12) % 12];
}

/** „w dniach 1–24 sierpnia" — ten sam odcinek poprzedniego miesiąca. */
export function sameStretchLabel(today: Date): string {
  const { date_to } = previousSameStretch(today);
  const lastDay = Number(date_to.slice(8, 10));
  const idx = (today.getMonth() + 11) % 12;
  return lastDay === 1
    ? `1 ${MONTHS_GENITIVE[idx]}`.replace(/^/, "w dniu ")
    : `w dniach 1–${lastDay} ${MONTHS_GENITIVE[idx]}`;
}

/** „w sierpniu" — do zdań porównujących z poprzednim miesiącem. */
export function inPreviousMonth(today: Date): string {
  const idx = (today.getMonth() + 11) % 12;
  return `w ${MONTHS_LOCATIVE[idx]}`;
}

const MONTHS_NOMINATIVE = [
  "Styczeń",
  "Luty",
  "Marzec",
  "Kwiecień",
  "Maj",
  "Czerwiec",
  "Lipiec",
  "Sierpień",
  "Wrzesień",
  "Październik",
  "Listopad",
  "Grudzień",
];

/** „Wrzesień 2026 · trwa, 24 z 30 dni". */
export function currentMonthCaption(today: Date): string {
  const days = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  return `${MONTHS_NOMINATIVE[today.getMonth()]} ${today.getFullYear()} · trwa, ${today.getDate()} z ${days} dni`;
}

/** „1 placement", „2 placementy", „5 placementów". */
export function placementsPl(n: number): string {
  if (n === 1) return "placement";
  const last = n % 10;
  const lastTwo = n % 100;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) {
    return "placementy";
  }
  return "placementów";
}

export interface MyMonthFacts {
  placements: number;
  placementsTarget: number;
  /** Pozycja w wyścigu placementów; `null` = poza rankingiem. */
  raceRank: number | null;
  /** Placementy lidera wyścigu (zakwalifikowanego albo pierwszego). */
  leaderPlacements: number | null;
  leaderName: string | null;
  verificationsToday: number;
  verificationsDailyTarget: number;
}

/** Zdanie na górze „Mojego miesiąca" — jeden wniosek, bez tabelki. */
export function myMonthSentence(f: MyMonthFacts): string {
  const parts: string[] = [];
  parts.push(`Masz ${f.placements} ${placementsPl(f.placements)} w tym miesiącu`);
  if (f.placementsTarget > 0) {
    parts[0] +=
      f.placements >= f.placementsTarget
        ? " — cel osiągnięty"
        : ` — do celu brakuje ${f.placementsTarget - f.placements}`;
  }
  parts[0] += ".";
  if (f.raceRank !== null) {
    if (f.raceRank === 1) {
      parts.push("Prowadzisz w wyścigu placementów.");
    } else if (f.leaderPlacements !== null && f.leaderName) {
      const gap = Math.max(f.leaderPlacements - f.placements, 0);
      parts.push(
        `Jesteś ${f.raceRank}. w wyścigu placementów — do prowadzenia (${f.leaderName}) brakuje Ci ${gap}.`,
      );
    } else {
      parts.push(`Jesteś ${f.raceRank}. w wyścigu placementów.`);
    }
  }
  if (f.verificationsDailyTarget > 0) {
    parts.push(
      f.verificationsToday >= f.verificationsDailyTarget
        ? `Dzisiejszy cel weryfikacji zrobiony (${f.verificationsToday}).`
        : `Dziś ${f.verificationsToday} z ${f.verificationsDailyTarget} weryfikacji.`,
    );
  }
  return parts.join(" ");
}

export interface ShareRow {
  name: string;
  value: number | null;
}

/**
 * Top N klientów + „pozostali" i udział top 3 w całości. Wiersze bez kwoty
 * (brak kursu, brak nogi) nie wchodzą do sumy — i nie udają zera.
 */
export function topWithRest(
  rows: readonly ShareRow[],
  n: number,
): {
  top: Array<ShareRow & { share: number | null }>;
  rest: number;
  total: number;
  top3Share: number | null;
} {
  const priced = rows
    .filter((r): r is ShareRow & { value: number } => r.value !== null)
    .sort((a, b) => b.value - a.value);
  const total = priced.reduce((sum, r) => sum + r.value, 0);
  const share = (v: number) => (total > 0 ? Math.round((100 * v) / total) : null);
  const top = priced.slice(0, n).map((r) => ({ ...r, share: share(r.value) }));
  const rest = priced.slice(n).reduce((sum, r) => sum + r.value, 0);
  const top3 = priced.slice(0, 3).reduce((sum, r) => sum + r.value, 0);
  return { top, rest, total, top3Share: share(top3) };
}

export interface ComparablePeriod {
  params: {
    period: "month" | "quarter" | "year" | "week" | "custom";
    offset?: number;
    date_from?: string;
    date_to?: string;
  };
  /** „w sierpniu", „w poprzednim kwartale" — do zdania delty. */
  label: string;
}

/**
 * Z czym porównać wybrany okres. Bieżący miesiąc → ten sam odcinek
 * poprzedniego miesiąca; każdy inny okres kalendarzowy → cały poprzedni
 * okres tej samej długości. Zakres własny nie ma naturalnego poprzednika —
 * wtedy bez porównania (`null`), zamiast zgadywać.
 */
export function previousComparablePeriod(
  p: { period: string; offset?: number },
  today: Date,
): ComparablePeriod | null {
  const offset = p.offset ?? 0;
  if (p.period === "month" && offset === 0) {
    return {
      params: { period: "custom", ...previousSameStretch(today) },
      label: sameStretchLabel(today),
    };
  }
  const labels: Record<string, string> = {
    week: "w poprzednim tygodniu",
    month: "w poprzednim miesiącu",
    quarter: "w poprzednim kwartale",
    year: "w poprzednim roku",
  };
  if (!(p.period in labels)) return null;
  return {
    params: {
      period: p.period as "week" | "month" | "quarter" | "year",
      offset: offset - 1,
    },
    label: labels[p.period],
  };
}

/** „3,41 mln zł", „612 tys. zł", „980 zł"; `null` → „—". */
export function compactPln(value: number | null | undefined): string {
  if (value == null) return "—";
  const abs = Math.abs(value);
  const fmt = (v: number, digits: number) =>
    v.toLocaleString("pl-PL", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  if (abs >= 1_000_000) return `${fmt(value / 1_000_000, 2)} mln zł`;
  if (abs >= 10_000) return `${fmt(value / 1_000, 0)} tys. zł`;
  return `${fmt(value, 0)} zł`;
}

/** Delta procentowa z `InsightsDelta` serwera: „▲ 4% wobec poprzedniego kwartału". */
export function pctDelta(
  changePct: number | null | undefined,
  label: string,
  opts: { lowerIsBetter?: boolean } = {},
): Delta | null {
  if (changePct == null) return null;
  const rounded = Math.round(changePct);
  if (rounded === 0) return { text: `bez zmian ${label}`, tone: "neutral" };
  const up = rounded > 0;
  const better = opts.lowerIsBetter ? !up : up;
  return {
    text: `${up ? "▲" : "▼"} ${Math.abs(rounded)}% ${label}`,
    tone: better ? "good" : "bad",
  };
}

/**
 * Suma od stycznia do ostatniego PEŁNEGO miesiąca w obu latach — to samo
 * okno po obu stronach. Miesiąc w toku nie wchodzi (kilka dni przeciw pełnemu
 * miesiącowi dałoby fałszywy spadek).
 */
export function yearToDate(
  current: ReadonlyArray<number | null>,
  previous: ReadonlyArray<number | null>,
  fullMonths: number,
): { current: number; previous: number } | null {
  if (fullMonths <= 0) return null;
  const sum = (xs: ReadonlyArray<number | null>) =>
    xs.slice(0, fullMonths).reduce<number>((acc, v) => acc + (v ?? 0), 0);
  return { current: sum(current), previous: sum(previous) };
}
