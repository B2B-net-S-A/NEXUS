/**
 * Formularz CV klienta pary osoba × rekrutacja (0522, 26.10.2026) — lustro
 * `/api/candidates/stages/{stageId}/client-form`.
 *
 * U klienta, który zamiast CV firmowego bierze własny formularz (np. SWZ
 * Centrum e-Zdrowia), NEXUS wypełnia wzór z Plików rekrutacji danymi z CV,
 * screeningu i notatek. Każda wartość ma źródło; czego nie było w źródłach,
 * rekruter uzupełnia ręcznie. Plik Word powstaje w układzie wzoru klienta.
 */
import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import type { ClientDocument, ClientFormKind } from "@/lib/api/jobFiles";
import { getAuthenticatedRequestHeaders } from "@/lib/session";

export type ClientFormFieldKind = "line" | "box" | "cell";
/** `client_rule` — reguła klienta „doświadczenie = 10/10” w polach skali (0755). */
export type ClientFormSource = "cv" | "notes" | "profile" | "recruiter" | "client_rule";
export type ClientFormStatus = "no_template" | "not_filled" | "filled";

export type ClientFormYearsLevel = "role" | "implied";

/** Stanowisko z CV, z którego kod policzył lata pola (cytat z datami i dowód). */
export interface ClientFormYearsRole {
  key: string;
  employer: string;
  title: string;
  /** „RRRR-MM” albo sam „RRRR”, gdy CV nie podaje miesiąca. */
  start: string;
  /** ``null`` = stanowisko trwa. */
  end: string | null;
  /** „12.2021 – 09.2022”, „2022 – obecnie”. */
  period: string;
  quote: string;
  /** „role” — opis stanowiska nazywa kompetencję, „implied” — praca jej wymagała. */
  level: ClientFormYearsLevel;
  /** Fragment opisu stanowiska o kompetencji (łączny staż — brak). */
  evidence: string | null;
  /** Rola liczy się do wartości pola (rekruter zdejmuje ją w siatce). */
  on: boolean;
}

/** Siatka lat pola (19.11.2026): lata liczy kod z ról, nie model. */
export interface ClientFormYears {
  kind: "total" | "competency" | "points";
  basis: ClientFormYearsRole[];
  /** Kompetencja tylko na liście umiejętności — lat z tego nie ma. */
  skills: string | null;
  /** Wiersz „ponad minimum”: minimum z wymagań (miesiące). */
  minimum_months: number | null;
  minimum_unknown?: boolean;
  /** Punkty z lat: progi z zasad oceny. */
  thresholds: { years: number; points: number }[];
  max_points: number | null;
  question: string;
  /** Brak idzie do ściągi screeningu. */
  ask: boolean;
  months: number;
}

export interface ClientFormField {
  id: string;
  kind: ClientFormFieldKind;
  /** Etykieta pola albo nagłówek kolumny ze wzoru. */
  label: string;
  /** Tabela punktowa: maksimum punktów w tym wierszu. */
  max_points?: number;
  section: string | null;
  /** Nazwa wiersza ze wzoru (np. kompetencja) albo „Wiersz 2”. */
  row_label: string | null;
  table: string | null;
  value: string | null;
  source: ClientFormSource | null;
  quote: string | null;
  years?: ClientFormYears | null;
}

export interface ClientFormUpload {
  filename: string;
  content_type: string;
  size: number;
  uploaded_at: string;
}

export interface ClientFormView {
  /** 0525: „form” — formularz CV (Word), „score” — tabela punktowa (Excel). */
  kind?: ClientFormKind;
  client_document: ClientDocument;
  /** Tylko tabela punktowa: suma wpisanych punktów i maksimum wierszy z punktami. */
  points?: { total: number; max: number } | null;
  status: ClientFormStatus;
  /** Zdanie dla rekrutera, np. gdy model był niedostępny. */
  message: string | null;
  template: { file_id: number; filename: string; summary: string } | null;
  /** DL podmienił wzór po wypełnieniu — warto wypełnić ponownie. */
  template_changed: boolean;
  /**
   * 0755: plik wypełniony poza NEXUSEM, wgrany z dysku — idzie do QC
   * i do klienta zamiast wypełnienia z NEXUSA.
   */
  uploaded?: ClientFormUpload | null;
  fields: ClientFormField[];
  extra_rows: { table: number; cells: Record<string, { value: string }> }[];
  missing: string[];
  filled_at: string | null;
  updated_at: string | null;
  model: string | null;
}

const basePath = (stageId: number) => `/api/candidates/stages/${stageId}/client-form`;
/** Formularz to domyślny rodzaj — jego adresy zostają bez parametru. */
const kindQuery = (kind: ClientFormKind) => (kind === "score" ? "?kind=score" : "");

export const clientFormKey = (stageId: number, kind: ClientFormKind = "form") =>
  ["client-form", stageId, kind] as const;

export async function fetchClientForm(
  stageId: number,
  kind: ClientFormKind = "form",
): Promise<ClientFormView> {
  const { data } = await api.get<ClientFormView>(`${basePath(stageId)}${kindQuery(kind)}`);
  return data;
}

export function useClientForm(
  stageId: number | null,
  enabled = true,
  kind: ClientFormKind = "form",
) {
  return useQuery({
    queryKey: clientFormKey(stageId ?? 0, kind),
    queryFn: () => fetchClientForm(stageId as number, kind),
    enabled: enabled && stageId != null,
    staleTime: 30_000,
    retry: false,
  });
}

/** Wypełnienie modelem — wartości wpisane przez rekrutera zostają. Do minuty. */
export async function fillClientForm(
  stageId: number,
  kind: ClientFormKind = "form",
): Promise<ClientFormView> {
  const { data } = await api.post<ClientFormView>(`${basePath(stageId)}/fill${kindQuery(kind)}`, null, {
    timeout: 180_000,
  });
  return data;
}

/** Poprawki rekrutera: pusta wartość = pole do uzupełnienia. */
export async function saveClientForm(
  stageId: number,
  fields: Record<string, string>,
  kind: ClientFormKind = "form",
): Promise<ClientFormView> {
  const { data } = await api.put<ClientFormView>(`${basePath(stageId)}${kindQuery(kind)}`, {
    fields,
  });
  return data;
}

/**
 * Siatka lat: które role liczą się do pola i które braki idą do ściągi
 * screeningu. Wartość liczy serwer z zapisanych ról.
 */
export async function saveClientFormYears(
  stageId: number,
  payload: { roles?: Record<string, string[]>; ask?: string[] },
  kind: ClientFormKind = "form",
): Promise<ClientFormView> {
  const { data } = await api.put<ClientFormView>(
    `${basePath(stageId)}/years${kindQuery(kind)}`,
    { roles: payload.roles ?? {}, ...(payload.ask ? { ask: payload.ask } : {}) },
  );
  return data;
}

/** Pliki przyjmowane przy wgraniu — lustro `UPLOAD_TYPES` w `client_forms.py`. */
export const CLIENT_FORM_UPLOAD_ACCEPT: Record<ClientFormKind, string> = {
  form: ".docx,.pdf",
  score: ".xlsx",
};

/** Wgraj wypełniony formularz (Word/PDF) albo tabelę (Excel); zastępuje poprzedni plik. */
export async function uploadClientForm(
  stageId: number,
  file: File,
  kind: ClientFormKind = "form",
): Promise<ClientFormView> {
  const body = new FormData();
  body.append("file", file);
  const { data } = await api.post<ClientFormView>(`${basePath(stageId)}/upload${kindQuery(kind)}`, body, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

/** Usuń wgrany plik — wraca wypełnienie z NEXUSA (albo „niewypełniony”). */
export async function deleteUploadedClientForm(
  stageId: number,
  kind: ClientFormKind = "form",
): Promise<ClientFormView> {
  const { data } = await api.delete<ClientFormView>(`${basePath(stageId)}/upload${kindQuery(kind)}`);
  return data;
}

/**
 * Plik Word formularza (albo plik wgrany z dysku, gdy jest). Natywny `fetch`, nie axios — `responseType: blob`
 * między domenami zwracał status 0 (jak przy plikach rekrutacji).
 */
export async function downloadClientForm(
  stageId: number,
  fallbackName: string,
  kind: ClientFormKind = "form",
): Promise<void> {
  const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
  const res = await fetch(`${apiBase}${basePath(stageId)}/docx${kindQuery(kind)}`, {
    method: "GET",
    credentials: "include",
    headers: getAuthenticatedRequestHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  const header = res.headers.get("content-disposition") ?? "";
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header)?.[1];
  const name = encoded ? decodeURIComponent(encoded) : fallbackName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const CLIENT_FORM_SOURCE_LABEL: Record<ClientFormSource, string> = {
  cv: "z CV",
  notes: "ze screeningu i notatek",
  profile: "z profilu",
  recruiter: "wpisane ręcznie",
  client_rule: "reguła klienta: doświadczenie = 10/10",
};

/** Krótka nazwa pola do listy braków: nazwa wiersza + etykieta kolumny. */
export function clientFormFieldName(field: Pick<ClientFormField, "label" | "row_label">): string {
  const row = field.row_label?.trim();
  return row ? `${row} — ${field.label}` : field.label;
}
