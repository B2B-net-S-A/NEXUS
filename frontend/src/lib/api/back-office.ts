// Kolejka back office'u (moduł `back_office`, decyzje Artura 02.11 i 19.11.2026).
//
// Od 19.11 jeden zespół: dawne kolumny zespołów to etykiety (`labels`), sprawę
// bierze pierwsza wolna osoba („Weź następną”), a sprawa może czekać na dział
// poza back office'em („Na zewnątrz”).
//
// Lustro `backend/app/api/back_office.py`. Kwoty, tytuły spraw i akcje liczy
// serwer per czytający. Akcept na karcie woła istniejącą trasę (raporty, premie,
// zmiany w zamówieniach), a potem `refresh` przelicza karty tego rodzaju.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type BoTeamId = "care" | "finance" | "contracts" | "orders";
export type BoState = "new" | "in_progress" | "waiting" | "done";
export type BoOutsideTeam = "recruitment" | "sales" | "it" | "hr" | "accounting" | "legal";
export type BoMemberRole = "deputy" | "reception" | "accountant" | "member";

export interface BoLabel {
  id: string;
  label: string;
  family: BoTeamId;
  family_label: string;
  description: string;
}
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
  contract_id: number | null;
  /** Dział poza back office'em, na który sprawa czeka (przy stanie `waiting`). */
  outside_team: BoOutsideTeam | null;
  /** Rozmowa z portalu zarezerwowana w tej sprawie (tylko na tablicy). */
  meeting?: { start_at: string; topic: string; join_url: string | null } | null;
  meta: {
    timesheet_id?: number;
    year?: number;
    month?: number;
    item_key?: string;
    gap_id?: number;
  };
  /** Propozycja z maila: wypowiedzenie, klient kończy, zmiana daty, wycofanie (0757). */
  notice?: BoNotice | null;
}

export type BoNoticeKind = "consultant_notice" | "client_termination" | "date_change" | "withdrawal";

export interface BoNotice {
  id: number;
  kind: BoNoticeKind;
  label: string;
  last_day: string | null;
}

export interface NoticeContractView {
  id: number;
  person: string | null;
  client: string | null;
  client_id: number;
  status: string;
  contract_type: string;
  start_date: string | null;
  end_date: string | null;
  terminated_at: string | null;
  agreement_termination_mode: string | null;
  exit_case_id: number | null;
}

export interface NoticeDetail {
  id: number;
  case_id: number;
  kind: BoNoticeKind;
  label: string;
  status: "pending" | "confirmed" | "rejected" | "superseded";
  delivered_on: string | null;
  proposed_last_day: string | null;
  alternative_last_day: string | null;
  client_end_date: string | null;
  contract_number: string | null;
  cpro_number: string | null;
  agreement: boolean;
  period_source: "template" | "default" | null;
  client_reason: string | null;
  evidence: string[];
  reasons: { key: string; label: string }[];
  message: {
    id: number;
    sender_email: string | null;
    sender_name: string | null;
    subject: string | null;
    received_at: string | null;
    excerpt: string;
    attachments: string[];
  } | null;
  sender_known: boolean;
  /** Uwierzytelniony nadawca dopasowany po adresie albo nazwisku (nie po numerze z treści). */
  can_remember_sender: boolean;
  contract: NoticeContractView | null;
  alternatives: NoticeContractView[];
  order: {
    id: number;
    title: string;
    client_id: number;
    status: string;
    start_date: string | null;
    end_date: string | null;
  } | null;
  dates: { key: string; label: string; date: string | null; differs: boolean }[];
  thread: {
    id: number;
    kind: BoNoticeKind;
    label: string;
    status: string;
    received_at: string | null;
    sender_name: string | null;
    subject: string | null;
    proposed_last_day: string | null;
  }[];
  decision: Record<string, unknown> | null;
  decided_at: string | null;
}

export interface NoticeDecisionInput {
  id: number;
  decision: "confirmed" | "rejected";
  contract_id?: number | null;
  remember_sender?: boolean;
  applied?: Record<string, unknown>;
  note?: string | null;
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

export interface BoRelatedCard {
  id: number;
  lane: string;
  label: string;
  title: string;
  state: BoState;
  due_on: string | null;
  assignee: BoPersonRef | null;
}

export interface BoCardDetail extends BoCard {
  step_cards: BoStepCard[];
  events: BoEvent[];
  bonuses?: BoBonusRow[];
  /** Inne otwarte karty tego kontraktu (np. ławka przy sprawie wyjścia). */
  related: BoRelatedCard[];
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
  labels: BoLabel[];
  outside_teams: { id: BoOutsideTeam; label: string }[];
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
    outside: number;
  };
}

export interface BoTeamMemberRow {
  user_id: number;
  name: string | null;
  role: BoMemberRole;
  role_label: string;
  takes_calls: boolean;
  in_progress: number;
  open: number;
  overdue: number;
}

export interface BoTeamSetup {
  members: BoTeamMemberRow[];
  roles: { id: BoMemberRole; label: string }[];
  head: BoPersonRef | null;
  outsiders: { user_id: number; name: string | null; cards: number }[];
  outside_contacts: { id: BoOutsideTeam; label: string; contact: BoPersonRef | null }[];
  /** Pusty skład: do kolejki wchodzi każdy z uprawnieniami (tryb przejściowy). */
  from_permissions: boolean;
  candidates: { id: number; name: string }[];
}

export interface BoLabelRef {
  id: number;
  lane: string;
  label: string;
}

export interface BoConsultantRow {
  contract_id: number;
  client_id: number;
  client_name: string;
  name: string;
  job_title: string | null;
  contract_type: string | null;
  start_date: string | null;
  /** Koniec współpracy: najbliższy znany koniec umowy albo bieżącego zamówienia. */
  end_date: string | null;
  end_source: "order" | "contract" | null;
  open_cases: BoLabelRef[];
  last_conversation: { on: string; by: string | null } | null;
}

export interface BoConsultantCard {
  contract_id: number;
  client_id: number;
  client_name: string;
  name: string;
  job_title: string | null;
  contract_type: string | null;
  status: string;
  start_date: string | null;
  end_date: string | null;
  end_source: "order" | "contract" | null;
  days_to_end: number | null;
  last_conversation: { on: string; by: string | null } | null;
  open_count: number;
  cases: (BoLabelRef & {
    title: string;
    state: BoState;
    due_on: string | null;
    closed_at: string | null;
    assignee: BoPersonRef | null;
  })[];
  conversations: {
    on: string;
    by: string | null;
    channel: string;
    satisfaction: number | null;
    note: string | null;
  }[];
}

export interface BoClientRow {
  client_id: number;
  name: string;
  consultants: number;
  ending_60: number;
  open_cases: number;
  delivery_leads: string[];
  has_sheet: boolean;
}

export type BoSheetBlockId = "settlement" | "onboarding" | "orders" | "contacts";

export interface BoClientSheet {
  client_id: number;
  name: string;
  consultants: number;
  open_cases: number;
  ending_60: { contract_id: number; name: string; end_date: string }[];
  delivery_leads: string[];
  settlement_rule: { mode: string; instructions: string | null } | null;
  blocks: {
    id: BoSheetBlockId;
    label: string;
    body: string;
    updated_by: string | null;
    updated_at: string | null;
  }[];
}

export const boKeys = {
  all: ["back-office"] as const,
  board: ["back-office", "board"] as const,
  card: (id: number) => ["back-office", "card", id] as const,
  team: ["back-office", "team"] as const,
  consultants: ["back-office", "consultants"] as const,
  consultant: (id: number) => ["back-office", "consultant", id] as const,
  clients: ["back-office", "clients"] as const,
  client: (id: number) => ["back-office", "client", id] as const,
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

export function useNoticeProposal(id: number | null | undefined) {
  return useQuery({
    queryKey: [...boKeys.all, "notice", id],
    enabled: Boolean(id),
    queryFn: async () => (await api.get<NoticeDetail>(`/api/back-office/notices/${id}`)).data,
  });
}

export function useDecideNotice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: NoticeDecisionInput) =>
      (await api.post<NoticeDetail>(`/api/back-office/notices/${id}/decision`, body)).data,
    onSettled: () => client.invalidateQueries({ queryKey: boKeys.all }),
  });
}

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

function useTeamMutation<V>(request: (vars: V) => Promise<BoTeamSetup>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSuccess: (data) => client.setQueryData(boKeys.team, data),
    onSettled: () => client.invalidateQueries({ queryKey: boKeys.all }),
  });
}

export const useSaveMember = () =>
  useTeamMutation(async ({ user_id, role, takes_calls }: { user_id: number; role: BoMemberRole; takes_calls: boolean }) =>
    (await api.put<BoTeamSetup>(`/api/back-office/team/members/${user_id}`, { role, takes_calls })).data,
  );

export const useRemoveMember = () =>
  useTeamMutation(async (user_id: number) =>
    (await api.delete<BoTeamSetup>(`/api/back-office/team/members/${user_id}`)).data,
  );

export const useSaveOutsideContacts = () =>
  useTeamMutation(async (contacts: Partial<Record<BoOutsideTeam, number | null>>) =>
    (await api.put<BoTeamSetup>("/api/back-office/team/outside-contacts", { contacts })).data,
  );

export function useReleaseOutsiders() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post<{ released: number }>("/api/back-office/team/release-outsiders", {})).data,
    onSettled: () => client.invalidateQueries({ queryKey: boKeys.all }),
  });
}

/** „Na zewnątrz”: sprawa czeka na dział poza back office'em. */
export const useSendOutside = () =>
  useCardCommand<{ id: number; team: BoOutsideTeam; note: string; expected_updated_at?: string }>(
    "outside",
    ({ team, note, expected_updated_at }) => ({ team, note, expected_updated_at: expected_updated_at ?? null }),
  );

/** „Weź następną”: kolejność liczy serwer (najstarszy termin, potem najdłużej bez osoby). */
export function useTakeNext() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post<BoCardDetail>("/api/back-office/next", {})).data,
    onSettled: () => client.invalidateQueries({ queryKey: boKeys.all }),
  });
}

export function useBulkReview() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: { card_ids: number[]; decision: "current" | "close"; note?: string }) =>
      (await api.post<{ done: number; skipped: number }>("/api/back-office/review/bulk", body)).data,
    onSettled: () => client.invalidateQueries({ queryKey: boKeys.all }),
  });
}

export function useBoConsultants(enabled = true) {
  return useQuery({
    queryKey: boKeys.consultants,
    enabled,
    queryFn: async () => (await api.get<{ items: BoConsultantRow[] }>("/api/back-office/consultants")).data,
    staleTime: 60_000,
  });
}

export function useBoConsultant(contractId: number | null) {
  return useQuery({
    queryKey: boKeys.consultant(contractId ?? 0),
    enabled: contractId != null,
    queryFn: async () => (await api.get<BoConsultantCard>(`/api/back-office/consultants/${contractId}`)).data,
  });
}

export function useBoClients(enabled = true) {
  return useQuery({
    queryKey: boKeys.clients,
    enabled,
    queryFn: async () => (await api.get<{ items: BoClientRow[] }>("/api/back-office/clients")).data,
    staleTime: 60_000,
  });
}

export function useBoClientSheet(clientId: number | null) {
  return useQuery({
    queryKey: boKeys.client(clientId ?? 0),
    enabled: clientId != null,
    queryFn: async () => (await api.get<BoClientSheet>(`/api/back-office/clients/${clientId}`)).data,
  });
}

export function useSaveClientNote(clientId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ block, body }: { block: BoSheetBlockId; body: string }) =>
      (await api.put<BoClientSheet>(`/api/back-office/clients/${clientId}/notes/${block}`, { body })).data,
    onSuccess: (data) => client.setQueryData(boKeys.client(clientId), data),
    onSettled: () => client.invalidateQueries({ queryKey: boKeys.clients }),
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
