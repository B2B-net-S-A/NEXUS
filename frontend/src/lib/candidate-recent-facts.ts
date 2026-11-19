/**
 * „Ostatnio z osobą” — linia pod wierszem listy kandydatów (18.11.2026,
 * decyzja Artura, makiety: https://claude.ai/artifact/Lk3LqawjifGhmJwn59Wrg3).
 *
 * Dwie ostatnie informacje o osobie z API (`recent_facts`, backend
 * `candidate_recent_facts.py`), najnowsza pierwsza, każda z datą. Zastępuje
 * kolumnę „Ostatnie odrzucenie”, w której cytat z lipca („nie jest
 * zainteresowany, nie wydzwaniać”) wyglądał na dzisiejszy, choć w listopadzie
 * była rozmowa z „dostępny ASAP”. Niczego nie wnioskujemy z treści —
 * „nie jest zainteresowany Nordeą” to odmowa jednej oferty, nie szukania pracy.
 */

export type RecentFactKind = "talk" | "note" | "rejection";

export interface RecentFact {
  at: string;
  kind: RecentFactKind;
  text: string;
  client_name?: string | null;
}

const KIND_LABEL: Record<RecentFactKind, string> = {
  talk: "rozmowa",
  note: "notatka",
  rejection: "odrzucenie",
};

const DATE = new Intl.DateTimeFormat("pl-PL", {
  timeZone: "Europe/Warsaw",
  day: "2-digit",
  month: "2-digit",
  year: "2-digit",
});

/** „02.11.26” w kalendarzu firmy; `null` przy złej dacie. */
export function recentFactDate(at: string): string | null {
  const date = new Date(at);
  return Number.isNaN(date.getTime()) ? null : DATE.format(date);
}

/** „rozmowa”, „notatka”, „odrzucenie (Nordea)”. */
export function recentFactLabel(fact: RecentFact): string {
  const label = KIND_LABEL[fact.kind] ?? "notatka";
  return fact.kind === "rejection" && fact.client_name ? `${label} (${fact.client_name})` : label;
}

/** Notatka i opis odrzucenia to cudze słowa — w cudzysłowie; podsumowanie rozmowy nie. */
export function recentFactText(fact: RecentFact): string {
  return fact.kind === "talk" ? fact.text : `„${fact.text}”`;
}

/** Pełna treść do dymka: każda informacja w osobnej linii. */
export function recentFactsTitle(facts: readonly RecentFact[]): string {
  return facts
    .map((fact) => `${recentFactDate(fact.at) ?? "—"} · ${recentFactLabel(fact)} — ${recentFactText(fact)}`)
    .join("\n");
}
