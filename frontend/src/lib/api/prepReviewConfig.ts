// Ustawienia → Ocena prepów (0505, 22.10.2026).
//
// Typy są lustrem `GET/PUT /api/prep-review-config`
// (`backend/app/api/prep_review_config.py`, walidacja w
// `services/prep_review_config.py`). Odczyt: rekruter, Delivery Lead, HoR,
// admin; publikacja: HoR i admin (`can_edit`).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import api from "@/lib/api";

export type Prep1Criterion = "topics" | "must_answers" | "client_questions" | "talk_share";
export type Prep2Criterion = "prep1_followup" | "topics" | "client_questions" | "talk_share";
export type AnswerGradeKey = "strong" | "general" | "weak" | "missing";

export const PREP1_CRITERIA: Prep1Criterion[] = [
  "topics",
  "must_answers",
  "client_questions",
  "talk_share",
];
export const PREP2_CRITERIA: Prep2Criterion[] = [
  "prep1_followup",
  "topics",
  "client_questions",
  "talk_share",
];
export const ANSWER_GRADES: AnswerGradeKey[] = ["strong", "general", "weak", "missing"];

export const CRITERION_LABELS: Record<Prep1Criterion | Prep2Criterion, string> = {
  topics: "Tematy prowadzącego",
  must_answers: "Odpowiedzi kandydata na must-have",
  client_questions: "Pytania tego klienta",
  talk_share: "Kandydat mówi, prowadzący słucha",
  prep1_followup: "Poprawa punktów z Prepu 1",
};

export const CRITERION_HINTS: Record<Prep1Criterion | Prep2Criterion, string> = {
  topics: "Czy prowadzący poruszył tematy z listy niżej",
  must_answers: "Każda odpowiedź według skali: mocna, ogólna, słaba, nie było",
  client_questions: "Przećwiczone pytania, które zadaje ten klient, i jak kandydat odpowiedział",
  talk_share: "Udział kandydata w rozmowie — wymaga mówców w transkrypcie Teams",
  prep1_followup: "Czy słabe i ogólne odpowiedzi z Prepu 1 stały się mocne",
};

export const GRADE_LABELS: Record<AnswerGradeKey, string> = {
  strong: "Mocna",
  general: "Ogólna",
  weak: "Słaba",
  missing: "Nie było",
};

export interface PrepTopic {
  label: string;
  required: boolean;
}

export interface PrepRules<K extends string> {
  weights: Record<K, number>;
  topics: PrepTopic[];
}

export interface AnswerGrade {
  description: string;
  points: number;
}

export interface FollowupRules {
  weak_answers: boolean;
  general_answers: boolean;
  missing_required_topics: boolean;
  unpracticed_client_questions: boolean;
  max_items: number;
}

export interface PrepReviewConfig {
  prep1: PrepRules<Prep1Criterion>;
  prep2: PrepRules<Prep2Criterion>;
  answer_scale: Record<AnswerGradeKey, AnswerGrade>;
  max_client_questions: number;
  good_threshold: number;
  weak_threshold: number;
  min_minutes_enabled: boolean;
  min_minutes: number;
  talk_share_enabled: boolean;
  talk_share_target: number;
  required_topic_caps_ok: boolean;
  weak_must_caps_ok: boolean;
  followup: FollowupRules;
  ai_hints: string;
}

export interface PrepReviewConfigHistoryEntry {
  version: number;
  created_at: string | null;
  author: string | null;
  reason: string | null;
  changes: string[];
}

export interface PrepReviewConfigState {
  config: PrepReviewConfig;
  /** `null` = obowiązują ustawienia startowe. */
  version: number | null;
  defaults: PrepReviewConfig;
  can_edit: boolean;
  history: PrepReviewConfigHistoryEntry[];
  saved?: boolean;
}

export const MAX_TOPICS = 12;

const QUERY_KEY = ["prep-review-config"] as const;

export function usePrepReviewConfig() {
  return useQuery({
    queryKey: QUERY_KEY,
    queryFn: async () =>
      (await api.get<PrepReviewConfigState>("/api/prep-review-config")).data,
  });
}

export function usePublishPrepReviewConfig() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (input: { config: PrepReviewConfig; reason?: string }) =>
      (await api.put<PrepReviewConfigState>("/api/prep-review-config", input)).data,
    onSuccess: (state) => client.setQueryData(QUERY_KEY, state),
  });
}

export function weightSum(weights: Record<string, number>): number {
  return Object.values(weights).reduce((sum, w) => sum + (Number.isFinite(w) ? w : 0), 0);
}

/**
 * Lustro walidacji serwera — ten sam komunikat przed wysłaniem, żeby
 * przycisk „Opublikuj” nie czekał na 422. Serwer i tak sprawdza całość.
 */
export function configProblems(config: PrepReviewConfig): string[] {
  const problems: string[] = [];
  for (const [name, rules] of [
    ["Prep 1", config.prep1],
    ["Prep 2", config.prep2],
  ] as const) {
    if (weightSum(rules.weights) !== 100) {
      problems.push(`${name}: wagi kryteriów muszą dawać razem 100%.`);
    }
    const labels = rules.topics.map((t) => t.label.trim().toLocaleLowerCase("pl"));
    if (labels.some((l) => l.length < 2)) {
      problems.push(`${name}: każdy temat prowadzącego musi mieć nazwę.`);
    }
    if (new Set(labels).size !== labels.length) {
      problems.push(`${name}: ten sam temat prowadzącego jest dwa razy.`);
    }
  }
  const points = ANSWER_GRADES.map((g) => config.answer_scale[g].points);
  if (points.some((p, i) => i > 0 && p > points[i - 1])) {
    problems.push("Punkty skali nie mogą rosnąć: mocna ≥ ogólna ≥ słaba ≥ nie było.");
  }
  if (config.weak_threshold >= config.good_threshold) {
    problems.push("Próg „słaby” musi być niższy niż próg „dobry”.");
  }
  return problems;
}

export type PreviewLevel = "good" | "ok" | "weak";

/** Wynik przykładu z wag i wyników kryteriów (0–100) — podgląd na ekranie. */
export function previewScore(
  weights: Record<string, number>,
  scores: Record<string, number>,
  config: Pick<PrepReviewConfig, "good_threshold" | "weak_threshold">,
): { total: number; level: PreviewLevel } {
  const sum = weightSum(weights);
  const total =
    sum > 0
      ? Math.round(
          Object.entries(weights).reduce((acc, [key, w]) => acc + (scores[key] ?? 0) * w, 0) / sum,
        )
      : 0;
  const level: PreviewLevel =
    total >= config.good_threshold ? "good" : total < config.weak_threshold ? "weak" : "ok";
  return { total, level };
}
