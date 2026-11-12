// Sprzedaż → karta firmy: bot uzupełnia kartę (G-A) i odpowiada na pytania (G-B).
//
// Lustro `backend/app/api/sales_company_bot.py` i `sales_bot_results.py`.
// Z wyłączoną flagą `SALES_BOT_TASKS_ENABLED` odczyt mówi `enabled: false`
// i karta nic nie pokazuje. Bieg bota trwa kilka minut, więc w trakcie
// (`status: "started"`) zapytania odświeżają się same.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

import { salesKeys } from "./sales";

export type EnrichFieldKey =
  | "domain"
  | "website_url"
  | "nip"
  | "hq_city"
  | "industry"
  | "tier"
  | "parent_name";

/** Kolejność pól na ekranie, ta sama co w backendzie (`enrich.FIELDS`). */
export const ENRICH_FIELDS: EnrichFieldKey[] = [
  "domain",
  "website_url",
  "nip",
  "hq_city",
  "industry",
  "tier",
  "parent_name",
];

export interface EnrichField {
  value: string;
  source: string;
  published?: string | null;
  /** Tylko `tier`: przedział liczby pracowników od bota („1000+”). */
  employees?: string;
}

export type BotRunStatus = "started" | "received" | "failed" | "expired";

export interface EnrichResult {
  id: number;
  kind: "enrich";
  company: { id: number; name: string } | null;
  status: "new" | "partial" | "accepted" | "rejected";
  payload: {
    fields: Partial<Record<EnrichFieldKey, EnrichField>>;
    decisions?: Partial<Record<EnrichFieldKey, "accepted" | "rejected">>;
    checked_at?: string;
  };
  created_at: string;
  run_id: number;
}

export interface EnrichState {
  enabled: boolean;
  run: { id: number; status: BotRunStatus; started_at: string } | null;
  result: EnrichResult | null;
}

export interface AcceptOutcome {
  id: number;
  status: EnrichResult["status"];
  company_id: number;
  applied: EnrichFieldKey[];
  rejected: EnrichFieldKey[];
  notes: string[];
}

export interface AnswerLine {
  text: string;
  url?: string | null;
  published?: string | null;
}

export interface BotQuestion {
  run_id: number;
  status: BotRunStatus;
  question: string | null;
  asked_by: { id: number; name: string } | null;
  asked_at: string;
  answered_at: string | null;
  minutes: number | null;
  answer: AnswerLine[] | null;
}

export interface BotQuestions {
  enabled: boolean;
  items: BotQuestion[];
}

const POLL_MS = 20_000;

export const salesBotKeys = {
  enrich: (companyId: number) => ["sales", "company", companyId, "bot-enrich"] as const,
  questions: (companyId: number) => ["sales", "company", companyId, "bot-questions"] as const,
};

export function useCompanyEnrich(companyId: number) {
  return useQuery({
    queryKey: salesBotKeys.enrich(companyId),
    queryFn: async () =>
      (await api.get<EnrichState>(`/api/sales/companies/${companyId}/enrich`)).data,
    enabled: Number.isFinite(companyId) && companyId > 0,
    refetchInterval: (query) => (query.state.data?.run?.status === "started" ? POLL_MS : false),
  });
}

export function useStartEnrich(companyId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.post<EnrichState>(`/api/sales/companies/${companyId}/enrich`)).data,
    onSuccess: (state) => queryClient.setQueryData(salesBotKeys.enrich(companyId), state),
  });
}

/** Przyjęcie albo odrzucenie pól propozycji; zapis zmienia kartę, więc odświeżamy i ją. */
export function useDecideEnrich(companyId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { resultId: number; fields?: EnrichFieldKey[]; reject?: EnrichFieldKey[] }) =>
      (
        await api.post<AcceptOutcome>(`/api/sales/bot-results/${vars.resultId}/accept`, {
          ...(vars.fields ? { fields: vars.fields } : {}),
          reject: vars.reject ?? [],
        })
      ).data,
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: salesBotKeys.enrich(companyId) });
      void queryClient.invalidateQueries({ queryKey: salesKeys.company(companyId), exact: true });
    },
  });
}

export function useRejectEnrich(companyId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (resultId: number) =>
      (await api.post(`/api/sales/bot-results/${resultId}/reject`, {})).data,
    onSettled: () => void queryClient.invalidateQueries({ queryKey: salesBotKeys.enrich(companyId) }),
  });
}

export function useCompanyQuestions(companyId: number) {
  return useQuery({
    queryKey: salesBotKeys.questions(companyId),
    queryFn: async () =>
      (await api.get<BotQuestions>(`/api/sales/companies/${companyId}/questions`)).data,
    enabled: Number.isFinite(companyId) && companyId > 0,
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => item.status === "started") ? POLL_MS : false,
  });
}

export function useAskBot(companyId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (question: string) =>
      (await api.post<BotQuestion>(`/api/sales/companies/${companyId}/ask`, { question })).data,
    onSettled: () => void queryClient.invalidateQueries({ queryKey: salesBotKeys.questions(companyId) }),
  });
}
