import api from "@/lib/api";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";

/**
 * Tablica jednej rekrutacji — DOKŁADNIE ten sam kształt co
 * `GET /api/pipeline/kanban/{job_id}` (backendowy `KanbanView`). Dashboard
 * liczy „następną akcję" tym samym modułem co karta na tablicy, więc nie może
 * dostać uproszczonej projekcji.
 */
export interface MyNextStepsKanbanView {
  job_id: number;
  columns: KanbanColumn[];
  off_template?: unknown;
}

export interface MyNextStepsJob {
  job_id: number;
  title: string;
  client_name: string | null;
  view: MyNextStepsKanbanView;
}

export interface MyNextStepsResponse {
  jobs: MyNextStepsJob[];
  /** Backend ogranicza listę rekrutacji (25); `true` = pokazano część. */
  truncated: boolean;
}

/** Klucz odświeżany zdarzeniem `pipeline_changed` (bez własnego interwału). */
export const myNextStepsQueryKey = ["my-next-steps"] as const;

export function getMyNextSteps(
  signal?: AbortSignal,
): Promise<MyNextStepsResponse> {
  return api
    .get<MyNextStepsResponse>("/api/pipeline/my-next-steps", { signal })
    .then((response) => response.data);
}
