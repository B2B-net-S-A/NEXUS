// „Ludzie w NEXUSIE”, etap 3 (O2, O3, O6): pakiet klienta „Wejście u klienta”,
// mail powitalny konsultanta i wzory protokołów recepcji.
//
// Lustro `backend/app/api/client_onboarding.py` (prefiks
// `/api/client-onboarding`) i tras wzorów w `backend/app/api/equipment.py`
// (`/api/equipment/protocol-templates`).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import type { EquipmentProvider, ProtocolKind } from "@/lib/api/equipment";

const BASE = "/api/client-onboarding";
const TEMPLATES = "/api/equipment/protocol-templates";

// ── Pakiet klienta ────────────────────────────────────────────────────────────

/** Kto po naszej stronie pilnuje pozycji (role z `hr_lifecycle_schema.TASK_ASSIGNEES`). */
export type PackAssignee =
  | "care_owner"
  | "delivery_lead"
  | "administration"
  | "it"
  | "reception";

export interface PackItem {
  name: string;
  note: string | null;
  assignee: PackAssignee | null;
  /** Dni robocze względem startu kontraktu (ujemne = przed startem). */
  offset_days: number | null;
  required: boolean;
  requires_file: boolean;
}

export interface PackTemplateOption {
  id: number;
  kind: ProtocolKind;
  name: string;
  description: string | null;
  is_active: boolean;
}

export interface ClientPack {
  client_id: number;
  exists: boolean;
  version: number;
  updated_at: string | null;
  updated_by: number | null;
  updated_by_name: string | null;
  equipment: {
    provider: EquipmentProvider;
    issue_template_id: number | null;
    return_template_id: number | null;
    ours: PackItem[];
    client: PackItem[];
  };
  first_day: {
    contact_id: number | null;
    place: string | null;
    time: string | null;
    bring: string | null;
  };
  documents: PackItem[];
  accesses: PackItem[];
  /** Kontrakty klienta przed startem i w trakcie. */
  live_contracts: number;
  options: {
    templates: PackTemplateOption[];
    contacts: { id: number; name: string; position: string | null }[];
    assignees: { value: PackAssignee; label: string }[];
  };
  can_edit: { equipment: boolean; rest: boolean };
}

export interface PackItemInput {
  name: string;
  note?: string | null;
  assignee?: PackAssignee | null;
  offset_days?: number | null;
  required?: boolean;
  requires_file?: boolean;
}

export interface ClientPackSave {
  expected_version?: number;
  equipment?: {
    /** Tylko przy zmianie flagi; `expected_provider` = wartość sprzed edycji (inna = 409). */
    provider?: EquipmentProvider;
    expected_provider?: EquipmentProvider;
    issue_template_id: number | null;
    return_template_id: number | null;
    ours: PackItemInput[];
    client: PackItemInput[];
  };
  first_day?: ClientPack["first_day"];
  documents?: PackItemInput[];
  accesses?: PackItemInput[];
}

export const clientOnboardingKeys = {
  pack: (clientId: number) => ["client-onboarding", "pack", clientId] as const,
  preview: (clientId: number) => ["client-onboarding", "preview", clientId] as const,
  welcome: (contractId: number) => ["client-onboarding", "welcome", contractId] as const,
  templates: ["equipment", "protocol-templates"] as const,
};

export function useClientPack(clientId: number, enabled = true) {
  return useQuery({
    queryKey: clientOnboardingKeys.pack(clientId),
    queryFn: async () => (await api.get<ClientPack>(`${BASE}/clients/${clientId}/pack`)).data,
    enabled: enabled && clientId > 0,
    retry: false,
  });
}

export function useSaveClientPack(clientId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: ClientPackSave) =>
      (await api.put<ClientPack>(`${BASE}/clients/${clientId}/pack`, payload)).data,
    onSuccess: (pack) => {
      queryClient.setQueryData(clientOnboardingKeys.pack(clientId), pack);
      void queryClient.invalidateQueries({ queryKey: clientOnboardingKeys.preview(clientId) });
      // Flaga „sprzęt od nas” na profilu klienta czyta własny klucz.
      void queryClient.invalidateQueries({ queryKey: ["equipment", "provider", clientId] });
    },
  });
}

export function useClientPackPreview(clientId: number, enabled: boolean) {
  return useQuery({
    queryKey: clientOnboardingKeys.preview(clientId),
    queryFn: async () =>
      (
        await api.get<{ subject: string; body: string }>(
          `${BASE}/clients/${clientId}/pack/welcome-preview`,
        )
      ).data,
    enabled: enabled && clientId > 0,
    retry: false,
  });
}

// ── Mail powitalny ────────────────────────────────────────────────────────────

export interface WelcomeMailIssue {
  code: "no_email" | "no_start" | "no_pack" | "no_contact" | "no_owner";
  message: string;
  /** Blokuje wysyłkę (bez adresu albo dnia startu). */
  blocking: boolean;
}

export interface WelcomeMailSent {
  id: number;
  sent_at: string | null;
  sent_by: number | null;
  sent_by_name: string | null;
  recipient_email: string;
  subject: string;
  body: string;
  /** `simulated` — tryb symulacji Microsoft 365, nic nie wyszło; `uncertain` —
   * Graph mógł przyjąć mail (bez ponowienia, żeby nie wysłać dwa razy). */
  delivery: "sent" | "simulated" | "uncertain";
}

export interface WelcomeMailState {
  contract_id: number;
  /** Przełącznik `consultant_welcome_mail` (domyślnie wyłączony). */
  enabled: boolean;
  /** Skrzynka administracja@ ustawiona na serwerze. */
  mailbox_ready: boolean;
  /** Kanał wysyłki działa (`HR_M365_MODE` inny niż `off`, są poświadczenia). */
  transport_ready: boolean;
  can_toggle: boolean;
  /** Rola opiekuna (Delivery Lead, TCM, admin). */
  is_sender: boolean;
  can_send: boolean;
  sent: WelcomeMailSent | null;
  draft: {
    recipient_email: string | null;
    recipient_name: string | null;
    subject: string;
    body: string;
  } | null;
  issues: WelcomeMailIssue[];
}

export function useWelcomeMail(contractId: number, enabled = true) {
  return useQuery({
    queryKey: clientOnboardingKeys.welcome(contractId),
    queryFn: async () =>
      (await api.get<WelcomeMailState>(`${BASE}/contracts/${contractId}/welcome-mail`)).data,
    enabled: enabled && contractId > 0,
    retry: false,
  });
}

export function useSendWelcomeMail(contractId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { subject: string; body: string }) =>
      (
        await api.post<WelcomeMailState>(
          `${BASE}/contracts/${contractId}/welcome-mail`,
          payload,
        )
      ).data,
    onSuccess: (state) => {
      queryClient.setQueryData(clientOnboardingKeys.welcome(contractId), state);
      // Wysłanie odhacza pozycję „Mail powitalny” w wejściu kontraktu
      // (klucze `lifecycleKeys` z `lib/api/hr-lifecycle.ts`).
      void queryClient.invalidateQueries({ queryKey: ["hr", "lifecycle"] });
    },
  });
}

export function useSetWelcomeMailSwitch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (enabled: boolean) =>
      (await api.put<{ enabled: boolean }>(`${BASE}/welcome-mail/switch`, { enabled })).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["client-onboarding", "welcome"] });
    },
  });
}

// ── Wzory protokołów (Sprzęt → Wzory protokołów) ─────────────────────────────

export interface ProtocolTemplate {
  id: number;
  kind: ProtocolKind;
  name: string;
  description: string | null;
  file_name: string;
  file_size: number;
  fields: string[];
  is_active: boolean;
  created_at: string | null;
  /** W ilu pakietach klientów wzór jest wybrany. */
  packs: number;
  /** Ile protokołów z niego powstało. */
  protocols: number;
}

export interface ProtocolTemplateField {
  field: string;
  label: string;
  scope: "protocol" | "line";
}

export interface ProtocolTemplateList {
  items: ProtocolTemplate[];
  fields: ProtocolTemplateField[];
  required: Record<ProtocolKind, string[]>;
  max_bytes: number;
}

export function useProtocolTemplates(enabled = true) {
  return useQuery({
    queryKey: clientOnboardingKeys.templates,
    queryFn: async () => (await api.get<ProtocolTemplateList>(TEMPLATES)).data,
    enabled,
    retry: false,
  });
}

function useInvalidateTemplates() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: clientOnboardingKeys.templates });
    void queryClient.invalidateQueries({ queryKey: ["client-onboarding", "pack"] });
  };
}

export function useUploadProtocolTemplate() {
  const invalidate = useInvalidateTemplates();
  return useMutation({
    mutationFn: async (input: {
      file: File;
      kind: ProtocolKind;
      name: string;
      description?: string;
    }) => {
      const body = new FormData();
      body.append("file", input.file);
      body.append("kind", input.kind);
      body.append("name", input.name);
      if (input.description) body.append("description", input.description);
      return (
        await api.post<ProtocolTemplate>(TEMPLATES, body, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

export function useUpdateProtocolTemplate() {
  const invalidate = useInvalidateTemplates();
  return useMutation({
    mutationFn: async ({
      id,
      ...payload
    }: {
      id: number;
      name?: string;
      description?: string | null;
      is_active?: boolean;
    }) => (await api.patch<ProtocolTemplate>(`${TEMPLATES}/${id}`, payload)).data,
    onSuccess: invalidate,
  });
}

export function downloadProtocolTemplate(
  template: Pick<ProtocolTemplate, "id" | "file_name">,
  variant: "file" | "sample",
): Promise<void> {
  const name = variant === "sample" ? `Probka_${template.file_name}` : template.file_name;
  return downloadAuthenticatedFile(`${TEMPLATES}/${template.id}/${variant}`, name);
}

export function downloadStandardTemplate(kind: ProtocolKind): Promise<void> {
  return downloadAuthenticatedFile(
    `${TEMPLATES}/standard/${kind}`,
    `Wzor_protokolu_${kind}_standard.docx`,
  );
}
