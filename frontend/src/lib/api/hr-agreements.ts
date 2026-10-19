// „Ludzie w NEXUSIE” — umowy z ludźmi (etap 5, E5, 18.10.2026).
//
// Lustro `backend/app/api/hr_agreements.py` (prefiks `/api/hr/agreements`,
// przełącznik `app_settings['hr_agreements']`, domyślnie wyłączony). Wzory to
// pliki DOCX od Kadr z wersjami; umowa przechodzi szkic → wysłana (Autenti) →
// podpisana / odrzucona / anulowana. Po podpisie stawka, forma i dokument
// trafiają do kartoteki same. Kwoty przychodzą jako tekst dziesiętny.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { downloadAuthenticatedFile, openAuthenticatedFile } from "@/lib/authenticated-files";
import { downloadHrFile, type EmploymentType } from "@/lib/api/hr";
import type { Currency } from "@/lib/api/hr-payroll";

const BASE = "/api/hr/agreements";

export type AgreementStatus = "draft" | "sent" | "signed" | "rejected" | "cancelled";
export type AgreementKind = "agreement" | "annex";
export type TemplateKind = EmploymentType | "annex";
export type SigningChannel = "autenti" | "manual";

export interface AgreementActions {
  edit: boolean;
  send: boolean;
  withdraw: boolean;
  cancel: boolean;
  mark_signed: boolean;
  apply: boolean;
}

export interface AgreementTemplateRef {
  template_id: number;
  version_id: number;
  name: string;
  kind: TemplateKind;
  version: number;
}

export interface Agreement {
  id: number;
  user_id: number;
  person_name: string | null;
  kind: AgreementKind;
  employment_type: EmploymentType;
  form_label: string;
  title: string;
  status: AgreementStatus;
  status_label: string;
  template: AgreementTemplateRef | null;
  base_agreement_id: number | null;
  hourly_rate: string;
  currency: Currency;
  rate_basis: "netto" | "brutto";
  /** Od kiedy stawka wchodzi do historii stawek (1. dzień miesiąca). */
  rate_from: string;
  start_date: string;
  end_date: string | null;
  agreement_date: string;
  hours_confirmation: boolean;
  payout_day: number | null;
  coordinator_user_id: number | null;
  coordinator_name: string | null;
  signing_channel: SigningChannel | null;
  signing_channel_label: string | null;
  sent_at: string | null;
  signed_on: string | null;
  signed_at: string | null;
  manual_reason: string | null;
  rejected_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  last_error: string | null;
  applied_at: string | null;
  apply_error: string | null;
  document_id: number | null;
  symfonia_pending: boolean;
  created_at: string | null;
  actions: AgreementActions;
  /** Tylko w odpowiedzi zapisu: rok bez minimalnej stawki, inna waluta. */
  warning?: string | null;
}

export interface AgreementDefaults {
  employment_type: EmploymentType;
  payout_day: number;
  coordinator_user_id: number | null;
  coordinator_name: string | null;
  hours_confirmation: boolean;
  currency: Currency;
  hourly_rate: string | null;
  base_agreement_id: number | null;
  agreement_date: string;
}

export interface PersonAgreements {
  person: {
    user_id: number;
    name: string;
    employment_type: EmploymentType;
    employment_status: string;
  };
  defaults: AgreementDefaults;
  /** Minimalna stawka godzinowa na zleceniu: rok → kwota (D7). */
  minimum_rates: Record<string, string>;
  autenti_configured: boolean;
  can_write: boolean;
  /** Podpis tego widza przepisuje stawkę (Płace albo admin); inaczej robią to Płace. */
  applies_rate: boolean;
  agreements: Agreement[];
}

export interface AgreementInput {
  template_id?: number;
  base_agreement_id?: number | null;
  hourly_rate?: string;
  currency?: Currency;
  start_date?: string;
  end_date?: string | null;
  agreement_date?: string;
  hours_confirmation?: boolean;
  payout_day?: number | null;
  coordinator_user_id?: number | null;
}

export interface TemplateVersion {
  id: number;
  version: number;
  file_name: string;
  file_size: number;
  fields: string[];
  created_at: string | null;
  agreements: number;
}

export interface AgreementTemplate {
  id: number;
  kind: TemplateKind;
  kind_label: string;
  name: string;
  description: string | null;
  is_active: boolean;
  /** Najnowsza wersja pierwsza. */
  versions: TemplateVersion[];
}

export interface TemplateField {
  field: string;
  label: string;
}

export interface AgreementTemplates {
  items: AgreementTemplate[];
  fields: TemplateField[];
  required: Record<TemplateKind, string[]>;
  kinds: Record<TemplateKind, string>;
  max_bytes: number;
}

export interface AgreementSettings {
  enabled: boolean;
  autenti_configured: boolean;
}

export const agreementKeys = {
  all: ["hr", "agreements"] as const,
  person: (userId: number) => ["hr", "agreements", "person", userId] as const,
  templates: (active: boolean) => ["hr", "agreements", "templates", active] as const,
  settings: ["hr", "agreements", "settings"] as const,
};

export const agreementPaths = {
  pdf: (id: number) => `${BASE}/${id}/pdf`,
  docx: (id: number) => `${BASE}/${id}/docx`,
  versionFile: (id: number) => `${BASE}/templates/versions/${id}/file`,
  versionSample: (id: number) => `${BASE}/templates/versions/${id}/sample`,
};

export function usePersonAgreements(userId: number, enabled = true) {
  return useQuery({
    queryKey: agreementKeys.person(userId),
    queryFn: async () => (await api.get<PersonAgreements>(`${BASE}/people/${userId}`)).data,
    enabled,
    retry: false,
  });
}

export function useAgreementTemplates(active = false, enabled = true) {
  return useQuery({
    queryKey: agreementKeys.templates(active),
    queryFn: async () =>
      (await api.get<AgreementTemplates>(`${BASE}/templates`, { params: { active } })).data,
    enabled,
    retry: false,
  });
}

export function useAgreementSettings(enabled = true) {
  return useQuery({
    queryKey: agreementKeys.settings,
    queryFn: async () => (await api.get<AgreementSettings>(`${BASE}/settings`)).data,
    enabled,
    retry: false,
  });
}

function useInvalidateAgreements() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: agreementKeys.all }),
      // Po podpisie zmienia się kartoteka, stawki i e-teczka osoby.
      queryClient.invalidateQueries({ queryKey: ["hr", "people"] }),
      queryClient.invalidateQueries({ queryKey: ["hr", "payroll"] }),
      queryClient.invalidateQueries({ queryKey: ["hr", "documents"] }),
    ]);
}

export function useSaveAgreementSettings() {
  const invalidate = useInvalidateAgreements();
  return useMutation({
    mutationFn: async (enabled: boolean) =>
      (await api.put<AgreementSettings>(`${BASE}/settings`, { enabled })).data,
    onSuccess: invalidate,
  });
}

export function useCreateAgreement(userId: number) {
  const invalidate = useInvalidateAgreements();
  return useMutation({
    mutationFn: async (input: AgreementInput) =>
      (await api.post<Agreement>(`${BASE}/people/${userId}`, input)).data,
    onSuccess: invalidate,
  });
}

export function useUpdateAgreement() {
  const invalidate = useInvalidateAgreements();
  return useMutation({
    mutationFn: async ({ id, input }: { id: number; input: AgreementInput }) =>
      (await api.patch<Agreement>(`${BASE}/${id}`, input)).data,
    onSuccess: invalidate,
  });
}

function useAgreementCommand(path: "send" | "withdraw" | "apply") {
  const invalidate = useInvalidateAgreements();
  return useMutation({
    mutationFn: async (id: number) => (await api.post<Agreement>(`${BASE}/${id}/${path}`)).data,
    // Nieudana wysyłka zapisuje próbę i powód — lista też musi się odświeżyć.
    onSettled: invalidate,
  });
}

export const useSendAgreement = () => useAgreementCommand("send");
export const useWithdrawAgreement = () => useAgreementCommand("withdraw");
export const useApplyAgreement = () => useAgreementCommand("apply");

export function useCancelAgreement() {
  const invalidate = useInvalidateAgreements();
  return useMutation({
    mutationFn: async ({ id, reason }: { id: number; reason: string }) =>
      (await api.post<Agreement>(`${BASE}/${id}/cancel`, { reason })).data,
    onSuccess: invalidate,
  });
}

export function useMarkSigned() {
  const invalidate = useInvalidateAgreements();
  return useMutation({
    mutationFn: async (input: { id: number; file: File; signedOn: string; reason: string }) => {
      const body = new FormData();
      body.append("file", input.file);
      body.append("signed_on", input.signedOn);
      body.append("reason", input.reason);
      return (
        await api.post<Agreement>(`${BASE}/${input.id}/mark-signed`, body, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

export function useUploadAgreementTemplate() {
  const invalidate = useInvalidateAgreements();
  return useMutation({
    mutationFn: async (input: {
      file: File;
      kind: TemplateKind;
      name: string;
      description?: string;
    }) => {
      const body = new FormData();
      body.append("file", input.file);
      body.append("kind", input.kind);
      body.append("name", input.name);
      if (input.description) body.append("description", input.description);
      return (
        await api.post<{ id: number }>(`${BASE}/templates`, body, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

export function useUploadTemplateVersion() {
  const invalidate = useInvalidateAgreements();
  return useMutation({
    mutationFn: async ({ templateId, file }: { templateId: number; file: File }) => {
      const body = new FormData();
      body.append("file", file);
      return (
        await api.post<TemplateVersion>(`${BASE}/templates/${templateId}/versions`, body, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

export function useUpdateAgreementTemplate() {
  const invalidate = useInvalidateAgreements();
  return useMutation({
    mutationFn: async ({
      id,
      ...changes
    }: {
      id: number;
      name?: string;
      description?: string | null;
      is_active?: boolean;
    }) => (await api.patch(`${BASE}/templates/${id}`, changes)).data,
    onSuccess: invalidate,
  });
}

export function openAgreementPdf(id: number): Promise<void> {
  return openAuthenticatedFile(agreementPaths.pdf(id), "application/pdf", "umowa.pdf");
}

/** Plik Word umowy pod nazwą z serwera (bez polskich znaków i dwukropków). */
export function downloadAgreementDocx(id: number): Promise<void> {
  return downloadHrFile(agreementPaths.docx(id), "umowa.docx");
}

export function downloadTemplateVersion(
  version: Pick<TemplateVersion, "id" | "file_name">,
  variant: "file" | "sample",
): Promise<void> {
  const path =
    variant === "sample" ? agreementPaths.versionSample(version.id) : agreementPaths.versionFile(version.id);
  const name = variant === "sample" ? `Probka_${version.file_name}` : version.file_name;
  return downloadAuthenticatedFile(path, name);
}
