/**
 * Logika wzorów własnych (bez Reacta): grupy pól, braki w formularzu,
 * zakres klientów, opis zmian szkicu i kroki „Nowego wzoru z asystentem”.
 * Serwer sprawdza to samo (`custom_templates/fields.py`) — tu tylko po to,
 * żeby człowiek zobaczył brak przed wysłaniem.
 */

import type {
  CustomChange,
  CustomCheck,
  CustomDocumentType,
  CustomFieldDef,
  CustomTemplateDetail,
  CustomValue,
  CustomValues,
  CustomVersion,
} from "@/lib/api/customTemplates";

export type StudioStep = "brief" | "draft" | "save";

export const STUDIO_STEPS: { key: StudioStep; label: string }[] = [
  { key: "brief", label: "Opis" },
  { key: "draft", label: "Szkic i pola" },
  { key: "save", label: "Zapis i zatwierdzenie" },
];

export const KIND_OPTIONS: { value: CustomVersion["kind"]; label: string }[] = [
  { value: "contract", label: "Umowa" },
  { value: "preliminary", label: "Umowa przedwstępna" },
  { value: "annex", label: "Aneks" },
  { value: "letter", label: "Porozumienie / pismo" },
];

export const SIGNATORY_OPTIONS: { value: CustomVersion["signatories"]; label: string }[] = [
  { value: "both", label: "Partner i spółka" },
  { value: "partner_and_company", label: "Partner, potem spółka" },
  { value: "company", label: "Tylko spółka" },
];

export const SOURCE_OPTIONS: { value: CustomFieldDef["source"]; label: string }[] = [
  { value: "candidate", label: "kandydat" },
  { value: "ceidg", label: "CEIDG" },
  { value: "clients", label: "lista klientów" },
  { value: "manual", label: "ręcznie" },
];

export const FIELD_KIND_LABELS: Record<CustomFieldDef["kind"], string> = {
  text: "tekst",
  textarea: "tekst wielowierszowy",
  date: "data",
  money: "kwota",
  bool: "tak / nie",
  select: "wybór",
  email: "e-mail",
  gender: "płeć (formy Pan/Pani)",
  list: "lista",
};

/** Pola w kolejności pierwszego wystąpienia grupy. */
export function groupFields(
  fields: readonly CustomFieldDef[],
): { group: string; fields: CustomFieldDef[] }[] {
  const order: string[] = [];
  const by = new Map<string, CustomFieldDef[]>();
  for (const field of fields) {
    const group = field.group || "Dokument";
    if (!by.has(group)) {
      order.push(group);
      by.set(group, []);
    }
    by.get(group)!.push(field);
  }
  return order.map((group) => ({ group, fields: by.get(group)! }));
}

function filled(value: CustomValue | undefined): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "boolean") return true;
  return value !== null && value !== undefined && String(value).trim() !== "";
}

const MONEY = /^\d{1,8}([.,]\d{1,2})?$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Klucze pól z brakiem albo złą wartością (te same reguły co serwer). */
export function invalidFieldKeys(
  fields: readonly CustomFieldDef[],
  values: CustomValues,
): string[] {
  const out: string[] = [];
  for (const field of fields) {
    const value = values[field.key];
    if (!filled(value)) {
      if (field.required) out.push(field.key);
      continue;
    }
    const text = String(value).replace(/[\s ]/g, "").replace(/zł$/i, "");
    if (field.kind === "money" && !MONEY.test(text)) out.push(field.key);
    else if (field.kind === "date" && !DAY.test(String(value))) out.push(field.key);
    else if (field.kind === "email" && !EMAIL.test(String(value).trim())) out.push(field.key);
    else if (field.kind === "select" && !field.options.some(([v]) => v === String(value)))
      out.push(field.key);
  }
  return out;
}

/** Czy wzór wolno wystawić dla klienta (zakres „Tylko wybrani”). */
export function offeredForClient(
  type: Pick<CustomDocumentType, "client_scope" | "client_ids">,
  clientId: number | null,
): boolean {
  if (type.client_scope === "all") return true;
  return clientId !== null && type.client_ids.includes(clientId);
}

/** Klucz wzoru w „Nowy dokument” (`custom:<id>`). */
export function isCustomTypeKey(key: string | null | undefined): boolean {
  return Boolean(key?.startsWith("custom:"));
}

/** „Zmienione: 3 akapity · dodane: 2 · usunięte: 1 · pola: 11”. */
export function changeSummary(changes: readonly CustomChange[], fieldCount: number): string {
  const count = (op: CustomChange["op"]) => changes.filter((c) => c.op === op).length;
  const parts = [
    `zmienione: ${count("replace")}`,
    `dodane: ${count("insert_after")}`,
    `usunięte: ${count("delete")}`,
    `pola: ${fieldCount}`,
  ];
  const text = parts.join(" · ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Pole sprawdzenia → ton etykiety. */
export function checkTone(check: Pick<CustomCheck, "state">): "success" | "warning" | "danger" {
  if (check.state === "ok") return "success";
  return check.state === "block" ? "danger" : "warning";
}

export function citeStateLabel(state: CustomCheck["cite_state"]): string {
  switch (state) {
    case "ok":
      return "cytat sprawdzony";
    case "missing":
      return "brak w korpusie";
    case "mismatch":
      return "cytat niezgodny";
    default:
      return "do sprawdzenia";
  }
}

/** Krok, od którego otwiera się studio dla istniejącego wzoru. */
export function initialStep(detail: CustomTemplateDetail | null | undefined): StudioStep {
  if (!detail) return "brief";
  const working = detail.working;
  if (!working) return "save";
  return working.status === "pending" ? "save" : "draft";
}

/** Co blokuje „Wyślij do zatwierdzenia” — tekst do wyświetlenia, puste = nic. */
export function submitBlockers(version: CustomVersion | null | undefined): string[] {
  if (!version) return [];
  const out = [...(version.problems ?? [])];
  for (const check of version.checks ?? []) {
    if (check.state === "block") out.push(check.text);
  }
  if (version.fields.length === 0) out.push("Wzór nie ma żadnego pola do wypełnienia.");
  if (version.client_scope === "selected" && version.client_ids.length === 0)
    out.push("Wybierz klientów, dla których jest wzór.");
  if (!version.name.trim()) out.push("Podaj nazwę wzoru.");
  return out;
}

/** Lista pól do PATCH — bez pola tylko do wyświetlenia. */
export function fieldsPayload(fields: readonly CustomFieldDef[]): Omit<CustomFieldDef, "source_label">[] {
  return fields.map(({ source_label: _label, ...rest }) => rest);
}

/** Zmiana jednego pola listy bez ruszania reszty (stan React). */
export function patchField(
  fields: readonly CustomFieldDef[],
  key: string,
  patch: Partial<Pick<CustomFieldDef, "label" | "kind" | "group" | "source" | "required" | "help">>,
): CustomFieldDef[] {
  return fields.map((f) => (f.key === key ? { ...f, ...patch } : f));
}

/** Etykieta statusu wzoru na liście. */
export function templateStatusLabel(row: {
  withdrawn: boolean;
  active_version_no: number | null;
  working_status: string | null;
  working_status_label: string | null;
}): { label: string; tone: "success" | "warning" | "neutral" | "danger" } {
  if (row.withdrawn) return { label: "wycofany", tone: "danger" };
  if (row.working_status === "pending") return { label: "do zatwierdzenia", tone: "warning" };
  if (row.active_version_no !== null) return { label: `zatwierdzony v${row.active_version_no}`, tone: "success" };
  return { label: row.working_status_label ?? "szkic", tone: "neutral" };
}
