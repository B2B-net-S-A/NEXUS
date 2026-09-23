/**
 * Liczy powtarzające się odmowy serwera (409/422/…) z tym samym kodem.
 * Trzecia w ciągu dwóch minut = ktoś utknął → zdarzenie dla Jarvisa, który
 * wyjaśnia sprawę po ludzku (`error-explainers.ts`). Liczniki żyją wyłącznie
 * w pamięci karty; na serwer nie idzie nic poza kodem w telemetrii.
 */

import { explainerFor } from "./error-explainers";

export const JARVIS_STUCK_EVENT = "nexus:jarvis-stuck";
export const STUCK_WINDOW_MS = 2 * 60 * 1000;
export const STUCK_THRESHOLD = 3;

export interface JarvisStuckDetail {
  code: string;
}

const hits = new Map<string, number[]>();

/** Zwraca `true`, gdy właśnie przekroczono próg (i wysłano zdarzenie). */
export function recordRefusal(code: string, now: number = Date.now()): boolean {
  if (!explainerFor(code)) return false;
  const recent = (hits.get(code) ?? []).filter((t) => now - t < STUCK_WINDOW_MS);
  recent.push(now);
  if (recent.length < STUCK_THRESHOLD) {
    hits.set(code, recent);
    return false;
  }
  hits.delete(code);
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent<JarvisStuckDetail>(JARVIS_STUCK_EVENT, { detail: { code } }));
  }
  return true;
}

/** Kod odmowy z ciała błędu: `detail.code` albo `detail.reason` (kontrakty). */
export function refusalCode(status: number | undefined, data: unknown): string | null {
  if (!status || ![403, 409, 412, 422, 423].includes(status)) return null;
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const { code, reason } = detail as { code?: unknown; reason?: unknown };
  if (typeof code === "string" && code) return code;
  if (typeof reason === "string" && reason) return reason;
  return null;
}

/** Tylko dla testów. */
export function resetRefusals(): void {
  hits.clear();
}
