// Kroki stawek kontraktu dla „Stawek w czasie” (zakładka „Pieniądze”, wariant A
// z 19.11.2026): tabela kroków, odcinki wykresu schodkowego i zdanie o zmianach.
//
// Harmonogram z API to wpisy „od dnia”. Przy tej samej dacie obowiązuje wpis
// dodany jako ostatni — backend (`_resolve_scheduled_rate`) rozstrzyga remis
// kolejnością dopisania, a API zwraca wpisy po `effective_from, id`. Wcześniejszy
// wpis z tą samą datą nigdy nie obowiązywał, więc tabela go nie pokazuje: zostaje
// po nim liczba w zdaniu „pominięto N wpisy zastąpione tego samego dnia” i jego
// notatka (mówi, skąd zmiana — przy aneksie stoi na pierwszym wpisie).
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatRateNumber } from "./rate-format";

export interface ScheduleEntry {
  id: number;
  rate: number;
  effective_from: string;
  note?: string | null;
  /** Krok z zamówienia klienta (tylko harmonogram stawki klienta). */
  source_order_id?: number | null;
}

/** Krok, który obowiązuje od `date` (ostatni wpis z tą datą). */
export interface LiveStep {
  id: number;
  date: string;
  rate: number;
  sourceOrderId: number | null;
  /** Notatki wszystkich wpisów z tą datą, także zastąpionych. */
  notes: string[];
}

export interface LiveSchedule {
  steps: LiveStep[];
  /** Wpisy zastąpione krokiem z tą samą datą. */
  superseded: number;
}

export function liveSchedule(entries: readonly ScheduleEntry[] | null | undefined): LiveSchedule {
  const dated = (entries ?? []).filter((entry) => Boolean(entry.effective_from));
  // Sortowanie stabilne: przy tej samej dacie zostaje kolejność z API.
  const sorted = [...dated].sort((a, b) => a.effective_from.localeCompare(b.effective_from));
  const byDate = new Map<string, LiveStep>();
  for (const entry of sorted) {
    const notes = byDate.get(entry.effective_from)?.notes ?? [];
    const note = entry.note?.trim();
    byDate.set(entry.effective_from, {
      id: entry.id,
      date: entry.effective_from,
      rate: entry.rate,
      sourceOrderId: entry.source_order_id ?? null,
      notes: note && !notes.includes(note) ? [...notes, note] : notes,
    });
  }
  return { steps: [...byDate.values()], superseded: sorted.length - byDate.size };
}

/**
 * Stawka w dniu `date`: ostatni krok nie późniejszy niż ten dzień. Przed
 * pierwszym krokiem harmonogram nie ma stawki (`null`), a pusty harmonogram
 * znaczy stawkę z kontraktu (`fallback`).
 */
export function rateOn(steps: readonly LiveStep[], date: string, fallback: number | null): number | null {
  if (steps.length === 0) return fallback;
  let value: number | null = null;
  for (const step of steps) {
    if (step.date > date) break;
    value = step.rate;
  }
  return value;
}

/**
 * Wpis obowiązujący `today` jak w backendzie: najpóźniejszy z datą nie
 * późniejszą niż dziś, a gdy wszystkie są przyszłe — najwcześniejszy; remis
 * wygrywa wpis dodany później.
 */
export function entryInEffect<T extends { effective_from: string }>(
  entries: readonly T[] | null | undefined,
  today: string,
): T | null {
  const dated = (entries ?? []).filter((entry) => Boolean(entry.effective_from));
  let past: T | null = null;
  let upcoming: T | null = null;
  for (const entry of dated) {
    if (entry.effective_from <= today) {
      if (past === null || entry.effective_from >= past.effective_from) past = entry;
    } else if (upcoming === null || entry.effective_from <= upcoming.effective_from) {
      upcoming = entry;
    }
  }
  return past ?? upcoming;
}

export type StepSource = "order" | "amendment" | "manual" | "manual_or_amendment";
export type StepState = "past" | "current" | "planned";

export const STEP_SOURCE_LABEL: Record<StepSource, string> = {
  order: "zamówienie",
  amendment: "aneks",
  manual: "ręcznie",
  // Aneksy nieznane (brak odczytu) — nie zgadujemy, jak karta przed 19.11.2026.
  manual_or_amendment: "ręcznie / aneks",
};

/** Aneks kontraktu z `GET /api/contracts/{id}/amendments` (potrzebne pola). */
export interface AmendmentRef {
  amendment_type: string;
  effective_date: string | null;
  withdrawn?: boolean | null;
}

export interface RateStepRow {
  date: string;
  client: number | null;
  candidate: number | null;
  clientChanged: boolean;
  candidateChanged: boolean;
  /** Wpis harmonogramu klienta z tego dnia; `null` = stawka sprzed tego dnia. */
  clientStepId: number | null;
  candidateStepId: number | null;
  source: StepSource;
  note: string | null;
  state: StepState;
}

// Notatka kroku z zamówienia powtarza źródło „zamówienie”.
const ORDER_NOTE = "Z zamówienia klienta";

function stepSource(
  date: string,
  clientStep: LiveStep | null,
  amendments: readonly AmendmentRef[] | null,
): StepSource {
  if (clientStep?.sourceOrderId != null) return "order";
  if (amendments === null) return "manual_or_amendment";
  const fromAmendment = amendments.some(
    (a) => !a.withdrawn && a.amendment_type === "rate_change" && a.effective_date === date,
  );
  return fromAmendment ? "amendment" : "manual";
}

/** Wiersz tabeli na każdy dzień zmiany stawki klienta albo kandydata. */
export function buildStepRows(input: {
  client: LiveSchedule;
  candidate: LiveSchedule;
  fallbackClient: number | null;
  fallbackCandidate: number | null;
  today: string;
  /** `null` = aneksy nieznane: krok bez zamówienia to „ręcznie / aneks”. */
  amendments: readonly AmendmentRef[] | null;
}): RateStepRow[] {
  const { client, candidate, fallbackClient, fallbackCandidate, today, amendments } = input;
  const dates = [...new Set([...client.steps, ...candidate.steps].map((step) => step.date))].sort();
  const currentDate = [...dates].reverse().find((date) => date <= today) ?? null;
  return dates.map((date, index) => {
    const previous = index > 0 ? dates[index - 1] : null;
    const clientStep = client.steps.find((step) => step.date === date) ?? null;
    const candidateStep = candidate.steps.find((step) => step.date === date) ?? null;
    const clientValue = rateOn(client.steps, date, fallbackClient);
    const candidateValue = rateOn(candidate.steps, date, fallbackCandidate);
    const notes = [...new Set([...(clientStep?.notes ?? []), ...(candidateStep?.notes ?? [])])].filter(
      (note) => note !== ORDER_NOTE,
    );
    return {
      date,
      client: clientValue,
      candidate: candidateValue,
      clientChanged: previous === null || rateOn(client.steps, previous, fallbackClient) !== clientValue,
      candidateChanged:
        previous === null || rateOn(candidate.steps, previous, fallbackCandidate) !== candidateValue,
      clientStepId: clientStep?.id ?? null,
      candidateStepId: candidateStep?.id ?? null,
      source: stepSource(date, clientStep, amendments),
      note: notes.length > 0 ? notes.join(" · ") : null,
      state: date > today ? "planned" : date === currentDate ? "current" : "past",
    };
  });
}

// ── Wykres ────────────────────────────────────────────────────────────────────

export interface ChartSegment {
  from: string;
  /** Dzień po ostatnim dniu odcinka (koniec osi przy ostatnim odcinku). */
  to: string;
  client: number | null;
  candidate: number | null;
}

export interface ChartAxis {
  start: string;
  end: string;
  startLabel: string;
  /** Pusty, gdy koniec osi to dziś albo zapas za ostatnim krokiem. */
  endLabel: string;
}

export interface ChartModel {
  segments: ChartSegment[];
  axis: ChartAxis;
}

export const DAY_MS = 86_400_000;

/** Północ UTC dnia „RRRR-MM-DD” — rachunek dni bez stref czasowych. */
export function isoToMs(iso: string): number {
  return Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);
}

export function msToIso(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

function addDays(iso: string, days: number): string {
  return msToIso(isoToMs(iso) + days * DAY_MS);
}

/**
 * Oś od pierwszego kroku harmonogramu do dziś albo do końca zamówienia (co
 * później); zaplanowany krok dostaje miesiąc zapasu, żeby było go widać.
 * Umowa, która już się skończyła, kończy oś na swoim końcu, nie na dziś.
 * Wykres ma sens od dwóch kroków — jeden krok to zdanie, nie wykres.
 */
export function buildChartModel(input: {
  rows: readonly RateStepRow[];
  today: string;
  contractStart: string | null;
  contractEnd: string | null;
  orderEnd: string | null;
}): ChartModel | null {
  const { rows, today, contractStart, contractEnd, orderEnd } = input;
  if (rows.length < 2) return null;
  const start = rows[0].date;
  const last = rows[rows.length - 1].date;
  const anchor = contractEnd && contractEnd < today ? contractEnd : today;
  const ends = [anchor, orderEnd, last >= anchor ? addDays(last, 31) : null]
    .filter((date): date is string => date != null && date > start)
    .sort();
  const end = ends[ends.length - 1] ?? addDays(last, 31);
  const inRange = rows.filter((row) => row.date < end);
  const segments = inRange.map((row, index) => ({
    from: row.date,
    to: inRange[index + 1]?.date ?? end,
    client: row.client,
    candidate: row.candidate,
  }));
  return {
    segments,
    axis: {
      start,
      end,
      startLabel: start === contractStart ? "start umowy" : "pierwsza stawka",
      endLabel: end === orderEnd ? "koniec zamówienia" : end === contractEnd ? "koniec umowy" : "",
    },
  };
}

interface ChangePoint {
  date: string;
  value: number;
  planned: boolean;
}

function changePoints(rows: readonly RateStepRow[], pick: (row: RateStepRow) => number | null): ChangePoint[] {
  const points: ChangePoint[] = [];
  let previous: number | null = null;
  for (const row of rows) {
    const value = pick(row);
    if (value != null && value !== previous) {
      points.push({ date: row.date, value, planned: row.state === "planned" });
    }
    previous = value;
  }
  return points;
}

function seriesPhrase(
  rows: readonly RateStepRow[],
  points: ChangePoint[],
  lead: string,
  missing: string,
  unit: string,
): string {
  if (points.length === 0) return missing;
  const amount = (point: ChangePoint) =>
    `${formatRateNumber(point.value)} ${unit}${point.planned ? " (zaplanowana)" : ""}`;
  const [first, ...rest] = points;
  const head = `${lead} ${first.date === rows[0].date ? "" : `od ${formatIsoDatePl(first.date)} `}${amount(first)}`;
  if (rest.length === 0) return `${head} bez zmian`;
  return [head, ...rest.map((point) => `od ${formatIsoDatePl(point.date)} ${amount(point)}`)].join(", ");
}

/** Opis wykresu dla czytnika ekranu: zdanie o zmianach obu stawek. */
export function describeRateChanges(
  rows: readonly RateStepRow[],
  units: { client: string; candidate: string },
): string {
  if (rows.length === 0) return "Harmonogram stawek jest pusty.";
  const client = seriesPhrase(
    rows,
    changePoints(rows, (row) => row.client),
    "klient płaci",
    "bez stawki klienta",
    units.client,
  );
  const candidate = seriesPhrase(
    rows,
    changePoints(rows, (row) => row.candidate),
    "kandydat dostaje",
    "bez stawki kandydata",
    units.candidate,
  );
  return `Stawki od ${formatIsoDatePl(rows[0].date)}: ${client}; ${candidate}. Kwoty są też w tabeli pod wykresem.`;
}
