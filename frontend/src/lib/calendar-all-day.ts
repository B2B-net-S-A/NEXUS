/**
 * Wpisy całodniowe (urlop, OOO) w siatce tygodnia.
 *
 * Backend zapisuje je jako „pływającą datę" (`services/calendar_all_day.py`):
 * `start_time` = północ UTC dnia startu, `end_time` = północ UTC dnia PO
 * ostatnim dniu (koniec wyłączny). Tu czytamy z tych wartości SAME DATY —
 * `new Date(iso)` w strefie przeglądarki przesunąłby wpis o dzień dla każdego,
 * kto nie siedzi w UTC.
 *
 * Do 09.2026 taki wpis był rysowany jako blok 00:00–24:00: zajmował pas
 * w kolumnie dnia, zwężał rozmowy i generował fałszywe kolizje.
 */

export interface AllDayLike {
  all_day?: boolean | null;
  start_time: string;
  end_time?: string | null;
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})/;

/** `YYYY-MM-DD` z ISO zapisanym przez backend (część daty UTC). */
function isoDatePart(iso: string): string | null {
  const m = ISO_DATE.exec(iso);
  return m ? `${m[1]}-${m[2]}-${m[3]}` : null;
}

/** Data lokalna dnia w siatce jako `YYYY-MM-DD`. */
export function localDateKey(day: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

function addDays(key: string, days: number): string {
  const [y, m, d] = key.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d + days));
  return date.toISOString().slice(0, 10);
}

/** Pierwszy dzień i dzień PO ostatnim (wyłączny) — w formacie `YYYY-MM-DD`. */
export function allDayRange(ev: AllDayLike): { first: string; endExclusive: string } | null {
  const first = isoDatePart(ev.start_time);
  if (!first) return null;
  const rawEnd = ev.end_time ? isoDatePart(ev.end_time) : null;
  const endExclusive = rawEnd && rawEnd > first ? rawEnd : addDays(first, 1);
  return { first, endExclusive };
}

/** Czy wpis całodniowy obejmuje dany dzień siatki. */
export function isAllDayOnDay(ev: AllDayLike, day: Date): boolean {
  if (!ev.all_day) return false;
  const range = allDayRange(ev);
  if (!range) return false;
  const key = localDateKey(day);
  return range.first <= key && key < range.endExclusive;
}

function formatKey(key: string): string {
  const [y, m, d] = key.split("-").map(Number);
  // Południe UTC: data nie przeskoczy w żadnej strefie przeglądarki.
  return new Date(Date.UTC(y, m - 1, d, 12)).toLocaleDateString("pl-PL", {
    day: "numeric",
    month: "long",
  });
}

/** „Cały dzień · 21 września" albo „Cały dzień · 21 września – 23 września". */
export function allDayLabel(ev: AllDayLike): string {
  const range = allDayRange(ev);
  if (!range) return "Cały dzień";
  const last = addDays(range.endExclusive, -1);
  return last === range.first
    ? `Cały dzień · ${formatKey(range.first)}`
    : `Cały dzień · ${formatKey(range.first)} – ${formatKey(last)}`;
}
