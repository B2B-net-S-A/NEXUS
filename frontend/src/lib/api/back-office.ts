// Kolejka back office'u (moduł `back_office`, decyzje Artura 02.11.2026).
//
// Lustro `backend/app/api/back_office.py`. Kwoty, tytuły spraw i akcje liczy
// serwer per czytający. Akcept na karcie woła istniejącą trasę (raporty, premie,
// zmiany w zamówieniach), a potem `refresh` przelicza karty tego rodzaju.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type BoTeamId = "care" | "finance" | "contracts" | "orders";
export type BoState = "new" | "in_progress" | "waiting" | "done";
export type BoAction = "approve" | "return" | "approve_all" | "cancel_all" | "mark_done";

export interface BoPersonRef {
  id: number;
  name: string | null;
}

export interface BoCard {
  id: number;
  team: BoTeamId;
  lane: string;
  source_kind: string;
  title: string;
  person: string | null;
  client: string | null;
  state: BoState;
  waiting_on: string | null;
  due_on: string | null;
  href: string | null;
  assignee: BoPersonRef | null;
  substituting: boolean;
  created_at: string;
  updated_at: string;
  escalated: boolean;
  priority: { user_id: number; name: string | null; until: string | null } | null;
  needs_review: boolean;
  triage_guess: { team: BoTeamId; lane: string } | null;
  case_id: number | null;
  case_source: string | null;
  actions: BoAction[];
  amounts: { total: string; currency: string }[] | null;
  count: number | null;
  steps: { done: number; total: number } | null;
  parent_title: string | null;
  meta: {
    timesheet_id?: number;
    year?: number;
    month?: number;
    item_key?: string;
    gap_id?: number;
  };
}

export interface BoStepCard {
  id: number;
  label: string;
  team: BoTeamId;
  team_label: string;
  state: BoState;
  updated_at: string;
  assignee: BoPersonRef | null;
  can_act: boolean;
}

export interface BoEvent {
  action: string;
  actor: string | null;
  at: string;
  note: string | null;
}

export interface BoBonusRow {
  id: number;
  person: string;
  category: string | null;
  amount: string;
  currency: string;
  eligible_on: string | null;
}

export interface BoCardDetail extends BoCard {
  step_cards: BoStepCard[];
  events: BoEvent[];
  bonuses?: BoBonusRow[];
}

export interface BoLane {
  id: string;
  label: string;
  description: string;
}

export interface BoTeam {
  id: BoTeamId;
  label: string;
  lanes: BoLane[];
}

export interface BoBoard {
  today: string;
  teams: BoTeam[];
  cards: BoCard[];
  triage: BoCard[];
  me: {
    user_id: number;
    name: string;
    teams: BoTeamId[];
    is_lead: boolean;
    /** Uprawnienie „Sprawy”: zakłada sprawy i odpowiada na maile w sprawie. */
    cases_handler: boolean;
    sees_amounts: boolean;
    in_progress: number;
    limit: number;
  };
  counts: {
    unassigned: number;
    overdue_unassigned: number;
    escalated: number;
    review: number;
  };
}

export interface BoTeamSetup {
  candidates: { id: number; name: string }[];
  teams: { id: BoTeamId; label: string; members: BoPersonRef[] }[];
  deputy_user_id: number | null;
}

export const boKeys = {
  all: ["back-office"] as const,
  board: ["back-office", "board"] as const,
  card: (id: number) => ["back-office", "card", id] as const,
  team: ["back-office", "team"] as const,
};

export function useBoBoard(enabled = true) {
  return useQuery({
    queryKey: boKeys.board,
    enabled,
    queryFn: async () => (await api.get<BoBoard>("/api/back-office/board")).data,
    refetchInterval: 60_000,
  });
}

export function useBoCard(id: number | null) {
  return useQuery({
    queryKey: boKeys.card(id ?? 0),
    enabled: id != null,
    queryFn: async () => (await api.get<BoCardDetail>(`/api/back-office/cards/${id}`)).data,
  });
}

export function useBoTeam(enabled = true) {
  return useQuery({
    queryKey: boKeys.team,
    enabled,
    queryFn: async () => (await api.get<BoTeamSetup>("/api/back-office/team")).data,
  });
}

function useCardCommand<V extends { id: number }>(path: string, body: (vars: V) => unknown = () => ({})) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (vars: V) =>
      (await api.post<BoCardDetail>(`/api/back-office/cards/${vars.id}/${path}`, body(vars))).data,
    onSettled: () => client.invalidateQueries({ queryKey: boKeys.all }),
  });
}

export function useTakeCard() {
  return useCardCommand<{
    id: number;
    substitute?: boolean;
    override_priority?: boolean;
    expected_updated_at?: string;
  }>("take", ({ substitute, override_priority, expected_updated_at }) => ({
    substitute: substitute ?? false,
    override_priority: override_priority ?? false,
    expected_updated_at: expected_updated_at ?? null,
  }));
}

export const useReleaseCard = () => useCardCommand<{ id: number }>("release");
export const useAssignCard = () =>
  useCardCommand<{ id: number; user_id: number }>("assign", ({ user_id }) => ({ user_id }));
export const useSetCardState = () =>
  useCardCommand<{ id: number; state: BoState; waiting_on?: string | null; expected_updated_at?: string }>(
    "state",
    ({ state, waiting_on, expected_updated_at }) => ({
      state,
      waiting_on: waiting_on ?? null,
      expected_updated_at: expected_updated_at ?? null,
    }),
  );
export const useCardNote = () =>
  useCardCommand<{ id: number; body: string }>("note", ({ body }) => ({ body }));
export const useDismissCard = () =>
  useCardCommand<{ id: number; body: string }>("dismiss", ({ body }) => ({ body }));
export const useStepDone = () => useCardCommand<{ id: number }>("step-done");
export const useMoveCard = () =>
  useCardCommand<{ id: number; team: BoTeamId; lane: string }>("move", ({ team, lane }) => ({ team, lane }));
export const useRefreshCard = () => useCardCommand<{ id: number }>("refresh");

export const useReviewCard = () =>
  useCardCommand<{
    id: number;
    decision: "current" | "close" | "move";
    team?: BoTeamId;
    lane?: string;
    note?: string;
  }>("review", ({ decision, team, lane, note }) => ({
    decision,
    team: team ?? null,
    lane: lane ?? null,
    note: note ?? null,
  }));

export function useFinishReview() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post("/api/back-office/review/finish", {})).data,
    onSettled: () => client.invalidateQueries({ queryKey: boKeys.all }),
  });
}

export function useCaseReply() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ caseId, body }: { caseId: number; body: string }) =>
      (await api.post(`/api/cases/${caseId}/reply`, { body })).data,
    onSettled: () => client.invalidateQueries({ queryKey: boKeys.all }),
  });
}

export function useBoSync() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post("/api/back-office/sync", {})).data,
    onSettled: () => client.invalidateQueries({ queryKey: boKeys.all }),
  });
}

/** Karta nowej sprawy od razu, bez czekania na pętlę. Pełny przebieg ma tylko kierownik. */
export function useBoSyncCases() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post("/api/back-office/sync/cases", {})).data,
    onSettled: () => client.invalidateQueries({ queryKey: boKeys.all }),
  });
}

export function useSaveTeam() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ team, user_ids }: { team: BoTeamId; user_ids: number[] }) =>
      (await api.put<BoTeamSetup>(`/api/back-office/team/${team}`, { user_ids })).data,
    onSettled: () => client.invalidateQueries({ queryKey: boKeys.all }),
  });
}

export function useSaveDeputy() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (user_id: number | null) =>
      (await api.put("/api/back-office/deputy", { user_id })).data,
    onSettled: () => client.invalidateQueries({ queryKey: boKeys.all }),
  });
}

export function useCancelBonuses() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ ids, note }: { ids: number[]; note?: string | null }) =>
      (
        await api.post<{ cancelled: number }>("/api/hr/payroll/bonuses/cancel-batch", {
          ids,
          note: note ?? null,
        })
      ).data,
    onSettled: () => client.invalidateQueries(),
  });
}

// ── Dodatek do rozliczenia z karty sprawy (13.11.2026) ───────────────────────

export interface BoExtraPerson {
  contract_id: number;
  person: string;
  client: string | null;
}

export interface BoCardExtra {
  id: number;
  month: string;
  kind: string;
  kind_label: string;
  /** `null` bez dostępu do kwot (wpisujący widzi swoje). */
  amount: string | null;
  description: string;
  status: "pending" | "approved" | "rejected";
  status_label: string;
  decision_note: string | null;
  reported_by: string | null;
  person: string | null;
}

export interface BoCardExtras {
  contract: BoExtraPerson | null;
  kinds: { key: string; label: string }[];
  items: BoCardExtra[];
}

export const boExtraKeys = {
  card: (id: number) => ["back-office", "card", id, "settlement-extras"] as const,
  people: (q: string) => ["back-office", "settlement-extras", "people", q] as const,
};

/** Dodatki zgłoszone z karty; 404 = moduł rozliczeń wyłączony (sekcja się chowa). */
export function useCardSettlementExtras(cardId: number, enabled: boolean) {
  return useQuery({
    queryKey: boExtraKeys.card(cardId),
    enabled,
    retry: false,
    queryFn: async () => (await api.get<BoCardExtras>(`/api/back-office/cards/${cardId}/settlement-extras`)).data,
  });
}

export function useExtraPeople(q: string) {
  const query = q.trim();
  return useQuery({
    queryKey: boExtraKeys.people(query),
    enabled: query.length >= 2,
    queryFn: async () =>
      (await api.get<BoExtraPerson[]>("/api/back-office/settlement-extras/people", { params: { q: query } })).data,
  });
}

export function useAddCardSettlementExtra(cardId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: { contract_id: number; month: string; kind: string; amount: string; description: string | null }) =>
      (await api.post<BoCardExtras>(`/api/back-office/cards/${cardId}/settlement-extras`, body)).data,
    onSettled: () => client.invalidateQueries({ queryKey: boKeys.card(cardId) }),
  });
}
