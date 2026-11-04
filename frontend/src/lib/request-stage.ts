/**
 * Stan requestu w JEDNYM rzędzie pigułek listy `/jobs` (25.09.2026) — lustro
 * `job_similarity.request_stage_expr`. Serwer liczy jedną wartość na
 * rekrutację (status requestu + stan pracy), więc kilka pigułek naraz to LUB.
 *
 * Zakończone, obsadzone i zamknięte nie mają pigułki: są pod „Wszystkie”.
 */

import { STATE_HINT } from "@/lib/request-work-state";
import { REQUEST_STATUS_META } from "@/lib/request-status";

export const REQUEST_STAGES = [
  "closed",
  "filled",
  "contract",
  "champion",
  "incomplete",
  "finished",
  "client_silent",
  "to_review",
  "searching",
] as const;
export type RequestStage = (typeof REQUEST_STAGES)[number];

/** Kolejność pigułek nad listą — tak, jak request przechodzi przez pracę. */
export const REQUEST_STAGE_CHIPS: readonly RequestStage[] = [
  "incomplete",
  "to_review",
  "searching",
  "champion",
  "contract",
  "client_silent",
];

export const REQUEST_STAGE_META: Record<
  RequestStage,
  { label: string; hint: string; tone: "need" | "search" | "client" | "done" | "quiet" }
> = {
  incomplete: { ...REQUEST_STATUS_META.incomplete, tone: "need" },
  to_review: { label: "Do przejrzenia", hint: STATE_HINT.to_review, tone: "quiet" },
  searching: { label: "Szukamy", hint: STATE_HINT.searching, tone: "search" },
  champion: { ...REQUEST_STATUS_META.champion, tone: "client" },
  contract: { ...REQUEST_STATUS_META.contract, tone: "client" },
  client_silent: { label: "Klient milczy", hint: STATE_HINT.client_silent, tone: "need" },
  filled: { ...REQUEST_STATUS_META.filled, tone: "done" },
  finished: { label: "Zakończony", hint: STATE_HINT.finished, tone: "done" },
  closed: { ...REQUEST_STATUS_META.closed, tone: "done" },
};

export function requestStageOf(raw: unknown): RequestStage | null {
  return typeof raw === "string" && (REQUEST_STAGES as readonly string[]).includes(raw)
    ? (raw as RequestStage)
    : null;
}

/**
 * Stare adresy (`?rs=` status requestu, `?ws=` stan pracy) → pigułka stanu.
 * Wartości bez pigułki (obsadzona, zakończona, zamknięta) odpadają — stary
 * link nie może zawęzić listy filtrem, którego nie widać.
 */
export function initialStagesFromUrl(params: URLSearchParams): RequestStage[] {
  const out: RequestStage[] = [];
  for (const raw of [...params.getAll("stage"), ...params.getAll("rs"), ...params.getAll("ws")]) {
    const stage = requestStageOf(raw);
    if (stage && REQUEST_STAGE_CHIPS.includes(stage) && !out.includes(stage)) out.push(stage);
  }
  return out;
}
