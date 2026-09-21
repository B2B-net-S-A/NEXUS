/**
 * Zapis wstrzymany przez migrację na wspólną semantykę filtrów
 * (backend: `app/services/saved_search_migration.py`).
 *
 * `filters.migration.diff` niesie WYŁĄCZNIE liczby i kody reguł — tu zamieniamy
 * je na krótkie zdania po polsku. Kody: `saved_search_payload.py` (`RULE_*`).
 * To INNY przypadek niż wycofanie miesięcznych kryteriów stawki (tam zapis
 * też ma `requires_reapproval`, ale nie ma `filters.migration`).
 */

export const REAPPROVAL_RULE_LABELS: Record<string, string> = {
  location_wildcards:
    "znaki „%” i „_” w lokalizacji są teraz traktowane dosłownie",
  tags_whole_match: "tag musi pasować w całości (np. „java” to nie „javascript”)",
  category_secondary: "liczy się także poboczna kategoria kompetencji",
  open_to_any: "„Otwarty na” — wystarczy którakolwiek z zaznaczonych opcji",
  experience_traffit_fallback:
    "staż bierze pod uwagę także przedział zaimportowany z Traffita",
  text_person_literal: "wpisany tekst jest teraz szukany jako imię i nazwisko",
  other: "ujednolicone zasady filtrów listy i wyszukiwarki",
};

export function reapprovalRuleLabel(code: string): string {
  return REAPPROVAL_RULE_LABELS[code] ?? REAPPROVAL_RULE_LABELS.other;
}

export interface SemanticsReapproval {
  /** Liczba osób dotąd; `null`, gdy wyników nie porównywano liczbowo. */
  legacyTotal: number | null;
  unifiedTotal: number | null;
  ruleLabels: string[];
  alertWasOn: boolean;
}

const asCount = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

/** `null` = to nie jest zapis wstrzymany przez migrację semantyki. */
export function semanticsReapproval(filters: unknown): SemanticsReapproval | null {
  if (!filters || typeof filters !== "object") return null;
  const migration = (filters as Record<string, unknown>).migration;
  if (!migration || typeof migration !== "object") return null;
  const m = migration as Record<string, unknown>;
  if (m.reapproved_at) return null;
  const diff = (m.diff && typeof m.diff === "object" ? m.diff : {}) as Record<
    string,
    unknown
  >;
  const codes = Array.isArray(diff.rules)
    ? diff.rules.filter((c): c is string => typeof c === "string")
    : [];
  const labels = Array.from(
    new Set((codes.length ? codes : ["other"]).map(reapprovalRuleLabel)),
  );
  return {
    legacyTotal: asCount(diff.legacy_total),
    unifiedTotal: asCount(diff.unified_total),
    ruleLabels: labels,
    alertWasOn: m.alert_was_on === true,
  };
}
