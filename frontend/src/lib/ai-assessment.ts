/**
 * „Oceń z AI” na zaznaczonych osobach (28.10.2026, makieta C:
 * https://claude.ai/artifact/TBHtexa3vvyK76HW2vkSMS). Serwer:
 * `backend/app/api/candidate_ai_assessments.py`.
 *
 * Zaznaczenie idzie paczkami po `AI_ASSESSMENT_CHUNK` osób z jednym
 * `batch_id` — żadne żądanie nie czeka dłużej niż jedna runda modelu, a panel
 * pokazuje postęp. Kolejność dzwonienia liczy `callOrder` tak samo jak
 * `call_order_key` na serwerze.
 */

import { api } from "@/lib/api";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";

export type AiVerdict = "call" | "maybe" | "no_fit";

export interface AiAssessmentReason {
  text: string;
  quote: string;
  source: "cv" | "note" | "profile";
}

export interface AiAssessmentRow {
  candidate_id: number;
  full_name: string;
  selection_index: number;
  verdict: AiVerdict | null;
  strength: number | null;
  must_found: number;
  must_total: number;
  reasons: AiAssessmentReason[];
  /**
   * Dlaczego AI nie oceniło: brak CV, awaria modelu albo (tylko w panelu)
   * dzienny limit, który zatrzymał resztę paczek.
   */
  error_kind: "no_cv" | "model" | "limit" | null;
  reused: boolean;
}

export interface AiAssessmentBatch {
  batch_id: string | null;
  created_at: string | null;
  rows: AiAssessmentRow[];
  daily_limit: number;
  remaining_today: number;
}

/** Najwięcej osób w jednej ocenie — jak `MAX_BATCH` na serwerze. */
export const AI_ASSESSMENT_MAX = 30;
/** Osoby w jednym żądaniu — jak `MAX_PER_REQUEST` na serwerze. */
export const AI_ASSESSMENT_CHUNK = 6;
/** Ile paczek leci naraz. */
export const AI_ASSESSMENT_PARALLEL = 2;

export const VERDICT_LABEL: Record<AiVerdict, string> = {
  call: "Dzwoń",
  maybe: "Może",
  no_fit: "Nie pasuje",
};

const VERDICT_ORDER: Record<AiVerdict, number> = { call: 0, maybe: 1, no_fit: 2 };
const UNASSESSED_ORDER = 3;

export const SOURCE_LABEL: Record<AiAssessmentReason["source"], string> = {
  cv: "CV",
  note: "Notatka",
  profile: "Profil",
};

export function notAssessedLabel(row: AiAssessmentRow): string {
  if (row.error_kind === "no_cv") return "AI nie oceniło — brak CV w NEXUSIE";
  if (row.error_kind === "limit") return "AI nie oceniło — dzienny limit oceny wyczerpany";
  return "AI nie oceniło — spróbuj ponownie później";
}

/** Kolejność dzwonienia: werdykt, siła, must-have, miejsce w zaznaczeniu. */
export function callOrder(rows: readonly AiAssessmentRow[]): AiAssessmentRow[] {
  const key = (r: AiAssessmentRow) => [
    r.verdict ? VERDICT_ORDER[r.verdict] : UNASSESSED_ORDER,
    -(r.strength ?? 0),
    -(r.must_total ? r.must_found / r.must_total : 0),
    r.selection_index,
  ];
  return [...rows].sort((a, b) => {
    const ka = key(a);
    const kb = key(b);
    for (let i = 0; i < ka.length; i += 1) {
      if (ka[i] !== kb[i]) return ka[i] - kb[i];
    }
    return 0;
  });
}

export function verdictCounts(rows: readonly AiAssessmentRow[]) {
  const counts = { call: 0, maybe: 0, no_fit: 0, none: 0 };
  for (const row of rows) counts[row.verdict ?? "none"] += 1;
  return counts;
}

/** Wynik z paczek, które wróciły — ostatnia odpowiedź o osobie wygrywa. */
export function mergeRows(
  previous: readonly AiAssessmentRow[],
  incoming: readonly AiAssessmentRow[],
): AiAssessmentRow[] {
  const byId = new Map(previous.map((r) => [r.candidate_id, r]));
  for (const row of incoming) byId.set(row.candidate_id, row);
  return callOrder([...byId.values()]);
}

export function newBatchId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // jsdom bez `randomUUID` — format UUID v4 wystarcza serwerowi.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = Math.floor(Math.random() * 16);
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export const aiAssessmentApi = {
  assess: (
    jobId: number,
    body: { batch_id: string; candidate_ids: number[]; first_index: number; refresh?: boolean },
  ): Promise<AiAssessmentBatch> =>
    // Paczka to jedna runda modelu (do 45 s na serwerze, z zapasem) — domyślne
    // 30 s zrywało żądanie, a serwer i tak zapisywał wynik i liczył limit.
    api
      .post<AiAssessmentBatch>(`/api/jobs/${jobId}/ai-assessments`, body, {
        timeout: SLOW_ENDPOINT_TIMEOUT_MS,
      })
      .then((r) => r.data),
  latest: (jobId: number): Promise<AiAssessmentBatch> =>
    api.get<AiAssessmentBatch>(`/api/jobs/${jobId}/ai-assessments/latest`).then((r) => r.data),
};
