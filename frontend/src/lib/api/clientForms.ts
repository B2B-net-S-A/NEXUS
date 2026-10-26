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
import type { ClientDocument } from "@/lib/api/jobFiles";
import { getAuthenticatedRequestHeaders } from "@/lib/session";

export type ClientFormFieldKind = "line" | "box" | "cell";
export type ClientFormSource = "cv" | "notes" | "profile" | "recruiter";
export type ClientFormStatus = "no_template" | "not_filled" | "filled";

export interface ClientFormField {
  id: string;
  kind: ClientFormFieldKind;
  /** Etykieta pola albo nagłówek kolumny ze wzoru. */
  label: string;
  section: string | null;
  /** Nazwa wiersza ze wzoru (np. kompetencja) albo „Wiersz 2”. */
  row_label: string | null;
  table: string | null;
  value: string | null;
  source: ClientFormSource | null;
  quote: string | null;
}

export interface ClientFormView {
  client_document: ClientDocument;
  status: ClientFormStatus;
  /** Zdanie dla rekrutera, np. gdy model był niedostępny. */
  message: string | null;
  template: { file_id: number; filename: string; summary: string } | null;
  /** DL podmienił wzór po wypełnieniu — warto wypełnić ponownie. */
  template_changed: boolean;
  fields: ClientFormField[];
  extra_rows: { table: number; cells: Record<string, { value: string }> }[];
  missing: string[];
  filled_at: string | null;
  updated_at: string | null;
  model: string | null;
}

const basePath = (stageId: number) => `/api/candidates/stages/${stageId}/client-form`;

export const clientFormKey = (stageId: number) => ["client-form", stageId] as const;

export async function fetchClientForm(stageId: number): Promise<ClientFormView> {
  const { data } = await api.get<ClientFormView>(basePath(stageId));
  return data;
}

export function useClientForm(stageId: number | null, enabled = true) {
  return useQuery({
    queryKey: clientFormKey(stageId ?? 0),
    queryFn: () => fetchClientForm(stageId as number),
    enabled: enabled && stageId != null,
    staleTime: 30_000,
    retry: false,
  });
}

/** Wypełnienie modelem — wartości wpisane przez rekrutera zostają. Do minuty. */
export async function fillClientForm(stageId: number): Promise<ClientFormView> {
  const { data } = await api.post<ClientFormView>(`${basePath(stageId)}/fill`, null, {
    timeout: 180_000,
  });
  return data;
}

/** Poprawki rekrutera: pusta wartość = pole do uzupełnienia. */
export async function saveClientForm(
  stageId: number,
  fields: Record<string, string>,
): Promise<ClientFormView> {
  const { data } = await api.put<ClientFormView>(basePath(stageId), { fields });
  return data;
}

/**
 * Plik Word formularza. Natywny `fetch`, nie axios — `responseType: blob`
 * między domenami zwracał status 0 (jak przy plikach rekrutacji).
 */
export async function downloadClientForm(stageId: number, fallbackName: string): Promise<void> {
  const apiBase = process.env.NEXT_PUBLIC_API_URL || "";
  const res = await fetch(`${apiBase}${basePath(stageId)}/docx`, {
    method: "GET",
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
};

/** Krótka nazwa pola do listy braków: nazwa wiersza + etykieta kolumny. */
export function clientFormFieldName(field: Pick<ClientFormField, "label" | "row_label">): string {
  const row = field.row_label?.trim();
  return row ? `${row} — ${field.label}` : field.label;
}
