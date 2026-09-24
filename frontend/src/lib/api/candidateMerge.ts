// Scalanie duplikatów kandydatów (admin + Head of Recruitment).
//
// Lustro `backend/app/api/candidate_merge.py`. Plan liczy serwer: które pola
// się różnią, ile wierszy przejdzie na ocalałego i ile par zderzy się na
// unikalności (zostaje nowszy wiersz). Front wybiera tylko wartości pól
// w konfliktach i odsyła odcisk podglądu — inny stan = 409.

import { api } from "@/lib/api";
import { hasRole, type User } from "@/store/auth";

export type MergeChoice = "survivor" | "duplicate";

export interface MergePerson {
  id: number;
  name: string | null;
  lastname: string | null;
  email: string | null;
  phone: string | null;
  city: string | null;
  external_source: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MergeField {
  field: string;
  label: string;
  survivor: string | number | null;
  duplicate: string | number | null;
  conflict: boolean;
  default: MergeChoice;
}

export interface MergeReference {
  table: string;
  column: string;
  rows: number;
  conflicts: number;
  unresolvable: boolean;
}

export interface MergePlan {
  survivor_id: number;
  duplicate_id: number;
  survivor: MergePerson;
  duplicate: MergePerson;
  fields: MergeField[];
  references: MergeReference[];
  polymorphic: { table: string; rows: number }[];
  moved_rows: number;
  conflicts: number;
  blockers: { code: string; message: string }[];
  can_apply: boolean;
  fingerprint: string;
}

export interface MergeResult {
  survivor_id: number;
  duplicate_id: number;
  moved_rows: number;
  replaced_rows: number;
  fields_from_duplicate: string[];
}

export interface DuplicateSuggestion {
  candidate_id: number;
  name: string | null;
  lastname: string | null;
  email: string | null;
  match_score: number;
  match_reasons: string[];
}

/** Lustro `HeadOfRecruitmentPlus` na trasach scalania. */
export function canMergeCandidates(user: Pick<User, "role" | "roles"> | null | undefined): boolean {
  return hasRole(user, "admin", "head_of_recruitment");
}

export const candidateMergeKeys = {
  suggestions: (candidateId: number) => ["candidate-merge", "suggestions", candidateId] as const,
  preview: (survivorId: number, duplicateId: number | null) =>
    ["candidate-merge", "preview", survivorId, duplicateId] as const,
};

export async function fetchDuplicateSuggestions(candidate: {
  id: number;
  email?: string | null;
  phone?: string | null;
  linkedin?: string | null;
  name?: string | null;
  lastname?: string | null;
}): Promise<DuplicateSuggestion[]> {
  const { data } = await api.post<DuplicateSuggestion[]>("/api/candidates/check-duplicates", {
    email: candidate.email || undefined,
    phone: candidate.phone || undefined,
    linkedin: candidate.linkedin || undefined,
    name: candidate.name || undefined,
    lastname: candidate.lastname || undefined,
    exclude_candidate_id: candidate.id,
  });
  return data;
}

export async function fetchMergePreview(survivorId: number, duplicateId: number): Promise<MergePlan> {
  const { data } = await api.get<MergePlan>(`/api/candidates/${survivorId}/merge-preview`, {
    params: { other: duplicateId },
  });
  return data;
}

export async function applyMerge(
  survivorId: number,
  plan: MergePlan,
  choices: Record<string, MergeChoice>,
): Promise<MergeResult> {
  const { data } = await api.post<MergeResult>(`/api/candidates/${survivorId}/merge`, {
    other: plan.duplicate_id,
    fingerprint: plan.fingerprint,
    choices: conflictChoices(plan, choices),
  });
  return data;
}

/** Wybory wysyłane na serwer: tylko pola w konflikcie, brak wyboru = ocalały. */
export function conflictChoices(
  plan: MergePlan,
  choices: Record<string, MergeChoice>,
): Record<string, MergeChoice> {
  const out: Record<string, MergeChoice> = {};
  for (const field of plan.fields) {
    if (field.conflict) out[field.field] = choices[field.field] ?? "survivor";
  }
  return out;
}

/** Wartość, która zostanie na profilu po scaleniu. */
export function resultingValue(
  field: MergeField,
  choices: Record<string, MergeChoice>,
): string | number | null {
  const source = field.conflict ? (choices[field.field] ?? "survivor") : field.default;
  return source === "duplicate" ? field.duplicate : field.survivor;
}

/** Nowy plan z 409 „fingerprint_mismatch” — okno pokazuje aktualny stan. */
export function planFromMergeConflict(error: unknown): MergePlan | null {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } } | null)
    ?.response;
  if (response?.status !== 409) return null;
  const detail = response.data?.detail;
  if (detail && typeof detail === "object" && "plan" in detail) {
    const plan = (detail as { plan?: unknown }).plan;
    if (plan && typeof plan === "object" && "fingerprint" in plan) return plan as MergePlan;
  }
  return null;
}

const TABLE_LABELS: Record<string, string> = {
  candidate_stages: "Etapy w rekrutacjach",
  recruitment_processes: "Procesy rekrutacji",
  notes: "Notatki",
  candidate_documents: "Dokumenty i CV",
  contracts: "Kontrakty",
  application_submissions: "Zgłoszenia z formularza",
  my_people_overrides: "Moi ludzie",
  candidate_pins: "Przypięcia",
  emails: "Maile",
  activities: "Historia zmian",
  notifications: "Powiadomienia",
  candidate_contact_events: "Kontakty z kandydatem",
};

export function referenceLabel(table: string): string {
  return TABLE_LABELS[table] ?? table.replace(/_/g, " ");
}
