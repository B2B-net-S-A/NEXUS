/**
 * Odmowy bramki rekrutacji (04.10.2026, „Rekrutacja bez szkiców”).
 *
 * Serwer odmawia ze strukturalnym `detail`:
 *  • `handoff_regression` (422) — zapis tworzy NOWY brak w rekrutacji w pracy
 *    (PATCH rekrutacji, zapis Championa, hiring manager),
 *  • `job_not_ready` (422) — `POST /publish`: rekrutacja nie przechodzi bramki,
 *  • `draft_not_allowed` (422) — status „szkic” nie istnieje,
 *  • `reopen_required` (409) — zamkniętą rekrutację otwiera „Otwórz ponownie”.
 *
 * Moduł jest czysty (bez axios), tekst zawsze z `message`, nigdy surowy `detail`.
 */
import { apiErrorMessage } from "@/lib/api-error";

export type JobGateCode =
  | "handoff_regression"
  | "job_not_ready"
  | "draft_not_allowed"
  | "reopen_required";

export interface JobBlockerItem {
  code: string;
  message: string;
}

export interface JobGateRefusal {
  code: JobGateCode;
  message: string | null;
  blockers: JobBlockerItem[];
}

const GATE_CODES: ReadonlySet<string> = new Set<JobGateCode>([
  "handoff_regression",
  "job_not_ready",
  "draft_not_allowed",
  "reopen_required",
]);

/** Pozycje braków z odpowiedzi: `[{code, message}]` albo starsze `string[]`. */
export function blockerItemsFrom(value: unknown): JobBlockerItem[] {
  if (!Array.isArray(value)) return [];
  const items: JobBlockerItem[] = [];
  for (const entry of value) {
    if (typeof entry === "string" && entry.trim()) {
      items.push({ code: "", message: entry.trim() });
    } else if (entry && typeof entry === "object") {
      const { code, message } = entry as { code?: unknown; message?: unknown };
      if (typeof message === "string" && message.trim()) {
        items.push({ code: typeof code === "string" ? code : "", message: message.trim() });
      }
    }
  }
  return items;
}

/** Odmowa bramki z błędu axios albo `null`, gdy to inny błąd. */
export function jobGateRefusal(error: unknown): JobGateRefusal | null {
  const response = (error as { response?: { data?: unknown } } | null | undefined)?.response;
  const data = response?.data;
  if (!data || typeof data !== "object") return null;
  const detail: unknown = (data as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const { code, message, blockers } = detail as {
    code?: unknown;
    message?: unknown;
    blockers?: unknown;
  };
  if (typeof code !== "string" || !GATE_CODES.has(code)) return null;
  return {
    code: code as JobGateCode,
    message: typeof message === "string" && message.trim() ? message.trim() : null,
    blockers: blockerItemsFrom(blockers),
  };
}

const DEFAULT_MESSAGE: Record<JobGateCode, string> = {
  handoff_regression:
    "Tej zmiany nie da się zapisać — rekrutacja w pracy straciłaby wymaganą informację.",
  job_not_ready: "Rekrutacja nie jest gotowa do publikacji.",
  draft_not_allowed:
    "Rekrutacja nie może wrócić do szkicu. Zamknij ją albo zostaw w pracy.",
  reopen_required:
    "Zamkniętą rekrutację otwiera „Otwórz ponownie” w menu „⋯” rekrutacji.",
};

/**
 * Jedno zdanie do toasta albo pola: komunikat bramki i braki, które go
 * wywołały. Inne błędy — `apiErrorMessage`.
 */
export function jobGateErrorText(error: unknown, fallback: string): string {
  const refusal = jobGateRefusal(error);
  if (!refusal) return apiErrorMessage(error, fallback);
  const head = refusal.message ?? DEFAULT_MESSAGE[refusal.code];
  if (refusal.blockers.length === 0) return head;
  return `${head} ${refusal.blockers.map((b) => b.message).join(" ")}`;
}
