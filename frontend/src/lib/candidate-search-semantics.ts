/**
 * Wspólna semantyka filtrów kandydatów (v2) po stronie UI — decyzje
 * właściciela produktu z 21.09.2026, backend: `candidate_search_predicates.py`.
 *
 * - umiejętności w TRZECH jawnych kubełkach: „Musi mieć" (twardo, `a|b` =
 *   którakolwiek z grupy), „Mile widziane" (tylko kolejność), „Wyklucz" (twardo);
 * - tekst `q`: tryb automatyczny + widoczne „Rozumiem to jako…" z przełącznikiem
 *   „Dosłownie / Po znaczeniu";
 * - osoby bez lokalizacji / stażu / stawki ZOSTAJĄ, oznaczone plakietką,
 *   chyba że rekruter zaznaczy „Ukryj osoby bez danych".
 *
 * Stare stany (`?s=`, zapisane wyszukiwania) przechodzą przez ten sam adapter
 * co migracja zapisów (`saved-search-unified.ts`) — tu nie ma drugiej kopii
 * reguł mapowania.
 */

import type {
  CandidateSearchRequest,
  SearchTextInterpretation,
} from "@/lib/candidate-search-api";
import { searchRequestToUnified } from "@/lib/saved-search-unified";

export type TextMode = "auto" | "literal" | "semantic";
export type TextModeApplied = "literal" | "keywords" | "semantic" | "none";

/** Limit pozycji w jednym kubełku (lustro `max_length=20` w backendzie). */
export const SKILL_BUCKET_LIMIT = 20;

const OPEN_TO_FLAGS = [
  ["open_to_side_projects", "side_projects"],
  ["open_to_sales_support", "sales_support"],
  ["open_to_expert_consult", "expert_consult"],
] as const;

type OpenToValue = (typeof OPEN_TO_FLAGS)[number][1];

const dedupeCI = (items: string[]): string[] => {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of items) {
    const item = raw.trim();
    if (!item) continue;
    const key = item.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
};

/**
 * Żądanie wyszukiwarki (dowolny stan: domyślny, `?s=`, zapis legacy, prefill
 * rekrutacji) → kształt v2 z jawnymi kubełkami.
 *
 * Mapowanie pól legacy bierzemy z adaptera zapisów (`searchRequestToUnified`):
 * `skills_must` + `skills_any` → „Mile widziane" (tam zawsze były wyłącznie
 * sygnałem rankingowym), `skills_none` → „Wyklucz", `open_to_*: true` →
 * „Otwarty na" (którekolwiek). Grupy „którakolwiek" z zapisów listy lądują
 * w „Musi mieć" jako pozycje `a|b` — backend czyta je identycznie.
 */
export function toSearchSemanticsV2(
  request: CandidateSearchRequest,
): CandidateSearchRequest {
  const unified = searchRequestToUnified(
    request as unknown as Record<string, unknown>,
  );
  const groups = (unified.skills_required_any_groups ?? [])
    .map((group) => dedupeCI(group))
    .filter((group) => group.length > 0)
    .map((group) => group.join("|"));
  const openTo = new Set<OpenToValue>(
    (unified.open_to ?? []) as OpenToValue[],
  );
  const out: CandidateSearchRequest = {
    ...request,
    skills_must: [],
    skills_any: [],
    skills_none: [],
    skills_required: dedupeCI([
      ...(unified.skills_required ?? []),
      ...groups,
    ]).slice(0, SKILL_BUCKET_LIMIT),
    skills_required_any_groups: [],
    skills_preferred: dedupeCI(unified.skills_preferred ?? []).slice(
      0,
      SKILL_BUCKET_LIMIT,
    ),
    skills_excluded: dedupeCI(unified.skills_excluded ?? []).slice(
      0,
      SKILL_BUCKET_LIMIT,
    ),
    open_to: OPEN_TO_FLAGS.map(([, name]) => name).filter((name) =>
      openTo.has(name),
    ),
    semantics_version: 2,
  };
  // `true` przeszło do „Otwarty na"; `false` (jawne „nie") zostaje, jak w
  // adapterze zapisów (`search_only`).
  for (const [flag] of OPEN_TO_FLAGS) {
    if (request[flag] === true) out[flag] = null;
  }
  return out;
}

/**
 * Czy wpisany tekst wygląda na wklejony request (opis stanowiska), a nie na
 * frazę wyszukiwania: ≥ 300 znaków albo ≥ 3 przejścia do nowej linii.
 */
export function looksLikePastedRequest(text: string | null | undefined): boolean {
  const value = text ?? "";
  if (value.trim().length === 0) return false;
  if (value.length >= 300) return true;
  return (value.match(/\n/g) ?? []).length >= 3;
}

export interface TextInterpretationSummary {
  /** „osoba" / „słowa kluczowe" / „po znaczeniu" / „dosłowny tekst". */
  label: string;
  /** Szczegół w nawiasie (np. imię i nazwisko), może być pusty. */
  detail: string;
}

/**
 * Zdanie „Rozumiem to jako: …". O trybie decyduje to, co backend faktycznie
 * zrobił (`text_mode_applied`), a interpretacja dodaje szczegół (kto / co).
 */
export function summarizeTextInterpretation(
  applied: TextModeApplied | null | undefined,
  interpretation: SearchTextInterpretation | null | undefined,
): TextInterpretationSummary | null {
  if (!applied || applied === "none") return null;
  const kind = interpretation?.kind;
  if (applied === "literal") {
    if (kind === "email" && interpretation?.email) {
      return { label: "osoba", detail: `e-mail ${interpretation.email}` };
    }
    if (kind === "phone" && interpretation?.phone) {
      return { label: "osoba", detail: `telefon …${interpretation.phone}` };
    }
    if (kind === "name") {
      return {
        label: "osoba",
        detail: (interpretation?.name ?? []).join(" "),
      };
    }
    return { label: "dosłowny tekst", detail: "" };
  }
  if (applied === "keywords") return { label: "słowa kluczowe", detail: "" };
  return { label: "po znaczeniu", detail: "" };
}

export type UnknownField = "location" | "experience" | "rate";

const UNKNOWN_FIELD_LABELS: Record<UnknownField, string> = {
  location: "brak lokalizacji",
  experience: "brak stażu",
  rate: "brak stawki",
};

const UNKNOWN_FIELD_HINTS: Record<UnknownField, string> = {
  location:
    "Nie znamy lokalizacji tej osoby — przeszła filtr lokalizacji, bo nie da się jej wykluczyć.",
  experience:
    "Nie znamy stażu tej osoby — przeszła filtr lat doświadczenia, bo nie da się jej wykluczyć.",
  rate: "Nie znamy stawki tej osoby — przeszła filtr stawki, bo nie da się jej wykluczyć.",
};

/** Znane pola `unknown_fields` w stałej kolejności; nieznane kody odpadają. */
export function unknownFieldBadges(
  fields: readonly string[] | null | undefined,
): Array<{ field: UnknownField; label: string; hint: string }> {
  const out: Array<{ field: UnknownField; label: string; hint: string }> = [];
  for (const field of ["location", "experience", "rate"] as const) {
    if (fields?.includes(field)) {
      out.push({
        field,
        label: UNKNOWN_FIELD_LABELS[field],
        hint: UNKNOWN_FIELD_HINTS[field],
      });
    }
  }
  return out;
}

export type SkillBucket = "required" | "preferred" | "excluded";

export interface SkillBucketsValue {
  /** „Musi mieć" — pozycja `a|b` = którakolwiek z grupy. */
  required: string[];
  /** „Mile widziane" — tylko kolejność. */
  preferred: string[];
  /** „Wyklucz". */
  excluded: string[];
}

export const SKILL_BUCKET_LABELS: Record<SkillBucket, string> = {
  required: "Musi mieć",
  preferred: "Mile widziane",
  excluded: "Wyklucz",
};

/**
 * Tekst wpisany w pole umiejętności → pozycje do dodania.
 *
 * Przecinek rozdziela pozycje. `a|b` i `a OR b` to grupa „którakolwiek"
 * (zapisywana jako `a|b`). Wiodący `-` wysyła pozycję do „Wyklucz" niezależnie
 * od wybranego kubełka. Pozycja bez wybranego kubełka trafia do „Musi mieć"
 * (decyzja 21.09.2026) — to domyślna wartość `bucket`.
 */
export function parseSkillBucketInput(
  raw: string,
  bucket: SkillBucket = "required",
): Array<{ bucket: SkillBucket; value: string }> {
  const out: Array<{ bucket: SkillBucket; value: string }> = [];
  for (const piece of raw.split(",")) {
    let text = piece.trim();
    if (!text) continue;
    let target = bucket;
    if (text.startsWith("-")) {
      target = "excluded";
      text = text.slice(1).trim();
    }
    const parts = text
      .split(/\s*\|\s*|\s+OR\s+/i)
      .map((part) => part.trim().replace(/^"(.*)"$/, "$1").trim())
      .filter(Boolean);
    if (parts.length === 0) continue;
    if (target === "excluded") {
      // NOT (a LUB b) ≡ NOT a ORAZ NOT b — w „Wyklucz" grupa się spłaszcza.
      for (const part of parts) out.push({ bucket: target, value: part });
    } else {
      out.push({ bucket: target, value: dedupeCI(parts).join("|") });
    }
  }
  return out;
}

/** Pozycja `a|b` do wyświetlenia: „a lub b". */
export function skillEntryLabel(entry: string): string {
  return entry
    .split("|")
    .map((part) => part.trim())
    .filter(Boolean)
    .join(" lub ");
}
