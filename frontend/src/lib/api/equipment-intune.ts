// „Ludzie w NEXUSIE” — Sprzęt ↔ Intune (etap 4, D9).
//
// Lustro `backend/app/api/equipment_intune.py`. Rodzaje rozjazdów i decyzje
// to wartości z bazy (po polsku w ASCII); etykiety w `components/equipment/IntuneTab.tsx`.
// Klucze zaczynają się od "equipment" — zmiana w rejestrze (wydanie, zwrot,
// edycja S/N) odświeża też rozjazdy.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type {
  EquipmentCategory,
  EquipmentHolderKind,
  EquipmentItemStatus,
} from "@/lib/api/equipment";

export type IntuneMode = "off" | "simulate" | "live";
export type IntuneHealth = "disabled" | "healthy" | "degraded";
export type IntuneDiscrepancyKind =
  | "zniknal_z_intune"
  | "brak_w_ewidencji"
  | "inny_posiadacz"
  | "brak_w_intune";
export type IntuneResolution = "wyjasnione" | "pominiete";

export interface IntuneStatus {
  mode: IntuneMode;
  health: IntuneHealth;
  last_run_at: string | null;
  last_success_at: string | null;
  device_count: number;
  /** Zdanie dla recepcji (bez treści odpowiedzi Microsoftu). */
  error: string | null;
  error_code: string | null;
}

export interface IntuneDevice {
  id: number;
  device_name: string | null;
  serial_number: string | null;
  manufacturer: string | null;
  model: string | null;
  operating_system: string | null;
  user_principal_name: string | null;
  user: { id: number; name: string } | null;
  compliance_state: string | null;
  last_sync_at: string | null;
  last_seen_at: string | null;
  missing_since: string | null;
  item_id: number | null;
  resolution: IntuneResolution | null;
  resolution_note: string | null;
  resolved_at: string | null;
}

export interface IntuneItemRef {
  id: number;
  inventory_number: string | null;
  serial_number: string | null;
  model_name: string;
  category: EquipmentCategory;
  status: EquipmentItemStatus;
}

export interface IntuneHolderRef {
  kind: EquipmentHolderKind | "academy";
  id: number;
  name: string;
}

export interface IntuneDiscrepancy {
  key: string;
  kind: IntuneDiscrepancyKind;
  device: IntuneDevice | null;
  item: IntuneItemRef | null;
  holder: IntuneHolderRef | null;
}

export type IntuneCounts = Record<IntuneDiscrepancyKind | "zgodne" | "wyjasnione", number>;

export interface IntuneDiscrepancies {
  rows: IntuneDiscrepancy[];
  counts: IntuneCounts;
  /** Był choć jeden udany odczyt — dopiero wtedy liczymy „brak w Intune”. */
  checked: boolean;
  /** Urządzenia widziane w ostatnim odczycie. */
  devices: number;
}

export interface IntuneSyncResult {
  status: "ok" | "error";
  devices?: number;
  error?: string;
  error_text: string | null;
}

const BASE = "/api/equipment/intune";

export const intuneKeys = {
  all: ["equipment", "intune"] as const,
  status: ["equipment", "intune", "status"] as const,
  discrepancies: ["equipment", "intune", "discrepancies"] as const,
};

export function useIntuneStatus(enabled = true) {
  return useQuery({
    queryKey: intuneKeys.status,
    queryFn: async () => (await api.get<IntuneStatus>(`${BASE}/status`)).data,
    enabled,
  });
}

export function useIntuneDiscrepancies(enabled = true) {
  return useQuery({
    queryKey: intuneKeys.discrepancies,
    queryFn: async () => (await api.get<IntuneDiscrepancies>(`${BASE}/discrepancies`)).data,
    enabled,
  });
}

function useInvalidateIntune() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: intuneKeys.all });
  };
}

export function useResolveIntuneDevice() {
  const invalidate = useInvalidateIntune();
  return useMutation({
    mutationFn: async (payload: {
      deviceId: number;
      resolution: IntuneResolution;
      note: string | null;
    }) =>
      (
        await api.post<IntuneDevice>(`${BASE}/devices/${payload.deviceId}/resolve`, {
          resolution: payload.resolution,
          note: payload.note,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useLinkIntuneDevice() {
  const invalidate = useInvalidateIntune();
  return useMutation({
    mutationFn: async (payload: { deviceId: number; itemId: number }) =>
      (
        await api.post<IntuneDevice>(`${BASE}/devices/${payload.deviceId}/link`, {
          item_id: payload.itemId,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useIntuneSync() {
  const invalidate = useInvalidateIntune();
  return useMutation({
    mutationFn: async () => (await api.post<IntuneSyncResult>(`${BASE}/sync`)).data,
    onSuccess: invalidate,
  });
}
