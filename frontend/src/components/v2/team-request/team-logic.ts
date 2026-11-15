/**
 * Zespół dla klienta: czyste przeliczenia ceny i startu zespołu
 * (`docs/claude/klienci/zespol-dla-klienta.md`). Zespół to kilka zwykłych
 * rekrutacji (stanowisk); każde ma liczbę osób i kandydatów-alternatyw.
 * Cena zespołu to suma stawek do klienta, bez rabatu (decyzja 15.11.2026).
 */
import type { PanelCandidate, PanelRate } from "@/lib/api/clientPanel";

/** Stanowisko widziane przez przeliczenia: klucz, liczba miejsc, kandydaci. */
export interface SeatGroup<C> {
  key: string;
  headcount: number;
  candidates: readonly C[];
}

export type Picks = Record<string, string[]>;

/** Domyślna liczba godzin w miesiącu, gdy serwer jej nie podał. */
export const DEFAULT_HOURS_PER_MONTH = 168;

export function hourlyValue(
  rate: Pick<PanelRate, "unit"> & { value: string | number } | null | undefined,
): number | null {
  if (!rate || rate.unit !== "hourly") return null;
  const value = Number(rate.value);
  return Number.isFinite(value) ? value : null;
}

export function candidateHourly(candidate: PanelCandidate): number | null {
  return hourlyValue(candidate.rate);
}

/** Najniższa i najwyższa stawka godzinowa wśród kandydatów stanowiska. */
export function rateRange<C>(
  group: SeatGroup<C>,
  rateOf: (c: C) => number | null,
): { min: number; max: number } | null {
  const rates = group.candidates.map(rateOf).filter((r): r is number => r != null);
  if (rates.length === 0) return null;
  return { min: Math.min(...rates), max: Math.max(...rates) };
}

/**
 * Cena zespołu od–do za godzinę: na każdym miejscu najtańsza albo najdroższa
 * osoba stanowiska, razy liczba osób. Stanowisko bez żadnej stawki nie wchodzi
 * do sumy; zwracamy jego klucz, żeby ekran o nim powiedział.
 */
export function teamHourlyRange<C>(
  groups: readonly SeatGroup<C>[],
  rateOf: (c: C) => number | null,
): { min: number; max: number; unpriced: string[] } {
  let min = 0;
  let max = 0;
  const unpriced: string[] = [];
  for (const group of groups) {
    const range = rateRange(group, rateOf);
    if (!range) {
      unpriced.push(group.key);
      continue;
    }
    min += range.min * group.headcount;
    max += range.max * group.headcount;
  }
  return { min, max, unpriced };
}

export function pickedOf<C>(group: SeatGroup<C>, picks: Picks, idOf: (c: C) => string): C[] {
  const ids = picks[group.key] ?? [];
  return ids
    .map((id) => group.candidates.find((c) => idOf(c) === id))
    .filter((c): c is C => c != null);
}

/**
 * Suma stawek wybranego składu, miejsca bez osoby i osoby bez stawki
 * (te nie wchodzą do sumy, ekran mówi o nich osobno).
 */
export function selectionHourly<C>(
  groups: readonly SeatGroup<C>[],
  picks: Picks,
  idOf: (c: C) => string,
  rateOf: (c: C) => number | null,
): { total: number; openSeats: number; unpriced: number } {
  let total = 0;
  let openSeats = 0;
  let unpriced = 0;
  for (const group of groups) {
    const chosen = pickedOf(group, picks, idOf);
    openSeats += Math.max(0, group.headcount - chosen.length);
    for (const candidate of chosen) {
      const rate = rateOf(candidate);
      if (rate == null) unpriced += 1;
      else total += rate;
    }
  }
  return { total, openSeats, unpriced };
}

/**
 * Start całego zespołu = najpóźniejsza dostępność w składzie. Osoba bez daty
 * („do ustalenia”) nie przesuwa startu; zwracamy, ile takich osób jest.
 */
export function teamStart(
  groups: readonly SeatGroup<PanelCandidate>[],
  picks: Picks,
  today: string,
): { date: string; unknown: number } {
  let latest = today;
  let unknown = 0;
  for (const group of groups) {
    for (const candidate of pickedOf(group, picks, (c) => c.public_id)) {
      if (!candidate.available_from) unknown += 1;
      else if (candidate.available_from > latest) latest = candidate.available_from;
    }
  }
  return { date: latest, unknown };
}

/**
 * Zmiana wyboru na stanowisku: klik zaznacza albo odznacza osobę. Na pełnym
 * stanowisku nowa osoba zastępuje ostatnio wybraną.
 */
export function togglePick(picks: Picks, key: string, headcount: number, id: string): Picks {
  const chosen = picks[key] ?? [];
  if (chosen.includes(id)) return { ...picks, [key]: chosen.filter((x) => x !== id) };
  const seats = Math.max(1, headcount);
  const next = chosen.length >= seats ? [...chosen.slice(0, seats - 1), id] : [...chosen, id];
  return { ...picks, [key]: next };
}

/**
 * Skład startowy, gdy klient jeszcze nic nie wybrał: na każdym miejscu osoba
 * dostępna najwcześniej, przy remisie tańsza. Bez osób „nie pasuje”.
 */
export function startingPicks(
  groups: readonly SeatGroup<PanelCandidate>[],
): Picks {
  const picks: Picks = {};
  for (const group of groups) {
    const ranked = [...group.candidates]
      .filter((c) => c.state !== "not_fit")
      .sort((a, b) => {
        const da = a.available_from ?? "9999-12-31";
        const db = b.available_from ?? "9999-12-31";
        if (da !== db) return da < db ? -1 : 1;
        return (candidateHourly(a) ?? Infinity) - (candidateHourly(b) ?? Infinity);
      });
    picks[group.key] = ranked.slice(0, Math.max(1, group.headcount)).map((c) => c.public_id);
  }
  return picks;
}

/** Poziomy stawek na stanowisku („profile”): grupy kandydatów po stawce. */
export function profileTiers(
  candidates: readonly PanelCandidate[],
): { rate: number; count: number; availableNow: number }[] {
  const groups = new Map<number, PanelCandidate[]>();
  for (const candidate of candidates) {
    const rate = candidateHourly(candidate);
    if (rate == null) continue;
    groups.set(rate, [...(groups.get(rate) ?? []), candidate]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a - b)
    .map(([rate, items]) => ({
      rate,
      count: items.length,
      availableNow: items.filter((c) => c.available_label === "od zaraz").length,
    }));
}

const PLN = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 0 });
const PLN2 = new Intl.NumberFormat("pl-PL", { minimumFractionDigits: 0, maximumFractionDigits: 2 });

export function formatPln(value: number): string {
  return `${PLN.format(Math.round(value))} zł`;
}

export function formatHourly(value: number): string {
  return `${PLN2.format(value)} zł/h`;
}

export function formatThousands(value: number): string {
  return `${PLN.format(Math.round(value / 1000))} tys. zł`;
}

export function formatYmd(ymd: string): string {
  const [y, m, d] = ymd.split("-");
  return `${d}.${m}.${y}`;
}

/** „1 osoba”, „2 osoby”, „5 osób” */
export function peopleLabel(count: number): string {
  if (count === 1) return "1 osoba";
  const tens = count % 100;
  const ones = count % 10;
  if (ones >= 2 && ones <= 4 && (tens < 12 || tens > 14)) return `${count} osoby`;
  return `${count} osób`;
}
