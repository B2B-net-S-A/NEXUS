// Panel konsultanta od strony NEXUSA: lustro `backend/app/api/consultant_panel.py`.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { SettlementMode } from "@/lib/api/consultant-portal";

const BASE = "/api/consultant-panel";

export type PanelState = "off" | "pilot" | "all";

export interface PanelMaterial {
  id: number;
  title: string;
  kind: "file" | "link";
  url: string | null;
  file_name: string | null;
  shared: boolean;
  selected: boolean;
}

export interface PanelActivation {
  active: boolean;
  email: string | null;
  activated_at: string | null;
  activated_by: string | null;
  deactivated_at: string | null;
  last_login_at: string | null;
  address_changed: boolean;
}

export interface PanelProposal {
  contract_id: number;
  client_id: number | null;
  client: string | null;
  start_date: string | null;
  can_activate: boolean;
  suggested_email: string | null;
  activation: PanelActivation;
  materials: PanelMaterial[];
  mail: {
    enabled: boolean;
    subject: string;
    body: string;
    issues: { code: string; message: string; blocking: boolean }[];
    sent_at: string | null;
  };
  portal_state: PanelState;
}

export interface PanelSwitches {
  state: PanelState;
  welcome_mail: boolean;
}

export interface SettlementRule {
  client_id: number;
  mode: SettlementMode | null;
  instructions: string;
  updated_at: string | null;
}

const keys = {
  proposal: (contractId: number) => ["consultant-panel", "contract", contractId] as const,
  switches: ["consultant-panel", "settings"] as const,
  settlement: (clientId: number) => ["consultant-panel", "settlement", clientId] as const,
};

export function usePanelProposal(contractId: number) {
  return useQuery({
    queryKey: keys.proposal(contractId),
    queryFn: async () => (await api.get<PanelProposal>(`${BASE}/contracts/${contractId}`)).data,
    retry: false,
  });
}

export function usePanelActivate(contractId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      email: string;
      material_ids: number[];
      send_mail: boolean;
      subject?: string;
      body?: string;
    }) =>
      (
        await api.post<{ activation: PanelActivation; mail_error: string | null }>(
          `${BASE}/contracts/${contractId}/activation`,
          body,
        )
      ).data,
    onSettled: () => client.invalidateQueries({ queryKey: keys.proposal(contractId) }),
  });
}

export function usePanelDeactivate(contractId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.post<{ activation: PanelActivation }>(`${BASE}/contracts/${contractId}/deactivation`)).data,
    onSettled: () => client.invalidateQueries({ queryKey: keys.proposal(contractId) }),
  });
}

export function usePanelAddMaterial(contractId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: { title: string; clientId: number | null; url?: string; file?: File }) => {
      const form = new FormData();
      form.set("title", input.title);
      if (input.clientId !== null) form.set("client_id", String(input.clientId));
      if (input.url) form.set("url", input.url);
      if (input.file) form.set("file", input.file);
      return (await api.post<PanelMaterial>(`${BASE}/materials`, form)).data;
    },
    onSuccess: () => client.invalidateQueries({ queryKey: keys.proposal(contractId) }),
  });
}

export function usePanelRetireMaterial(contractId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (materialId: number) => {
      await api.delete(`${BASE}/materials/${materialId}`);
    },
    onSuccess: () => client.invalidateQueries({ queryKey: keys.proposal(contractId) }),
  });
}

export function usePanelSwitches(enabled: boolean) {
  return useQuery({
    queryKey: keys.switches,
    queryFn: async () => (await api.get<PanelSwitches>(`${BASE}/settings`)).data,
    enabled,
    retry: false,
  });
}

export function useSavePanelSwitches() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: Partial<PanelSwitches>) =>
      (await api.put<PanelSwitches>(`${BASE}/settings`, body)).data,
    onSuccess: () => client.invalidateQueries({ queryKey: ["consultant-panel"] }),
  });
}

export function useSettlementRule(clientId: number) {
  return useQuery({
    queryKey: keys.settlement(clientId),
    queryFn: async () => (await api.get<SettlementRule>(`${BASE}/clients/${clientId}/settlement`)).data,
    retry: false,
  });
}

export function useSaveSettlementRule(clientId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: { mode: SettlementMode; instructions: string }) =>
      (await api.put<SettlementRule>(`${BASE}/clients/${clientId}/settlement`, body)).data,
    onSuccess: () => client.invalidateQueries({ queryKey: keys.settlement(clientId) }),
  });
}
