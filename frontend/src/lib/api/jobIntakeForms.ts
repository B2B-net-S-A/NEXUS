/**
 * Niedokończone formularze nowej rekrutacji (04.10.2026) — lustro
 * `/api/job-intake/forms`. Rekrutacja nigdy nie jest szkicem: praca, której
 * nie da się jeszcze opublikować, żyje na koncie autora jako formularz.
 * Widzi i zmienia go wyłącznie autor; serwer kasuje go po 30 dniach albo
 * razem z udanym `POST /api/jobs` (`intake_form_id`).
 */
import api from "@/lib/api";
import type { IntakeForm, MissingCode } from "@/lib/job-request-intake";
import type { RecruiterAssignment } from "@/lib/recruiter-assignment";
import type { PriorityLevel } from "@/lib/request-priority";

export type IntakeFormSource = "text" | "file" | "manual";

/** Pozycja listy `GET /api/job-intake/forms`. */
export interface IntakeFormListItem {
  id: number;
  label: string;
  client_id: number | null;
  client_name: string | null;
  source: string | null;
  updated_at: string;
  expires_at: string | null;
  /** Liczba braków z chwili zapisu — gdy serwer ją oddaje (kopia `form.missing`). */
  missing_count?: number | null;
}

/**
 * Treść formularza (`form` w API) — kształt należy do frontu. `version`
 * pozwala odczytać starszy zapis po zmianie pól (`restoreIntakeForm`).
 */
export interface IntakeFormState {
  version: 1;
  step: "request" | "review";
  form: IntakeForm;
  evidence: string[];
  readByAi: boolean;
  templateJobId: number | null;
  recruiterId: number | null;
  assignment: RecruiterAssignment | null;
  priorityLevel: PriorityLevel;
  similarJobIds: number[];
  /** Braki w chwili zapisu — serwer może z nich policzyć `missing_count`. */
  missing: MissingCode[];
}

export interface IntakeFormRead {
  id: number;
  label: string;
  client_id: number | null;
  client_name: string | null;
  source: string | null;
  request_text: string | null;
  form: unknown;
  updated_at: string;
}

export interface IntakeFormWrite {
  label: string;
  client_id: number | null;
  source: IntakeFormSource;
  request_text: string;
  form: IntakeFormState;
}

export const jobIntakeFormKeys = {
  list: ["job-intake-forms"] as const,
};

export async function fetchIntakeForms(): Promise<IntakeFormListItem[]> {
  const { data } = await api.get<{ items?: IntakeFormListItem[] }>("/api/job-intake/forms");
  return Array.isArray(data?.items) ? data.items : [];
}

export async function fetchIntakeForm(id: number): Promise<IntakeFormRead> {
  const { data } = await api.get<IntakeFormRead>(`/api/job-intake/forms/${id}`);
  return data;
}

export async function saveIntakeForm(
  id: number | null,
  body: IntakeFormWrite,
): Promise<{ id: number; updated_at: string }> {
  const { data } =
    id == null
      ? await api.post<{ id: number; updated_at: string }>("/api/job-intake/forms", body)
      : await api.put<{ id: number; updated_at: string }>(`/api/job-intake/forms/${id}`, body);
  return data;
}

export async function deleteIntakeForm(id: number): Promise<void> {
  await api.delete(`/api/job-intake/forms/${id}`);
}

/** 409 `forms_limit` — osoba ma już komplet niedokończonych formularzy. */
export function isFormsLimitError(error: unknown): boolean {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } } | null)
    ?.response;
  if (response?.status !== 409) return false;
  const detail = response.data?.detail;
  return !!detail && typeof detail === "object" && (detail as { code?: unknown }).code === "forms_limit";
}

/** „usunie się sam za 5 dni” — `null`, gdy serwer nie podał terminu. */
export function expiresInDays(expiresAt: string | null, now: Date = new Date()): number | null {
  if (!expiresAt) return null;
  const end = new Date(expiresAt).getTime();
  if (!Number.isFinite(end)) return null;
  return Math.max(0, Math.ceil((end - now.getTime()) / 86_400_000));
}
