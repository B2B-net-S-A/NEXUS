// Przegląd DZ (0353) — podświetlenie must-have w tekście CV.
//
// Reguła granic słowa jest lustrem `backend/app/services/keyword_terms.py`
// (`py_regex`): granica tylko po stronie litery/cyfry, więc „Java" nie
// podświetla „JavaScript", a „C++" podświetla „C++17". Serwer liczy
// sprawdzenia (w CV / pogrubione / w rolach) — tu wyłącznie prezentacja.

export interface TextPart {
  text: string;
  /** Który must-have trafił (etykieta wymagania) — `null` = zwykły tekst. */
  match: string | null;
}

const WORD = /[\p{L}\p{N}_]/u;

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function termSource(term: string): string | null {
  const text = term.trim();
  if (!text) return null;
  const core = text
    .split(/\s+/)
    .map(escapeRegex)
    .join("[\\s\\-/]+");
  const left = WORD.test(text[0]) ? "(?<![\\p{L}\\p{N}_])" : "";
  const right = WORD.test(text[text.length - 1]) ? "(?![\\p{L}\\p{N}_])" : "";
  return `${left}${core}${right}`;
}

/** Alternatywy wymagania („Java lub Kotlin") — jak `requirement_contract.alternatives`. */
export function requirementAlternatives(label: string): string[] {
  return label
    .split(/\s+(?:lub|albo|or)\s+/i)
    .map((p) => p.trim())
    .filter(Boolean);
}

/** Dzieli tekst na kawałki z zaznaczonymi trafieniami must-have. */
export function highlightTerms(text: string, labels: string[]): TextPart[] {
  const sources: Array<{ label: string; source: string }> = [];
  for (const label of labels) {
    for (const alt of requirementAlternatives(label)) {
      const source = termSource(alt);
      if (source) sources.push({ label, source });
    }
  }
  if (!text || sources.length === 0) return [{ text, match: null }];
  // Dłuższe najpierw: „Spring Boot" wygrywa ze „Spring".
  sources.sort((a, b) => b.source.length - a.source.length);
  const pattern = new RegExp(sources.map((s) => `(${s.source})`).join("|"), "giu");
  const parts: TextPart[] = [];
  let last = 0;
  for (const m of text.matchAll(pattern)) {
    const index = m.index ?? 0;
    if (m[0].length === 0) continue;
    if (index > last) parts.push({ text: text.slice(last, index), match: null });
    const group = m.slice(1).findIndex((g) => g !== undefined);
    parts.push({ text: m[0], match: sources[group]?.label ?? null });
    last = index + m[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), match: null });
  return parts;
}

export const DZ_CV_SOURCE_LABEL: Record<string, string> = {
  branded_finalized: "Zatwierdzone CV firmowe",
  branded_draft: "Szkic CV firmowego",
  generated: "Z generatora (nieprzypięte do etapu)",
  document: "Plik kandydata (Traffit)",
};

export const DZ_HINT_KIND_LABEL: Record<string, string> = {
  missing_must: "Brak must-have",
  not_bolded: "Pogrubienie",
  missing_in_role: "Brak w roli",
  unsupported: "Brak pokrycia w oryginale",
  wording: "Nazewnictwo",
  other: "Uwaga",
};
