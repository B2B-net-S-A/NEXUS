/**
 * Podpis umowy B2B w NEXUSIE (0499) — druga droga obok „Oznacz jako podpisaną”.
 *
 * Wewnętrzne trasy pod `/api/b2b-generator/esign…`, strona kontraktora pod
 * `/api/public/b2b-sign/{token}` (bez konta). Reguły:
 * `docs/claude/kontrakty/podpis-umowy-b2b-w-nexusie.md`.
 */

import { api } from "@/lib/api";

export type EsignMode = "off" | "pilot" | "all";
export type EsignStatus =
  | "sent"
  | "contractor_signed"
  | "completed"
  | "withdrawn"
  | "expired";

export interface EsignPerson {
  id: number;
  name: string;
}

/** Kandydat do DW: zespół rekrutacji i autor, którzy sami widzą umowę ze stawkami. */
export interface EsignCcPerson extends EsignPerson {
  /** Prowadzący rekrutację — zaznaczony od razu (decyzja Artura 27.10.2026). */
  suggested: boolean;
}

export interface EsignSettings {
  mode: EsignMode;
  can_send: boolean;
  company_signers: EsignPerson[];
  /** Tylko dla admina. */
  pilot_user_ids: number[] | null;
}

export interface EsignRequest {
  id: number;
  generated_contract_id: number;
  status: EsignStatus;
  contractor_name: string;
  contractor_email: string | null;
  company_signer_id: number | null;
  company_signer_name: string | null;
  sent_at: string;
  expires_at: string;
  contractor_signed_at: string | null;
  completed_at: string | null;
  closed_at: string | null;
  close_reason: string | null;
  /** Osoby z NEXUSA w DW wysyłki (27.10.2026). */
  cc?: EsignPerson[];
  /** Kto obsługuje wysyłkę (po „Przejmij obsługę” zastępca). */
  handled_by_id?: number | null;
  handled_by_name?: string | null;
  /** Tylko w liście „Czeka na mój podpis” (`/esign/mine`). */
  contract_number?: string | null;
  client_name?: string | null;
}

export interface EsignDefaults {
  contractor_name: string | null;
  contractor_email: string | null;
  company_signers: EsignPerson[];
  mailbox_connected: boolean;
  cc_candidates?: EsignCcPerson[];
}

export interface EsignSendResult {
  request: EsignRequest;
  sign_url: string;
  mail_sent: boolean;
  mail_problem: string | null;
}

export type PublicSignState =
  | "waiting"
  | "signed_by_you"
  | "completed"
  | "expired"
  | "closed";

export interface PublicSignView {
  contract_number: string;
  contractor_name: string;
  status: PublicSignState;
  /** Przy `waiting` do kiedy działa link, przy `expired` kiedy minął termin. */
  expires_at: string | null;
  /** Kontraktor poprosił już o nowy link (27.10.2026). */
  renewal_requested_at?: string | null;
  /** Do kiedy link daje pobrać umowę podpisaną przez obie strony (26.10.2026). */
  signed_pdf_until?: string | null;
}

export const ESIGN_SETTINGS_KEY = ["b2b-esign-settings"] as const;
export const ESIGN_MINE_KEY = ["b2b-esign-mine"] as const;

function pdfForm(file: File): FormData {
  const form = new FormData();
  form.append("file", file);
  return form;
}

const MULTIPART = { headers: { "Content-Type": "multipart/form-data" } };

export const b2bEsignApi = {
  settings: () =>
    api.get<EsignSettings>("/api/b2b-generator/esign/settings").then((r) => r.data),
  saveSettings: (body: {
    mode: EsignMode;
    pilot_user_ids: number[];
    company_signer_ids: number[];
  }) =>
    api
      .put<EsignSettings>("/api/b2b-generator/esign/settings", body)
      .then((r) => r.data),
  defaults: (generatedId: number) =>
    api
      .get<EsignDefaults>(`/api/b2b-generator/generated/${generatedId}/esign/defaults`)
      .then((r) => r.data),
  send: (
    generatedId: number,
    body: {
      contractor_email: string;
      company_signer_id: number;
      days: number;
      cc_user_ids?: number[];
    },
  ) =>
    api
      .post<EsignSendResult>(
        `/api/b2b-generator/generated/${generatedId}/esign/send`,
        body,
      )
      .then((r) => r.data),
  /** „Przedłuż termin”: link z pierwszego maila działa dłużej, PDF ten sam. */
  extend: (requestId: number, days: number) =>
    api
      .post<EsignRequest>(`/api/b2b-generator/esign/${requestId}/extend`, { days })
      .then((r) => r.data),
  /** „Wyślij nowy link” po terminie: ten sam zamrożony PDF (27.10.2026). */
  relink: (requestId: number, days: number) =>
    api
      .post<EsignSendResult>(`/api/b2b-generator/esign/${requestId}/relink`, { days })
      .then((r) => r.data),
  /** „Przejmij obsługę”: przypomnienia i kopia z Twojej skrzynki (27.10.2026). */
  takeOver: (requestId: number) =>
    api
      .post<EsignRequest>(`/api/b2b-generator/esign/${requestId}/take-over`)
      .then((r) => r.data),
  withdraw: (requestId: number, reason: string) =>
    api
      .post<EsignRequest>(`/api/b2b-generator/esign/${requestId}/withdraw`, {
        reason,
      })
      .then((r) => r.data),
  mine: () =>
    api.get<EsignRequest[]>("/api/b2b-generator/esign/mine").then((r) => r.data),
  companyPdf: (requestId: number) =>
    api.get<Blob>(`/api/b2b-generator/esign/${requestId}/pdf`, {
      responseType: "blob",
    }),
  signedPdf: (requestId: number) =>
    api.get<Blob>(`/api/b2b-generator/esign/${requestId}/signed-pdf`, {
      responseType: "blob",
    }),
  companySign: (requestId: number, file: File) =>
    api
      .post<EsignRequest>(
        `/api/b2b-generator/esign/${requestId}/company-sign`,
        pdfForm(file),
        MULTIPART,
      )
      .then((r) => r.data),
};

/** Podpisany plik musi być PDF-em — skan ani zdjęcie nie niosą podpisu. */
export function signedPdfProblem(file: File): string | null {
  if (!/\.pdf$/i.test(file.name)) return "Wgraj podpisany plik PDF.";
  if (file.size === 0) return "Plik jest pusty.";
  if (file.size > 20 * 1024 * 1024) return "Plik jest za duży, może mieć najwyżej 20 MB.";
  return null;
}
