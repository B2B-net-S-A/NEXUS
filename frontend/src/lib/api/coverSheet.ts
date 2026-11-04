/**
 * „Karta przed CV” (Credit Agricole, 29.10.2026) — lustro
 * `backend/app/api/cover_sheets.py`.
 *
 * Klient z wgranym wzorem karty (edytor reguły CV) dostaje z każdym CV
 * jednostronicową kartę dostawcy w Wordzie. Kartę wysyła Delivery Lead
 * z przeglądu „Przejrzyj i wyślij”; ma stawkę do klienta, więc rekruter jej
 * nie widzi (serwer: 403). Włączenie = wzór u klienta, nie nazwa klienta.
 */
import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import { downloadBlob, fetchAuthenticatedDownload } from "@/lib/authenticated-files";
import { parseRateInput } from "@/lib/dl-review-margin";
import type { ClientRateUnit } from "@/lib/person-facts";

export type CoverSheetFieldId =
  | "name"
  | "role"
  | "level"
  | "experience"
  | "profile"
  | "availability"
  | "location"
  | "rate";

export interface CoverSheetField {
  id: CoverSheetFieldId;
  /** Etykieta ze wzoru, np. „Rola:”; pusta dla imienia i nazwiska. */
  label: string;
  value: string | null;
  source: string | null;
  /** Skąd wartość — zdanie dla DL-a („z profilu”, „z 7 lat stażu — sprawdź”). */
  source_label: string | null;
  /** Tekst wzoru za wartością („ doświadczenia komercyjnego”). */
  suffix: string;
  to_check: boolean;
  editable: boolean;
  options: string[] | null;
}

export type CoverSheetLayoutItem =
  | { kind: "field"; id: CoverSheetFieldId }
  | { kind: "text"; text: string; bold: boolean };

export interface CoverSheetEnabled {
  enabled: true;
  template: { filename: string };
  layout: CoverSheetLayoutItem[];
  fields: CoverSheetField[];
  /** Stawka za MD z zapisanej stawki do klienta pary (albo z parametrów). */
  md_rate: number | null;
  md_rate_label: string | null;
  rate_origin: "review" | "stored" | null;
  rate_problem: string | null;
  missing: CoverSheetFieldId[];
}

export type CoverSheetView = { enabled: false } | CoverSheetEnabled;

export interface CoverSheetTemplateMeta {
  filename: string;
  uploaded_at: string;
  uploaded_by_name: string | null;
  fields: { id: CoverSheetFieldId; label: string }[];
}

export interface ClientRateInput {
  raw: string;
  unit: ClientRateUnit;
  currency?: string;
}

const pairPath = (candidateId: number, jobId: number) =>
  `/api/candidates/${candidateId}/recruitments/${jobId}/cover-sheet`;
const templatePath = (clientId: number) => `/api/clients/${clientId}/cover-sheet-template`;

export const coverSheetKey = (candidateId: number, jobId: number) =>
  ["cover-sheet", candidateId, jobId] as const;
export const coverSheetTemplateKey = (clientId: number) =>
  ["cover-sheet-template", clientId] as const;

/** Godzinowa × 8, dzienna bez zmian; miesięcznej karta nie przelicza. */
export function mdRateFromInput(raw: string, unit: ClientRateUnit): number | null {
  const value = parseRateInput(raw);
  if (value == null) return null;
  if (unit === "hourly") return Math.round(value * 8 * 100) / 100;
  if (unit === "daily") return Math.round(value * 100) / 100;
  return null;
}

/** 1298.64 → „1 298,64” — tak jak w pliku Word. */
export function formatMdAmount(amount: number): string {
  const [whole, cents] = amount.toFixed(2).split(".");
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, " ")},${cents}`;
}

function rateParams(rate?: ClientRateInput | null): string {
  const value = rate ? parseRateInput(rate.raw) : null;
  if (!rate || value == null) return "";
  const params = new URLSearchParams({
    client_rate: String(value),
    client_rate_unit: rate.unit,
  });
  if (rate.currency) params.set("client_rate_currency", rate.currency.toUpperCase());
  return `?${params.toString()}`;
}

export async function fetchCoverSheet(candidateId: number, jobId: number): Promise<CoverSheetView> {
  const { data } = await api.get<CoverSheetView>(pairPath(candidateId, jobId));
  return data;
}

/**
 * Karta pary. Bez parametrów stawki — wynagrodzenie liczy się z zapisanej
 * stawki do klienta; stawkę wpisywaną właśnie w przeglądzie przelicza ekran.
 */
export function useCoverSheet(candidateId: number, jobId: number, enabled = true) {
  return useQuery({
    queryKey: coverSheetKey(candidateId, jobId),
    queryFn: () => fetchCoverSheet(candidateId, jobId),
    enabled: enabled && candidateId > 0 && jobId > 0,
    staleTime: 30_000,
    retry: false,
  });
}

/** Poprawki DL-a; pusta wartość = z powrotem wartość wyliczona przez NEXUS. */
export async function saveCoverSheet(
  candidateId: number,
  jobId: number,
  fields: Partial<Record<CoverSheetFieldId, string>>,
): Promise<CoverSheetView> {
  const { data } = await api.put<CoverSheetView>(pairPath(candidateId, jobId), { fields });
  return data;
}

/** Plik Word karty pod nazwą z serwera („Karta_Imię_Nazwisko.docx”). */
export async function downloadCoverSheet(
  candidateId: number,
  jobId: number,
  rate?: ClientRateInput | null,
): Promise<void> {
  const { blob, filename } = await fetchAuthenticatedDownload(
    `${pairPath(candidateId, jobId)}/docx${rateParams(rate)}`,
  );
  downloadBlob(blob, filename ?? "Karta.docx");
}

export async function fetchCoverSheetTemplate(
  clientId: number,
): Promise<CoverSheetTemplateMeta | null> {
  const { data } = await api.get<{ template: CoverSheetTemplateMeta | null }>(templatePath(clientId));
  return data.template;
}

export function useCoverSheetTemplate(clientId: number, enabled = true) {
  return useQuery({
    queryKey: coverSheetTemplateKey(clientId),
    queryFn: () => fetchCoverSheetTemplate(clientId),
    enabled: enabled && clientId > 0,
    staleTime: 60_000,
    retry: false,
  });
}

export async function uploadCoverSheetTemplate(
  clientId: number,
  file: File,
): Promise<CoverSheetTemplateMeta | null> {
  const body = new FormData();
  body.append("file", file);
  const { data } = await api.put<{ template: CoverSheetTemplateMeta | null }>(
    templatePath(clientId),
    body,
    { headers: { "Content-Type": "multipart/form-data" }, timeout: 60_000 },
  );
  return data.template;
}

export async function deleteCoverSheetTemplate(clientId: number): Promise<void> {
  await api.delete(templatePath(clientId));
}
