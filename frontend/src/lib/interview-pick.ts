/**
 * Okno „Umów rozmowę i prepy” (20.10.2026, PR 2) — logika bez Reacta.
 *
 * Rekruter po telefonie do kandydata wybiera termin od klienta (w oknie
 * klienta także godzinę) i od razu godziny obu prepów z podpowiedzi serwera.
 * Godziny pól liczymy w czasie przeglądarki, jak reszta okien terminów.
 */
import type { SlotItem } from "@/lib/interview-cycle";

const pad = (n: number) => String(n).padStart(2, "0");

export function hhmm(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function isWindow(slot: SlotItem): boolean {
  return Boolean(slot.window_end && slot.end && new Date(slot.window_end) > new Date(slot.end));
}

/** Najwcześniejsza i najpóźniejsza godzina startu rozmowy w oknie klienta. */
export function windowBounds(slot: SlotItem, durationMinutes: number): { from: string; to: string } | null {
  if (!isWindow(slot)) return null;
  const latest = new Date(new Date(slot.window_end as string).getTime() - durationMinutes * 60_000);
  return { from: hhmm(slot.start), to: hhmm(latest.toISOString()) };
}

const QUARTER_MS = 15 * 60_000;

/**
 * Najwcześniejsza godzina startu w oknie klienta, która jeszcze nie minęła
 * (audyt 22.10.2026, F36): okno, które już trwa, zaczyna się od „teraz”
 * w górę do pełnego kwadransa, a nie od minionego początku okna (serwer
 * odrzuca taki start: 422 „Ten termin już minął”). Domyślna wartość i `min`
 * pola „Godzina z kandydatem”.
 */
export function windowEarliest(slot: SlotItem, durationMinutes: number, now: Date = new Date()): string | null {
  const bounds = windowBounds(slot, durationMinutes);
  if (!bounds) return null;
  const next = new Date(Math.ceil(now.getTime() / QUARTER_MS) * QUARTER_MS);
  const latest = new Date(slot.window_end as string).getTime() - durationMinutes * 60_000;
  if (next.getTime() <= new Date(slot.start).getTime() || next.getTime() > latest) return bounds.from;
  return hhmm(next.toISOString());
}

/** Tolerancja jak po stronie serwera (`normalize_slots`, `_ensure_slot_ahead`). */
const PAST_TOLERANCE_MS = 5 * 60_000;

/**
 * Termin od klienta już minął (audyt 21.10.2026): od 0487 wybór od razu
 * wpisuje rozmowę do kalendarza, więc minionego terminu nie da się wybrać
 * (serwer odpowiada 422). Okno klienta mija, gdy nie zmieści się już w nim
 * rozmowa.
 */
export function slotPassed(slot: SlotItem, durationMinutes: number, now: Date = new Date()): boolean {
  const latest = isWindow(slot)
    ? new Date(slot.window_end as string).getTime() - durationMinutes * 60_000
    : new Date(slot.start).getTime();
  return latest < now.getTime() - PAST_TOLERANCE_MS;
}

/**
 * Start rozmowy dla wybranego terminu: zwykły termin — jego start; okno —
 * dzień okna i godzina z pola. `null`, gdy godzina jest pusta albo poza oknem.
 */
export function interviewStart(slot: SlotItem, time: string, durationMinutes: number): string | null {
  const bounds = windowBounds(slot, durationMinutes);
  if (!bounds) return new Date(slot.start).toISOString();
  if (!/^\d{2}:\d{2}$/.test(time) || time < bounds.from || time > bounds.to) return null;
  const day = new Date(slot.start);
  const [h, m] = time.split(":").map(Number);
  day.setHours(h, m, 0, 0);
  return day.toISOString();
}

const WHEN = new Intl.DateTimeFormat("pl-PL", {
  timeZone: "Europe/Warsaw",
  weekday: "short",
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

/** „śr., 21.10, 16:00” — etykieta godziny prepu. */
export function prepWhen(iso: string): string {
  return WHEN.format(new Date(iso));
}

/** Czy dwa przedziały ISO na siebie nachodzą (Prep 1 i Prep 2 jednocześnie). */
export function overlaps(a: { start: string; end: string }, b: { start: string; end: string }): boolean {
  return new Date(a.start) < new Date(b.end) && new Date(b.start) < new Date(a.end);
}

/** Okno kandydata „od–do” jest poprawne albo puste (wtedy godziny pracy). */
export function candidateWindowError(from: string, to: string): string | null {
  if (from && to && to <= from) return "Koniec musi być po początku.";
  return null;
}

// ── „Inna godzina…” prepu (22.10.2026) ──────────────────────────────────────
// Rekruter wpisuje prep spoza podpowiedzi. Reguły jak w `prep_availability`
// na serwerze: przed rozmową (blokada), bez nakładania na drugi prep
// (blokada), zapas przed rozmową, godziny pracy i 2 h od teraz (ostrzeżenia).
// Zajęte u prowadzącego to ostrzeżenie, nie blokada (decyzja Artura) — serwer
// sprawdza je jeszcze raz przy zapisie (`accept_busy`).

export interface Span {
  start: string;
  end: string;
}

export interface ManualPrepCheck {
  /** Zapisać się nie da. */
  blocks: string[];
  /** Da się zapisać, ale trzeba wiedzieć. */
  warnings: string[];
  /** Zajęty przedział prowadzącego, na który wpada prep. */
  busy: Span | null;
}

const PREP_GAP_MINUTES: Record<1 | 2, number> = { 1: 120, 2: 30 };
const MIN_LEAD_MS = 2 * 60 * 60_000;
const WORK_START_MIN = 8 * 60;
const WORK_END_MIN = 18 * 60;
const GRID_MINUTES = 30;

const DAY = new Intl.DateTimeFormat("pl-PL", { weekday: "short", day: "2-digit", month: "2-digit" });

/** `Date` → `RRRR-MM-DD` w czasie przeglądarki (jak pola godzin). */
export function localDay(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function parseDay(day: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}

/**
 * Dni do wyboru: dni robocze od dziś do dnia rozmowy, najwyżej `max`
 * ostatnich przed rozmową (rozmowa bywa za kilka tygodni).
 */
export function prepDays(
  interviewStart: string,
  now: Date = new Date(),
  max = 10,
): { value: string; label: string }[] {
  const interviewDay = localDay(new Date(interviewStart));
  const today = localDay(now);
  const cursor = new Date(interviewStart);
  cursor.setHours(12, 0, 0, 0);
  const out: { value: string; label: string }[] = [];
  while (out.length < max && localDay(cursor) >= today) {
    const weekday = cursor.getDay();
    if (weekday !== 0 && weekday !== 6) {
      const value = localDay(cursor);
      const note = value === interviewDay ? " (rozmowa)" : value === today ? " (dziś)" : "";
      out.push({ value, label: `${DAY.format(cursor)}${note}` });
    }
    cursor.setDate(cursor.getDate() - 1);
  }
  return out.reverse();
}

/** Dzień i godzina z pól → ISO; `null`, gdy któreś pole jest puste albo złe. */
export function manualStart(day: string, time: string): string | null {
  const date = parseDay(day);
  if (!date || !/^\d{2}:\d{2}$/.test(time)) return null;
  const [h, m] = time.split(":").map(Number);
  if (h > 23 || m > 59) return null;
  date.setHours(h, m, 0, 0);
  return date.toISOString();
}

function plusMinutes(iso: string, minutes: number): string {
  return new Date(new Date(iso).getTime() + minutes * 60_000).toISOString();
}

export function spanOf(start: string, minutes: number): Span {
  return { start, end: plusMinutes(start, minutes) };
}

/** Zajęte bloki, na które wpada prep, połączone w jeden przedział. */
export function busyOverlap(span: Span, busy: Span[]): Span | null {
  const hits = busy.filter((b) => overlaps(span, b));
  if (!hits.length) return null;
  const start = hits.reduce((a, b) => (new Date(b.start) < new Date(a) ? b.start : a), hits[0].start);
  const end = hits.reduce((a, b) => (new Date(b.end) > new Date(a) ? b.end : a), hits[0].end);
  return { start, end };
}

function minutesLabel(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

function minuteOfDay(d: Date): number {
  return d.getHours() * 60 + d.getMinutes();
}

export function checkManualPrep({
  prepNo,
  start,
  minutes,
  interviewStart,
  busy,
  organizerName,
  other,
  now = new Date(),
}: {
  prepNo: 1 | 2;
  start: string;
  minutes: number;
  interviewStart: string;
  /** `null` = kalendarza prowadzącego nie widać. */
  busy: Span[] | null;
  organizerName: string;
  /** Drugi prep tej osoby (wybrany albo już zaplanowany). */
  other: (Span & { prepNo: number }) | null;
  now?: Date;
}): ManualPrepCheck {
  const span = spanOf(start, minutes);
  const s = new Date(span.start);
  const e = new Date(span.end);
  const interview = new Date(interviewStart);
  const blocks: string[] = [];
  const warnings: string[] = [];

  if (s.getTime() < now.getTime()) blocks.push("Ta godzina już minęła.");
  if (e > interview) {
    blocks.push(`Prep musi skończyć się przed rozmową u klienta (${prepWhen(interviewStart)}).`);
  }
  if (other && overlaps(span, other)) {
    blocks.push(
      `W tym czasie jest Prep ${other.prepNo} (${prepWhen(other.start)}–${hhmm(other.end)}). ` +
        "Kandydat nie będzie na dwóch naraz.",
    );
  }

  const clash = busy ? busyOverlap(span, busy) : null;
  if (clash) {
    warnings.push(
      `${organizerName} ma wtedy zajęte (${hhmm(clash.start)}–${hhmm(clash.end)}). Możesz zapisać, jeśli to uzgodnione.`,
    );
  }
  const required = PREP_GAP_MINUTES[prepNo];
  const gap = Math.round((interview.getTime() - e.getTime()) / 60_000);
  if (gap >= 0 && gap < required) {
    warnings.push(
      `Prep ${prepNo} kończy się ${minutesLabel(gap)} przed rozmową — zwykle zostawiamy ${minutesLabel(required)}.`,
    );
  }
  if (localDay(s) !== localDay(e) || minuteOfDay(s) < WORK_START_MIN || minuteOfDay(e) > WORK_END_MIN) {
    warnings.push("Poza godzinami pracy (8:00–18:00).");
  }
  if (s.getTime() >= now.getTime() && s.getTime() - now.getTime() < MIN_LEAD_MS) {
    warnings.push("Prep za mniej niż 2 h — kandydat może nie zdążyć odebrać zaproszenia.");
  }
  return { blocks, warnings, busy: clash };
}

/**
 * Najbliższe wolne starty tego dnia (siatka co 30 min w godzinach pracy) —
 * podpowiedź pod ostrzeżeniem „ma wtedy zajęte”.
 */
export function nearestFreeStarts({
  day,
  around,
  minutes,
  interviewStart,
  busy,
  other,
  now = new Date(),
  limit = 2,
}: {
  day: string;
  around: string;
  minutes: number;
  interviewStart: string;
  busy: Span[];
  other: Span | null;
  now?: Date;
  limit?: number;
}): string[] {
  const base = parseDay(day);
  if (!base) return [];
  const interview = new Date(interviewStart).getTime();
  const target = new Date(around).getTime();
  const out: string[] = [];
  for (let m = WORK_START_MIN; m + minutes <= WORK_END_MIN; m += GRID_MINUTES) {
    const s = new Date(base);
    s.setHours(0, m, 0, 0);
    const span = spanOf(s.toISOString(), minutes);
    if (s.getTime() < now.getTime() + MIN_LEAD_MS) continue;
    if (new Date(span.end).getTime() > interview) continue;
    if (busy.some((b) => overlaps(span, b)) || (other && overlaps(span, other))) continue;
    out.push(span.start);
  }
  return out
    .sort((a, b) => Math.abs(new Date(a).getTime() - target) - Math.abs(new Date(b).getTime() - target))
    .slice(0, limit)
    .sort();
}

export interface DayStrip {
  ticks: { label: string; left: number }[];
  busy: { left: number; width: number }[];
  chosen: { left: number; width: number } | null;
}

/**
 * Pasek dnia prowadzącego: zajęte bloki i wpisany prep w procentach szerokości.
 * Zakres 8–18, poszerzony, gdy prep wypada poza godziny pracy.
 */
export function dayStrip(day: string, busy: Span[], chosen: Span | null): DayStrip | null {
  const base = parseDay(day);
  if (!base) return null;
  let from = WORK_START_MIN;
  let to = WORK_END_MIN;
  if (chosen && localDay(new Date(chosen.start)) === day) {
    from = Math.min(from, Math.floor(minuteOfDay(new Date(chosen.start)) / 60) * 60);
    const endDay = localDay(new Date(chosen.end)) === day;
    to = Math.max(to, endDay ? Math.ceil(minuteOfDay(new Date(chosen.end)) / 60) * 60 : 24 * 60);
  }
  const dayStart = base.getTime();
  const range = to - from;
  const place = (span: Span) => {
    const s = Math.max((new Date(span.start).getTime() - dayStart) / 60_000, from);
    const e = Math.min((new Date(span.end).getTime() - dayStart) / 60_000, to);
    if (e <= s) return null;
    return { left: ((s - from) / range) * 100, width: ((e - s) / range) * 100 };
  };
  const ticks: { label: string; left: number }[] = [];
  for (let m = from; m <= to; m += 120) ticks.push({ label: `${m / 60}:00`, left: ((m - from) / range) * 100 });
  return {
    ticks,
    busy: busy.map(place).filter((b): b is { left: number; width: number } => b != null),
    chosen: chosen ? place(chosen) : null,
  };
}
