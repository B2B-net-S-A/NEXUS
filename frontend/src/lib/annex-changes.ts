// Lista zmian aneksu z własną nazwą („Aneks — inna zmiana”, 16.11.2026).
// Lustro `backend/app/services/b2b_documents/registry.py`
// (`annex_changes_problems`) i `context.py` (`annex_change_points`): te same
// zdania odmowy i te same formułki, żeby formularz pokazał to, co wyjdzie
// w dokumencie, i odmówił tak samo jak serwer.

import type { AnnexChangeOp, AnnexChangeRow, AnnexClauseDef } from "@/lib/api/b2bDocuments";

export const ANNEX_CHANGE_OPS: readonly { value: AnnexChangeOp; label: string }[] = [
  { value: "replace", label: "otrzymuje nowe brzmienie" },
  { value: "add", label: "dodaje się ustęp" },
  { value: "delete", label: "skreśla się" },
  { value: "free", label: "własny tekst" },
];

export const MAX_ANNEX_CHANGES = 20;
export const MAX_ANNEX_CHANGE_TEXT = 4000;
const MAX_ANNEX_REF = 12;
/** Miejsce klauzuli bez danych (np. umowa bez klienta) — do uzupełnienia. */
export const CLAUSE_GAP = "[uzupełnij]";

export const EMPTY_ANNEX_CHANGE: AnnexChangeRow = {
  op: "replace",
  paragraph: "",
  section: "",
  text: "",
};

function isRow(value: unknown): value is AnnexChangeRow {
  return typeof value === "object" && value !== null && "op" in value;
}

/** Wiersze z wartości formularza; nieznany kształt = pusta lista. */
export function annexChangeRows(value: unknown): AnnexChangeRow[] {
  return Array.isArray(value) ? value.filter(isRow) : [];
}

function isBlank(row: AnnexChangeRow): boolean {
  return !row.paragraph.trim() && !row.section.trim() && !row.text.trim();
}

/** Do wysyłki: bez spacji na brzegach i bez zupełnie pustych wierszy. */
export function cleanAnnexChanges(value: unknown): AnnexChangeRow[] {
  return annexChangeRows(value)
    .filter((row) => !isBlank(row))
    .map((row) => ({
      op: row.op,
      paragraph: row.paragraph.trim(),
      section: row.section.trim(),
      text: row.text.trim(),
    }));
}

export function annexChangesProblems(value: unknown): string[] {
  const rows = cleanAnnexChanges(value);
  const problems: string[] = [];
  if (rows.length > MAX_ANNEX_CHANGES) {
    problems.push(`Aneks mieści najwyżej ${MAX_ANNEX_CHANGES} zmian.`);
  }
  rows.forEach((row, index) => {
    const n = index + 1;
    if (row.op !== "free" && !row.paragraph) {
      problems.push(`Zmiana ${n}: podaj numer paragrafu (§).`);
    }
    if (row.op === "add" && !row.section) {
      problems.push(`Zmiana ${n}: podaj numer dodawanego ustępu.`);
    }
    if (row.op !== "delete" && !row.text) {
      problems.push(`Zmiana ${n}: wpisz treść.`);
    }
    if (row.text.includes(CLAUSE_GAP)) {
      problems.push(`Zmiana ${n}: uzupełnij miejsca oznaczone ${CLAUSE_GAP}.`);
    }
    if (row.paragraph.length > MAX_ANNEX_REF || row.section.length > MAX_ANNEX_REF) {
      problems.push(`Zmiana ${n}: numer paragrafu albo ustępu jest za długi.`);
    }
    if (row.text.length > MAX_ANNEX_CHANGE_TEXT) {
      problems.push(`Zmiana ${n}: treść ma więcej niż ${MAX_ANNEX_CHANGE_TEXT} znaków.`);
    }
  });
  return problems;
}

function ref(row: AnnexChangeRow): string {
  const paragraph = row.paragraph.replace(/^§\s*/, "").trim() || "…";
  return row.section.trim() ? `§ ${paragraph} ust. ${row.section.trim()}` : `§ ${paragraph}`;
}

/** Formułka, którą dokument poprzedzi treść wiersza (jak `annex_change_points`). */
export function annexChangeLead(row: AnnexChangeRow): string {
  switch (row.op) {
    case "replace":
      return `${ref(row)} Umowy otrzymuje brzmienie: „…”`;
    case "add":
      return `w § ${row.paragraph.replace(/^§\s*/, "").trim() || "…"} Umowy dodaje się ust. ${row.section.trim() || "…"} w brzmieniu: „…”`;
    case "delete":
      return `${ref(row)} Umowy skreśla się.`;
    default:
      return "punkt aneksu z Twoją treścią";
  }
}

/**
 * Podstawia `{non_compete_paragraph}`, `{client_legal_name}` itd. Brakująca
 * wartość zostaje jako „[…]”, żeby człowiek widział, co uzupełnić — nigdy
 * nie zgadujemy klienta ani paragrafu.
 */
export function fillClauseText(text: string, vars: Record<string, string | null | undefined>): string {
  return text.replace(/\{(\w+)\}(\.?)/g, (_, key: string, dot: string) => {
    const value = vars[key]?.trim() || CLAUSE_GAP;
    // „Bank S.A.” przed kropką zdania — bez podwójnej kropki.
    return value.endsWith(".") ? value : `${value}${dot}`;
  });
}

export function clauseRows(
  clause: AnnexClauseDef,
  vars: Record<string, string | null | undefined>,
): AnnexChangeRow[] {
  return clause.rows.map((row) => ({
    op: row.op,
    paragraph: row.paragraph ?? "",
    section: row.section ?? "",
    text: fillClauseText(row.text, vars),
  }));
}
