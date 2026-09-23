/**
 * Telemetria pomocy na ekranie (`POST /api/jarvis/ui-events`, 0355): czy
 * dymki i przewodniki ktoś klika. Wysyłamy wyłącznie klucz ekranu i kod
 * (id kotwicy albo kod odmowy) — nigdy dane rekordu. Dodatek: błąd zapisu
 * jest połykany, bo nie może zepsuć niczego na ekranie.
 */

import { api } from "@/lib/api";

export type JarvisUiEvent =
  | "bubble_shown"
  | "bubble_clicked"
  | "bubble_dismissed"
  | "guide_opened"
  | "guide_task"
  | "highlight_shown"
  | "highlight_missing"
  | "stuck_shown"
  | "stuck_clicked";

const SAFE = /^[A-Za-z0-9_.:-]{1,60}$/;

export function trackJarvisUi(event: JarvisUiEvent, screenKey?: string | null, detail?: string | null): void {
  const body: Record<string, string> = { event };
  if (screenKey && /^[a-z0-9_.]{1,60}$/.test(screenKey)) body.screen_key = screenKey;
  if (detail && SAFE.test(detail)) body.detail = detail;
  void api.post("/api/jarvis/ui-events", body).catch(() => {
    /* telemetria jest dodatkiem */
  });
}
