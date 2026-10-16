/**
 * Polecenie własnymi słowami dla całego CV (Edytor CV 2, PR 4).
 *
 * Trasa `POST /api/pipeline/stages/{id}/cv-ai/command` zwraca PLAN: operacje na
 * numerach wierszy, które przeszły kontrolę serwera. Niczego nie zapisuje —
 * wybrane operacje nakłada edytor, a utrwala je zwykły autozapis. Edytor wysyła
 * TEKST wierszy (pogrubienie jako `**x**`), nigdy HTML ani pozycji.
 *
 * Edytor CV 3, PR 4 (asystent w kolumnie): żądanie niesie kilka ostatnich
 * wiadomości rozmowy i wiersze zaznaczone w edytorze; operacja z faktem spoza
 * CV i źródeł wraca z `ask: "source"`, a „Tak, dopisz” zapisuje go notatką
 * pary (`…/cv-ai/confirm-fact`), zanim edytor nałoży zmianę.
 */

import api from "@/lib/api";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";

export type CvLineKind = "title" | "heading" | "role" | "employer" | "label" | "technologies" | "bullet" | "text";

export interface CvCommandLine {
  id: number;
  kind: CvLineKind;
  text: string;
  section?: string;
  role?: number;
}

export type CvCommandPreset =
  | "shorten"
  | "drop_old_roles"
  | "order_by_requirements"
  | "unify_sentences"
  | "more_requirements"
  | "proofread";

/** Gotowe polecenia — treść trzyma serwer, tu są nazwy dla rekrutera. */
export const CV_COMMAND_PRESETS: ReadonlyArray<{ preset: CvCommandPreset; label: string }> = [
  { preset: "shorten", label: "Skróć do 2 stron" },
  { preset: "more_requirements", label: "Więcej o wymaganiach klienta" },
  { preset: "proofread", label: "Popraw język i styl" },
  { preset: "drop_old_roles", label: "Usuń najstarsze role" },
];

/** Wiadomość rozmowy z asystentem wysyłana jako kontekst (najwyżej 6). */
export interface CvCommandMessage {
  role: "user" | "assistant";
  text: string;
}

export const CV_COMMAND_HISTORY_MAX = 6;
export const CV_COMMAND_HISTORY_TEXT_MAX = 500;
export const CV_COMMAND_FOCUS_MAX = 60;

export interface CvCommandRequest {
  preset?: CvCommandPreset;
  command?: string;
  lines: CvCommandLine[];
  history?: CvCommandMessage[];
  /** Numery wierszy zaznaczonych w edytorze. */
  focus?: number[];
}

export type CvPlanOperationType =
  | "remove"
  | "replace"
  | "merge"
  | "reorder"
  | "remove_role"
  | "remove_section"
  | "add"
  | "bold"
  | "unbold"
  | "considered_for"
  | "reorder_roles";

export interface CvPlanOperation {
  id: number;
  type: CvPlanOperationType;
  /**
   * Wiersze operacji; dla `reorder` w nowej kolejności, dla `merge` pierwszy
   * dostaje tekst, dla `reorder_roles` — linie stanowisk w nowej kolejności.
   */
  lines: number[];
  /** Nowa treść (`replace`, `merge`); `**x**` = pogrubienie — nigdy HTML. */
  text: string | null;
  /** Zdanie asystenta: co i dlaczego. */
  why: string;
  /** Wymagania rekrutacji, które po tej operacji znikają z CV. */
  loses: string[];
  /**
   * Słowa nowej treści, których nie było w zastępowanych wierszach. Kontrola
   * serwera sprawdza liczby, daty, nazwy i wymagania — nie zwykłe słowa — więc
   * taka operacja nie jest zaznaczona z góry.
   */
  new_words: string[];
  /**
   * Pytanie przed nałożeniem: `source` — fakt spoza CV i źródeł (`problem`),
   * `loses` — znika jedyne miejsce z wymaganiem klienta.
   */
  ask?: "source" | "loses" | null;
  problem?: string | null;
  /** `bold` / `unbold`: terminy, które stoją w CV. */
  terms?: string[];
}

export interface CvPlanDropped {
  type: string | null;
  reason: string;
  problem: string | null;
}

export interface CvCommandResponse {
  status: "ok" | "empty" | "unavailable";
  operations: CvPlanOperation[];
  /** Propozycje asystenta, które odrzuciła kontrola serwera. */
  dropped: CvPlanDropped[];
  message: string | null;
  /** Model zaproponował więcej zmian, niż asystent robi naraz — reszta nie weszła. */
  truncated?: boolean;
}

export interface CvEditorCommandApi {
  plan: (stageId: number, body: CvCommandRequest) => Promise<CvCommandResponse>;
  /** „Tak, dopisz”: fakt z rozmowy z kandydatem jako notatka pary (autor, data). */
  confirmFact: (stageId: number, body: { term: string; text: string }) => Promise<void>;
}

export const networkCommandApi: CvEditorCommandApi = {
  // Serwer czeka na plan do 60 s (`cv_command_ai._call_model`) — CRUD-owe 30 s
  // zrywało żądanie, a model i tak liczył i kosztował.
  plan: (stageId, body) =>
    api
      .post<CvCommandResponse>(`/api/pipeline/stages/${stageId}/cv-ai/command`, body, {
        timeout: SLOW_ENDPOINT_TIMEOUT_MS,
      })
      .then((response) => response.data),
  confirmFact: (stageId, body) =>
    api.post(`/api/pipeline/stages/${stageId}/cv-ai/confirm-fact`, body).then(() => undefined),
};
