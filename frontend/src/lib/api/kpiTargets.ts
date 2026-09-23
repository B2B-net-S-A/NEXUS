// Ustawienia → Rekrutacja → Cele KPI (plan PR3, 23.09.2026).
//
// Lustro `backend/app/services/kpi_target_editor.py` (`build_matrix`,
// `history`). Reguły zapisu (kanoniczne id, wartość z katalogu = usunięcie
// odstępstwa roli) liczy serwer — front wysyła liczbę albo `null` („przywróć").

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type KpiTargetRole = "recruiter" | "sourcer" | "tac";

export interface KpiTargetKpi {
  kpi_id: string;
  title: string;
  description: string;
  period: "day" | "week" | "month";
  period_label: string;
  /** Cel jest progiem Wyścigu Rekomendacji (nagroda 1 500 zł). */
  race_threshold: boolean;
}

export interface KpiRoleCell {
  catalog_default: number;
  /** Odstępstwo roli od katalogu; `null` = obowiązuje katalog. */
  override: number | null;
  effective: number;
}

export interface KpiUserCell {
  effective: number;
  /** Osobisty cel; `null` = cel z ról osoby (maksimum). */
  override: number | null;
  source: "user" | "role";
}

export interface KpiTargetsMatrix {
  kpis: KpiTargetKpi[];
  roles: {
    role: KpiTargetRole;
    label: string;
    targets: Record<string, KpiRoleCell>;
  }[];
  users: {
    user_id: number;
    name: string;
    roles: KpiTargetRole[];
    targets: Record<string, KpiUserCell>;
  }[];
}

export interface KpiTargetEvent {
  id: number;
  scope: "role" | "user";
  role: string | null;
  role_label: string | null;
  subject_user_id: number | null;
  subject_name: string | null;
  kpi_id: string;
  kpi_title: string;
  action: "set" | "reset";
  from_value: number | null;
  to_value: number | null;
  actor_name: string | null;
  created_at: string | null;
}

export function useKpiTargets() {
  return useQuery({
    queryKey: ["kpi-targets"],
    queryFn: async () => (await api.get<KpiTargetsMatrix>("/api/kpi-targets")).data,
  });
}

export function useKpiTargetHistory() {
  return useQuery({
    queryKey: ["kpi-targets", "history"],
    queryFn: async () =>
      (await api.get<{ items: KpiTargetEvent[] }>("/api/kpi-targets/history"))
        .data.items,
  });
}

function useSaveTarget<T>(path: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: T) =>
      (await api.put<KpiTargetsMatrix>(`/api/kpi-targets/${path}`, body)).data,
    onSuccess: (matrix) => {
      queryClient.setQueryData(["kpi-targets"], matrix);
      void queryClient.invalidateQueries({ queryKey: ["kpi-targets", "history"] });
      // Cele czyta panel „Moje KPI", widget i wyścig — niech pobiorą je od nowa.
      void queryClient.invalidateQueries({ queryKey: ["kpis"] });
    },
  });
}

export function useSaveRoleDefault() {
  return useSaveTarget<{
    role: KpiTargetRole;
    kpi_id: string;
    target_value: number | null;
  }>("role-default");
}

export function useSaveUserTarget() {
  return useSaveTarget<{
    user_id: number;
    kpi_id: string;
    target_value: number | null;
  }>("user-target");
}

/** Pole liczby → wartość do zapisu. Pusty tekst = „przywróć" (`null`). */
export function parseTargetInput(raw: string): number | null | "invalid" {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  if (!/^\d+$/.test(trimmed)) return "invalid";
  const value = Number(trimmed);
  return value > 100_000 ? "invalid" : value;
}

/** Zdanie historii po polsku: „Rekruter · Weryfikacje dziś: 4 → 5". */
export function describeKpiEvent(event: KpiTargetEvent): string {
  const who =
    event.scope === "role"
      ? `rola ${event.role_label ?? event.role ?? "—"}`
      : (event.subject_name ?? "osoba usunięta");
  const from =
    event.from_value ?? (event.scope === "role" ? "katalog" : "cel z ról");
  const to =
    event.to_value ??
    (event.scope === "role" ? "katalog" : "cel z ról");
  return `${who} · ${event.kpi_title}: ${from} → ${to}`;
}
