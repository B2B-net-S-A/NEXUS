/**
 * Powód w wierszu okna „Kandydaci do dodania” (14.10.2026): do trzech chipów
 * „✓ spełnia”, „✕ brakuje”, „? zapytaj” i „+N” za resztę, żeby rekruter nie
 * otwierał osoby tylko po to, by zobaczyć, czemu jest na liście. Etykieta
 * do ~18 znaków (`shortChipLabel`), cała w podpowiedzi — chip skrócony do
 * trzech liter był gorszy niż żaden (zrzut 1280 × 720, okno 540 px).
 *
 * Najpierw po jednym z każdego rodzaju (co pasuje, czego brakuje, o co
 * zapytać), potem reszta po kolei — trzy „✓” nie mówią, czego brakuje.
 * Dane są już na liście: wymagania propozycji (`detail.requirements`)
 * i rozbicie dopasowania (`matching_must` / `gap_must`); „zapytaj” to
 * must-have zdaniem, których wyszukiwanie nie czyta (`not_searchable_must`).
 */

import type { MatchBreakdown } from "@/lib/match-breakdown";
import type { ProposalRequirement } from "@/lib/proposals-merge";

export type ReasonChipTone = "met" | "gap" | "ask";

export interface ReasonChip {
  tone: ReasonChipTone;
  label: string;
}

export const REASON_CHIPS_MAX = 3;
/** Tyle znaków etykiety widać na chipie; resztę mówi podpowiedź (`title`). */
export const REASON_CHIP_LABEL_MAX = 18;

/** Chipy do pokazania i reszta (chip „+N”, lista w podpowiedzi). */
export interface ReasonChipList {
  shown: ReasonChip[];
  hidden: ReasonChip[];
}

const EMPTY: ReasonChipList = { shown: [], hidden: [] };

/** „Minimum 5 lat doświadczenia…” — skrót etykiety do `max` znaków. */
export function shortChipLabel(label: string, max: number = REASON_CHIP_LABEL_MAX): string {
  const chars = [...label.trim()];
  if (chars.length <= max) return chars.join("");
  return `${chars.slice(0, max - 1).join("").trimEnd()}…`;
}

const TONES: readonly ReasonChipTone[] = ["met", "gap", "ask"];

const labelKey = (label: string) => label.trim().replace(/\s+/g, " ").toLocaleLowerCase("pl");

/** Chipy z trzech list; ta sama etykieta raz (pierwszy rodzaj wygrywa). */
export function reasonChips(
  lists: Partial<Record<ReasonChipTone, readonly string[]>>,
  max: number = REASON_CHIPS_MAX,
): ReasonChipList {
  const seen = new Set<string>();
  const queues = TONES.map((tone) => ({
    tone,
    labels: (lists[tone] ?? []).filter((label) => {
      const key = labelKey(label);
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    }),
  }));
  const out: ReasonChip[] = [];
  for (let round = 0; ; round += 1) {
    const before = out.length;
    for (const { tone, labels } of queues) {
      const label = labels[round];
      if (label) out.push({ tone, label: label.trim() });
    }
    if (out.length === before) break;
  }
  if (out.length === 0) return EMPTY;
  return { shown: out.slice(0, max), hidden: out.slice(max) };
}

/**
 * Propozycja: spełnione must-have (potem mile widziane), brakujące must-have,
 * nieznane must-have i must-have zdaniem z rekrutacji jako „zapytaj”.
 */
export function proposalReasonChips(
  requirements: readonly ProposalRequirement[] | null | undefined,
  askLabels: readonly string[] = [],
): ReasonChipList {
  const reqs = requirements ?? [];
  // „angular · 2020”: technologia sprzed ponad 3 lat jest „zapytaj”, z rokiem.
  const pick = (level: "must" | "nice", status: ProposalRequirement["status"]) =>
    reqs
      .filter((r) => r.level === level && r.status === status)
      .map((r) => (r.lastUsedYear != null ? `${r.label} · ${r.lastUsedYear}` : r.label));
  return reasonChips({
    met: [...pick("must", "met"), ...pick("nice", "met")],
    gap: pick("must", "not_met"),
    ask: [...pick("must", "unknown"), ...askLabels],
  });
}

/** „Szukaj w bazie”: rozbicie dopasowania z `/scores` + must-have zdaniem. */
export function breakdownReasonChips(
  breakdown: MatchBreakdown | null | undefined,
  askLabels: readonly string[] = [],
): ReasonChipList {
  return reasonChips({
    met: breakdown?.matching_must ?? [],
    gap: breakdown?.gap_must ?? [],
    ask: askLabels,
  });
}

/**
 * Wiersze dodane w tym oknie zostają na liście z „Cofnij”, choć źródło już
 * ich nie zwraca: wracają w miejsce, w którym stały. Żywy wiersz wygrywa.
 */
export function withKeptRows<T>(
  live: readonly T[],
  kept: ReadonlyMap<number, { value: T; index: number }>,
  idOf: (value: T) => number,
): T[] {
  if (kept.size === 0) return [...live];
  const liveIds = new Set(live.map(idOf));
  const out = [...live];
  const missing = [...kept.entries()]
    .filter(([id]) => !liveIds.has(id))
    .sort((a, b) => a[1].index - b[1].index);
  for (const [, { value, index }] of missing) {
    out.splice(Math.min(index, out.length), 0, value);
  }
  return out;
}
