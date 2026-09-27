// Termin prepu względem rozmowy u klienta (runda 10, F08).
//
// Do 27.09.2026 okno „Zaplanuj Prep” proponowało zawsze najbliższy dzień
// roboczy o 10:00 (a zapasowe okno — najbliższą pełną godzinę), więc prep
// potrafił wypaść dokładnie na rozmowę u klienta. Prep ma sens tylko PRZED
// rozmową: tu jest podpowiedź terminu i ostrzeżenie o kolizji albo kolejności.

import type { CycleOverview } from "@/lib/interview-cycle";

/** Rozmowa u klienta, do której robi się prep. `end` pusty = 60 min. */
export interface PrepInterview {
  start: string;
  end?: string | null;
}

const DEFAULT_INTERVIEW_MINUTES = 60;
const MIN_LEAD_MINUTES = 15;

const pad = (n: number) => String(n).padStart(2, "0");

/** `Date` → wartość pola `datetime-local` (czas przeglądarki). */
export function toLocalInput(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function isWeekend(d: Date): boolean {
  return d.getDay() === 0 || d.getDay() === 6;
}

/** Najbliższy dzień roboczy od jutra o danej godzinie (dotychczasowa podpowiedź). */
export function nextWorkdayAt(hour: number, now: Date = new Date()): string {
  const d = new Date(now);
  d.setDate(d.getDate() + 1);
  while (isWeekend(d)) d.setDate(d.getDate() + 1);
  d.setHours(hour, 0, 0, 0);
  return toLocalInput(d);
}

function previousWorkdayAt(day: Date, hour: number): Date {
  const d = new Date(day);
  d.setDate(d.getDate() - 1);
  while (isWeekend(d)) d.setDate(d.getDate() - 1);
  d.setHours(hour, 0, 0, 0);
  return d;
}

function floorToQuarter(d: Date): Date {
  const out = new Date(d);
  out.setMinutes(out.getMinutes() - (out.getMinutes() % 15), 0, 0);
  return out;
}

function ceilToQuarter(d: Date): Date {
  const out = new Date(d);
  out.setSeconds(0, 0);
  const rest = out.getMinutes() % 15;
  if (rest) out.setMinutes(out.getMinutes() + (15 - rest));
  return out;
}

function interviewWindow(interview: PrepInterview): { start: Date; end: Date } | null {
  const start = new Date(interview.start);
  if (Number.isNaN(start.getTime())) return null;
  const end = interview.end ? new Date(interview.end) : null;
  return {
    start,
    end:
      end && !Number.isNaN(end.getTime()) && end > start
        ? end
        : new Date(start.getTime() + DEFAULT_INTERVIEW_MINUTES * 60_000),
  };
}

/**
 * Podpowiedź terminu prepu (wartość pola `datetime-local`).
 *
 * - Prep 1 (prowadzi DL): poprzedni dzień roboczy przed rozmową, 10:00.
 * - Prep 2 (rekruter): 2 godziny przed rozmową.
 * Gdy taki termin już minął, najpóźniejszy możliwy przed rozmową; gdy rozmowy
 * nie ma albo już się zaczęła — dotychczasowa podpowiedź (jutro, 10:00).
 */
export function defaultPrepStart(
  interview: PrepInterview | null | undefined,
  prepNo: 1 | 2,
  durationMinutes: number,
  now: Date = new Date(),
): string {
  const win = interview ? interviewWindow(interview) : null;
  if (!win || win.start <= now) return nextWorkdayAt(10, now);
  const earliest = new Date(now.getTime() + MIN_LEAD_MINUTES * 60_000);
  const latest = new Date(win.start.getTime() - durationMinutes * 60_000);
  const candidates: Date[] = [];
  if (prepNo === 1) candidates.push(previousWorkdayAt(win.start, 10));
  candidates.push(floorToQuarter(new Date(win.start.getTime() - 120 * 60_000)));
  candidates.push(floorToQuarter(latest));
  for (const c of candidates) {
    if (c >= earliest && c <= latest) return toLocalInput(c);
  }
  // Na prep przed rozmową brakuje czasu — najbliższy kwadrans; okno ostrzeże.
  return toLocalInput(ceilToQuarter(earliest));
}

const WHEN = new Intl.DateTimeFormat("pl-PL", {
  weekday: "short",
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});
const TIME = new Intl.DateTimeFormat("pl-PL", { hour: "2-digit", minute: "2-digit" });

/** „pon., 28.09, 10:00–11:00” — rozmowa w komunikacie ostrzeżenia. */
function windowLabel(win: { start: Date; end: Date }): string {
  return `${WHEN.format(win.start)}–${TIME.format(win.end)}`;
}

/**
 * Ostrzeżenie o terminie prepu względem rozmowy u klienta albo `null`.
 * Nie blokuje zapisu — prep po rozmowie bywa świadomy (przełożona rozmowa),
 * ale człowiek ma to widzieć przed wysłaniem zaproszenia.
 */
export function prepTimingWarning(
  startLocal: string,
  durationMinutes: number,
  interview: PrepInterview | null | undefined,
): string | null {
  const win = interview ? interviewWindow(interview) : null;
  const start = new Date(startLocal);
  if (!win || Number.isNaN(start.getTime())) return null;
  const end = new Date(start.getTime() + durationMinutes * 60_000);
  if (start >= win.end) {
    return `Prep wypada po rozmowie u klienta (${windowLabel(win)}) — zaplanuj go przed rozmową.`;
  }
  if (end > win.start) {
    return `Prep nakłada się na rozmowę u klienta (${windowLabel(win)}) — przesuń go przed rozmowę.`;
  }
  return null;
}

/**
 * Zaplanowana (przyszła) rozmowa z kroków cyklu — tam, gdzie widok ma tylko
 * kroki (Tablica, dok osoby). `end` dokłada wołający, jeśli go zna.
 */
export function scheduledInterviewFromSteps(
  steps: ReadonlyArray<{ key: string; state: string; at?: string | null }> | null | undefined,
): PrepInterview | null {
  const step = steps?.find((s) => s.key === "interview" && s.state === "scheduled");
  return step?.at ? { start: step.at } : null;
}

/** Rozmowa, do której prep robi się z ekranu „Rozmowy u klienta” (z końcem z agendy). */
export function prepInterviewForPair(
  data: CycleOverview | null | undefined,
  pair: { candidate_id: number; job_id: number },
): PrepInterview | null {
  const item = data?.items.find(
    (i) => i.candidate_id === pair.candidate_id && i.job_id === pair.job_id,
  );
  const step = item?.steps.find((s) => s.key === "interview" && s.state === "scheduled");
  if (!step?.at) return null;
  const entry = data?.agenda.find(
    (a) => a.kind === "interview" && step.event_id != null && a.event_id === step.event_id,
  );
  return { start: step.at, end: entry?.end ?? null };
}
