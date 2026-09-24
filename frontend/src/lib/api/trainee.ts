/**
 * Praktykanci — codzienne listy telefonów (0374).
 *
 * Typy są lustrem kontraktu `docs/trainee-call-lists-contract.md`
 * (`backend/app/api/trainee.py`). Klucze react-query są eksportowane, żeby
 * harnessy `/preview/trainee*` mogły zasiać cache tymi samymi funkcjami.
 * Kwoty stawek są zawsze PLN netto B2B.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { recountToday } from "@/lib/trainee-call";

// ── Praktykant: lista na dziś ────────────────────────────────────────────────

export type TraineeListStatus =
  | "ready"
  | "not_workday"
  | "no_program"
  | "program_finished"
  /** Admin w „podglądzie jako”: lista na dziś jeszcze nie powstała, a podgląd
   *  jej nie zakłada (tylko odczyt). */
  | "preview_not_generated";

/** Wynik zamkniętej pozycji. `call` = rozmowa zapisana formularzem. */
export type TraineeOutcome = "call" | "noanswer" | "later" | "wrong" | "declined";

export type TraineeMissingCode =
  | "rate_missing"
  | "rate_stale"
  | "b2b"
  | "work_time"
  | "work_mode"
  | "below_min_consent"
  | "office_consent"
  | "availability";

export type B2bWillingness = "b2b" | "would_switch" | "employment_only";
export type RemoteMode = "remote" | "hybrid" | "onsite";
export type WorkTimePreference =
  | "full_time_only"
  | "also_part_time"
  | "part_time_only";
export type CallAvailability = "now" | "within_1m" | "within_3m" | "later";
export type OpenToOffers = "yes" | "maybe" | "no";
export type RateUnit = "hour" | "day" | "month";

export interface TraineeItemFacts {
  min_rate_hourly: number | null;
  rate_updated_at: string | null;
  b2b_willingness: B2bWillingness | null;
  accepts_below_min_rate: boolean | null;
  remote_modes: RemoteMode[];
  max_onsite_days: number | null;
  accepts_more_office_days: boolean | null;
  office_cities: string[];
  work_time_preference: WorkTimePreference | null;
  availability_status: string | null;
  availability_date: string | null;
}

export interface TraineeItemReasons {
  /** Do ilu rekrutacji z okna reguł pasuje. */
  fits: number;
  /** …z czego ile jest otwartych teraz. */
  open_fits: number;
  stack: string[];
  missing: TraineeMissingCode[];
}

export interface TraineeItem {
  id: number;
  candidate_id: number;
  position: number;
  name: string;
  role: string | null;
  company: string | null;
  city: string | null;
  phone: string | null;
  in_base_since: number | null;
  last_contact_at: string | null;
  attempts: number;
  /** Pierwsza próba bez odpowiedzi: wraca na listę po tej chwili. */
  retry_after: string | null;
  outcome: TraineeOutcome | null;
  closed_at: string | null;
  later_date: string | null;
  reasons: TraineeItemReasons;
  facts: TraineeItemFacts;
}

export interface TraineeProgramDay {
  day: number;
  total_days: number;
  status: string;
}

export interface TraineeCounts {
  total: number;
  closed: number;
  open: number;
  call: number;
  noanswer: number;
  later: number;
  wrong: number;
  declined: number;
}

export interface TraineeToday {
  list_date: string;
  status: TraineeListStatus;
  program: TraineeProgramDay | null;
  counts: TraineeCounts;
  day_completed: boolean;
  answered_pct: number | null;
  team_answered_pct: number | null;
  items: TraineeItem[];
}

export interface TraineeCallBody {
  b2b_willingness: B2bWillingness;
  min_rate: { value: number; unit: RateUnit } | null;
  accepts_below_min_rate: boolean | null;
  remote_modes: RemoteMode[];
  max_onsite_days: number | null;
  accepts_more_office_days: boolean | null;
  office_cities: string[];
  work_time_preference: WorkTimePreference | null;
  availability: CallAvailability | null;
  open_to_offers: OpenToOffers | null;
  wants: string | null;
}

export type TraineeNoCallOutcome = Exclude<TraineeOutcome, "call">;

export interface TraineeOutcomeBody {
  outcome: TraineeNoCallOutcome;
  /** Tylko przy `later` — polski dzień roboczy po dziś. */
  later_date?: string;
}

export interface TraineeItemResponse {
  item: TraineeItem;
  day_completed: boolean;
}

export interface TraineeOpenJob {
  job_id: number;
  title: string;
  recruiter_name: string | null;
  matched_skills: string[];
}

export interface TraineeHandoverBody {
  job_id: number;
  note: string;
}

// ── Head of Recruitment / admin ──────────────────────────────────────────────

export interface TraineeProgram {
  start_date: string;
  workdays: number;
  extended_days: number;
  daily_list_size: number;
  status: string;
  day: number;
  total_days: number;
  end_date: string | null;
  decision_due: boolean;
}

export interface TraineeOverviewRow {
  user_id: number;
  name: string;
  is_active: boolean;
  program: TraineeProgram | null;
  days_with_list: number;
  days_completed: number;
  calls_per_day: number | null;
  answered_pct: number | null;
  complete_profiles_pct: number | null;
  handed_over: number;
  handed_in_process: number;
  quality: { checked: number; issues: number };
  flag_low_answer: boolean;
}

export interface TraineePoolCategory {
  name: string;
  count: number;
}

export interface TraineePool {
  size: number;
  open_fit: number;
  by_category: TraineePoolCategory[];
  computed_at?: string | null;
}

export interface TraineeOverview {
  trainees: TraineeOverviewRow[];
  team_answered_pct: number | null;
  /** `null`, dopóki pula nie była jeszcze policzona (pierwszy bieg po wdrożeniu). */
  pool: TraineePool | null;
  month: { verified_rates: number; handed_over: number; in_process: number };
}

export interface TraineeProgramUpdate {
  start_date?: string;
  workdays?: number;
  daily_list_size?: number;
}

export type TraineeDecisionBody =
  | { action: "promote"; role: "sourcer" | "recruiter"; add_to_my_people: boolean }
  | { action: "extend"; extend_days: number }
  | { action: "end" };

export type QualityVerdict = "ok" | "issue";

export interface TraineeQualitySampleItem {
  item_id: number;
  candidate_id: number;
  name: string;
  phone: string | null;
  called_at: string | null;
  facts: Partial<TraineeItemFacts>;
  verdict: QualityVerdict | null;
  note: string | null;
}

export interface TraineeRules {
  min_fits: number;
  window_months: number;
  rate_stale_months: number;
  verified_recently_days: number;
  process_active_days: number;
  my_people_contact_days: number;
  trainee_recall_days: number;
  missing_rate: boolean;
  missing_availability: boolean;
  missing_work_mode: boolean;
  missing_consents: boolean;
  missing_b2b: boolean;
  missing_work_time: boolean;
}

export type TraineeRulesPreview = TraineePool;

// ── Klucze ───────────────────────────────────────────────────────────────────

export const traineeKeys = {
  all: ["trainee"] as const,
  today: () => ["trainee", "today"] as const,
  openJobs: (itemId: number) => ["trainee", "open-jobs", itemId] as const,
  overview: () => ["trainee", "overview"] as const,
  qualitySample: (userId: number) => ["trainee", "quality-sample", userId] as const,
  rules: () => ["trainee", "rules"] as const,
  rulesPreview: (rules: TraineeRules | null) =>
    ["trainee", "rules-preview", rules] as const,
};

// ── Wywołania ────────────────────────────────────────────────────────────────

export const traineeApi = {
  async today() {
    const { data } = await api.get<TraineeToday>("/api/trainee/today");
    return data;
  },
  async saveCall(itemId: number, body: TraineeCallBody) {
    const { data } = await api.post<TraineeItemResponse>(
      `/api/trainee/items/${itemId}/call`,
      body,
    );
    return data;
  },
  async saveOutcome(itemId: number, body: TraineeOutcomeBody) {
    const { data } = await api.post<TraineeItemResponse>(
      `/api/trainee/items/${itemId}/outcome`,
      body,
    );
    return data;
  },
  async openJobs(itemId: number) {
    const { data } = await api.get<TraineeOpenJob[]>(
      `/api/trainee/items/${itemId}/open-jobs`,
    );
    return data;
  },
  async handover(itemId: number, body: TraineeHandoverBody) {
    const { data } = await api.post<{ ok: boolean }>(
      `/api/trainee/items/${itemId}/handover`,
      body,
    );
    return data;
  },
  async overview() {
    const { data } = await api.get<TraineeOverview>("/api/trainee/overview");
    return data;
  },
  async updateProgram(userId: number, body: TraineeProgramUpdate) {
    const { data } = await api.put(`/api/trainee/programs/${userId}`, body);
    return data;
  },
  async decision(userId: number, body: TraineeDecisionBody) {
    const { data } = await api.post(`/api/trainee/programs/${userId}/decision`, body);
    return data;
  },
  async qualitySample(userId: number) {
    const { data } = await api.get<TraineeQualitySampleItem[]>(
      "/api/trainee/quality-sample",
      { params: { user_id: userId } },
    );
    return data;
  },
  async qualityVerdict(itemId: number, body: { verdict: QualityVerdict; note: string }) {
    const { data } = await api.post(`/api/trainee/quality-sample/${itemId}`, body);
    return data;
  },
  async rules() {
    const { data } = await api.get<TraineeRules>("/api/trainee/rules");
    return data;
  },
  async saveRules(body: TraineeRules) {
    const { data } = await api.put<TraineeRules>("/api/trainee/rules", body);
    return data;
  },
  /**
   * Podgląd puli. Bieżący (niezapisany) stan formularza idzie w parametrach,
   * żeby podgląd był „na żywo”; bez nich backend liczy zapisane reguły.
   */
  async rulesPreview(rules: TraineeRules | null) {
    const { data } = await api.get<TraineeRulesPreview>("/api/trainee/rules/preview", {
      params: rules ?? undefined,
    });
    return data;
  },
};

// ── Hooki ────────────────────────────────────────────────────────────────────

export function useTraineeToday(enabled = true) {
  return useQuery({
    queryKey: traineeKeys.today(),
    queryFn: () => traineeApi.today(),
    enabled,
    // Lista zmienia się tylko przez zapisy praktykanta; nocą powstaje nowa.
    staleTime: 60_000,
  });
}

/**
 * Po zapisie pozycji: podmiana wiersza w cache (lista od razu przeskakuje na
 * następną osobę), przeliczenie liczników lokalnie i odświeżenie z serwera.
 */
function useApplyItemResponse() {
  const queryClient = useQueryClient();
  return (response: TraineeItemResponse) => {
    queryClient.setQueryData<TraineeToday>(traineeKeys.today(), (prev) => {
      if (!prev) return prev;
      const items = prev.items.map((item) =>
        item.id === response.item.id ? response.item : item,
      );
      return recountToday({ ...prev, items, day_completed: response.day_completed });
    });
    void queryClient.invalidateQueries({ queryKey: traineeKeys.today() });
  };
}

export function useSaveTraineeCall() {
  const apply = useApplyItemResponse();
  return useMutation({
    mutationFn: ({ itemId, body }: { itemId: number; body: TraineeCallBody }) =>
      traineeApi.saveCall(itemId, body),
    onSuccess: apply,
  });
}

export function useSaveTraineeOutcome() {
  const apply = useApplyItemResponse();
  return useMutation({
    mutationFn: ({ itemId, body }: { itemId: number; body: TraineeOutcomeBody }) =>
      traineeApi.saveOutcome(itemId, body),
    onSuccess: apply,
  });
}

export function useTraineeOpenJobs(itemId: number | null) {
  return useQuery({
    queryKey: traineeKeys.openJobs(itemId ?? 0),
    queryFn: () => traineeApi.openJobs(itemId as number),
    enabled: itemId != null,
  });
}

export function useTraineeHandover() {
  return useMutation({
    mutationFn: ({ itemId, body }: { itemId: number; body: TraineeHandoverBody }) =>
      traineeApi.handover(itemId, body),
  });
}

export function useTraineeOverview() {
  return useQuery({
    queryKey: traineeKeys.overview(),
    queryFn: () => traineeApi.overview(),
  });
}

export function useUpdateTraineeProgram() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, body }: { userId: number; body: TraineeProgramUpdate }) =>
      traineeApi.updateProgram(userId, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: traineeKeys.overview() }),
  });
}

export function useTraineeDecision() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, body }: { userId: number; body: TraineeDecisionBody }) =>
      traineeApi.decision(userId, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: traineeKeys.overview() }),
  });
}

export function useTraineeQualitySample(userId: number | null) {
  return useQuery({
    queryKey: traineeKeys.qualitySample(userId ?? 0),
    queryFn: () => traineeApi.qualitySample(userId as number),
    enabled: userId != null,
  });
}

export function useTraineeQualityVerdict(userId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      itemId,
      body,
    }: {
      itemId: number;
      body: { verdict: QualityVerdict; note: string };
    }) => traineeApi.qualityVerdict(itemId, body),
    onSuccess: (_data, { itemId, body }) => {
      queryClient.setQueryData<TraineeQualitySampleItem[]>(
        traineeKeys.qualitySample(userId),
        (prev) =>
          prev?.map((row) =>
            row.item_id === itemId ? { ...row, verdict: body.verdict, note: body.note } : row,
          ),
      );
      void queryClient.invalidateQueries({ queryKey: traineeKeys.overview() });
    },
  });
}

export function useTraineeRules() {
  return useQuery({ queryKey: traineeKeys.rules(), queryFn: () => traineeApi.rules() });
}

export function useSaveTraineeRules() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TraineeRules) => traineeApi.saveRules(body),
    onSuccess: (saved) => {
      queryClient.setQueryData(traineeKeys.rules(), saved);
      void queryClient.invalidateQueries({ queryKey: ["trainee", "rules-preview"] });
      void queryClient.invalidateQueries({ queryKey: traineeKeys.overview() });
    },
  });
}

export function useTraineeRulesPreview(rules: TraineeRules | null) {
  return useQuery({
    queryKey: traineeKeys.rulesPreview(rules),
    queryFn: () => traineeApi.rulesPreview(rules),
    enabled: rules != null,
    placeholderData: (previous) => previous,
  });
}
