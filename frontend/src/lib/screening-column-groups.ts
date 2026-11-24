/**
 * Kolumna „Screening” w grupach i napis o powrocie karty (decyzja Artura
 * z 23.11.2026, `docs/claude/rekrutacja-tablica/karty-bez-sladu-wracaja-do-nowych.md`).
 *
 * Grupy liczą się z danych, które Tablica już ma: `screening_done` i karta
 * rekomendacji (`card.answers`) = była rozmowa, `contact_attempts` = próby
 * „Nie odebrał”. Dzień powrotu (`returns_to_new_on`) liczy serwer tą samą
 * regułą co automat (`services/screening_stale.py`), więc front nie liczy dni
 * roboczych sam.
 */
import { warsawToday } from "@/lib/warsaw-date";

/** Po tylu próbach „Nie odebrał” termin porcji już się nie przesuwa (#3788). */
export const MAX_CONTACT_ATTEMPTS = 3;

export type ScreeningGroup = "to_call" | "no_answer" | "after_call";

export interface ScreeningGroupItem {
  id: number;
  screening_done?: boolean;
  card?: { answers: number } | null;
  contact_attempts?: number;
  returns_to_new_on?: string | null;
}

export function screeningGroupOf(item: ScreeningGroupItem): ScreeningGroup {
  if (item.screening_done === true || (item.card?.answers ?? 0) > 0) return "after_call";
  if ((item.contact_attempts ?? 0) > 0) return "no_answer";
  return "to_call";
}

const GROUP_ORDER: Record<ScreeningGroup, number> = { to_call: 0, no_answer: 1, after_call: 2 };

/** Karty w kolejności grup; w grupie najpierw te, które najszybciej wracają
 *  do „Nowych”, potem kolejność z serwera (sortowanie stabilne). */
export function orderScreeningColumn<T extends ScreeningGroupItem>(
  items: readonly T[]
): { items: T[]; groups: Map<number, ScreeningGroup> } {
  const groups = new Map<number, ScreeningGroup>();
  for (const it of items) groups.set(it.id, screeningGroupOf(it));
  const sorted = items
    .map((it, index) => ({ it, index }))
    .sort((a, b) => {
      const g = GROUP_ORDER[groups.get(a.it.id)!] - GROUP_ORDER[groups.get(b.it.id)!];
      if (g !== 0) return g;
      const ra = a.it.returns_to_new_on ?? "9999-12-31";
      const rb = b.it.returns_to_new_on ?? "9999-12-31";
      if (ra !== rb) return ra < rb ? -1 : 1;
      return a.index - b.index;
    })
    .map(({ it }) => it);
  return { items: sorted, groups };
}

/** Nagłówek grupy z liczbą kart; „Nie odebrał” mówi o limicie 3 prób. */
export function screeningGroupLabel(group: ScreeningGroup, count: number): string {
  if (group === "after_call") return `Po rozmowie · dokończ arkusz · ${count}`;
  if (group === "no_answer") return `Nie odebrał · do ${MAX_CONTACT_ATTEMPTS} prób · ${count}`;
  return `Do telefonu · ${count}`;
}

/** Podpis karty w grupie „Nie odebrał”: „próba N z 3”. */
export function attemptLabel(attempts: number | undefined): string | null {
  const n = attempts ?? 0;
  if (n <= 0) return null;
  if (n >= MAX_CONTACT_ATTEMPTS) return `próba ${MAX_CONTACT_ATTEMPTS} z ${MAX_CONTACT_ATTEMPTS} · wpisz wynik albo odrzuć`;
  return `próba ${n} z ${MAX_CONTACT_ATTEMPTS}`;
}

function addDays(day: string, days: number): string {
  const [y, m, d] = day.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d + days));
  return date.toISOString().slice(0, 10);
}

const WEEKDAY = ["w niedzielę", "w poniedziałek", "we wtorek", "w środę", "w czwartek", "w piątek", "w sobotę"];

function weekdayOf(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return WEEKDAY[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
}

/**
 * Napis o powrocie, gdy zostało najwyżej 1 dzień roboczy: „dziś”, „jutro”
 * albo dzień tygodnia (piątek → „w poniedziałek”). Dalszy termin = `null`,
 * żeby karta nie straszyła od pierwszego dnia. `column` zmienia czasownik:
 * w „Nowych” karta nie wraca, tylko traci „Biorę”.
 */
export function returnNotice(
  returnsOn: string | null | undefined,
  column: "screening" | "new",
  now: Date = new Date()
): string | null {
  if (!returnsOn) return null;
  const today = warsawToday(now);
  const verb = column === "new" ? "„Biorę” wygasa" : "Wraca do „Nowych”";
  if (returnsOn <= today) return `${verb} dziś`;
  if (returnsOn === addDays(today, 1)) return `${verb} jutro`;
  // Po drodze sam weekend (piątek → poniedziałek) = dziś ostatni dzień roboczy.
  // Święto po drodze daje dalszy dzień powrotu z serwera i napis pojawi się
  // dzień później; to tylko podpowiedź, termin liczy serwer.
  let day = addDays(today, 1);
  while (day < returnsOn) {
    const dow = new Date(`${day}T12:00:00Z`).getUTCDay();
    if (dow !== 0 && dow !== 6) return null;
    day = addDays(day, 1);
  }
  return `${verb} ${weekdayOf(returnsOn)}`;
}
