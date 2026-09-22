// Własny pulpit startowy (0337) — typy i hooki.
//
// Typy są lustrem `backend/app/services/dashboard_tiles.py` i
// `backend/app/services/custom_metrics/definition.py`. Lista `TILE_TYPES`
// jest pilnowana testem lustra po stronie backendu
// (`test_dashboard_tile_types_mirror.py`) — nowy kafelek = wpis tu, w katalogu
// (`lib/dashboard-tiles/catalog.ts`), w `TileContent.tsx` i w `TileType` na serwerze.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export const TILE_TYPES = [
  "my_tasks",
  "my_next_steps",
  "my_contact_queue",
  "my_priority_queue",
  "my_people",
  "my_kpis_today",
  "my_onboarding",
  "my_recruitments",
  "recruitment_activity",
  "recruitment_competence",
  "team_workload",
  "team_allocation",
  "contact_oversight",
  "my_clients_alerts",
  "dl_alerts",
  "calendar_today",
  "metric_number",
  "metric_chart",
  "metric_funnel",
  "note",
] as const;

export type TileType = (typeof TILE_TYPES)[number];

export type MetricSource =
  | "pipeline_moves"
  | "candidates"
  | "jobs"
  | "contracts"
  | "orders"
  | "finance";
export type MetricGroupBy =
  | "none"
  | "week"
  | "month"
  | "client"
  | "recruiter"
  | "stage"
  | "competence_category";
export type MetricAuthor = "me" | "team" | "all";
export type MetricPeriod =
  | "last_7_days"
  | "last_30_days"
  | "last_8_weeks"
  | "last_12_weeks"
  | "last_90_days"
  | "this_month"
  | "last_month"
  | "this_quarter"
  | "this_year"
  | "last_12_months";

export interface MetricFilters {
  client_ids?: number[];
  competence_category_ids?: number[];
  job_ids?: number[];
  author?: MetricAuthor;
}

export interface MetricDefinition {
  source: MetricSource;
  measure: string;
  stage?: string | null;
  filters?: MetricFilters;
  group_by?: MetricGroupBy;
  period?: MetricPeriod;
  compare_previous?: boolean;
}

export type TileChart = "bars" | "line" | "table";

export interface NoteLink {
  label: string;
  url: string;
}

export interface TileConfig {
  title?: string | null;
  metric?: MetricDefinition | null;
  chart?: TileChart | null;
  text?: string | null;
  links?: NoteLink[];
  link_to?: string | null;
}

export interface DashboardTile {
  id: string;
  type: TileType;
  x: number;
  y: number;
  w: number;
  h: number;
  config: TileConfig;
}

export interface UserDashboardResponse {
  tiles: DashboardTile[];
  version: number;
  dropped_tiles: { id: string | null; type: string | null }[];
}

export const USER_DASHBOARD_QUERY_KEY = ["user-dashboard"] as const;

export const userDashboardApi = {
  get: () =>
    api.get<UserDashboardResponse>("/api/users/me/dashboard").then((r) => r.data),
  save: (tiles: DashboardTile[], expectedVersion: number) =>
    api
      .put<UserDashboardResponse>("/api/users/me/dashboard", {
        tiles,
        expected_version: expectedVersion,
      })
      .then((r) => r.data),
};

export function useUserDashboard() {
  return useQuery({
    queryKey: USER_DASHBOARD_QUERY_KEY,
    queryFn: userDashboardApi.get,
    staleTime: 60_000,
  });
}

export function useSaveUserDashboard() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ tiles, version }: { tiles: DashboardTile[]; version: number }) =>
      userDashboardApi.save(tiles, version),
    onSuccess: (data) => {
      queryClient.setQueryData(USER_DASHBOARD_QUERY_KEY, data);
    },
  });
}

/** 409 z serwera: pulpit zmieniony w innej karcie. */
export function isDashboardVersionConflict(error: unknown): boolean {
  const e = error as {
    response?: { status?: number; data?: { detail?: { code?: string } } };
  } | null;
  return (
    e?.response?.status === 409 &&
    e.response.data?.detail?.code === "DASHBOARD_VERSION_CONFLICT"
  );
}
