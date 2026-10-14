/**
 * Polecenie własnymi słowami dla całego CV (Edytor CV 2, PR 4).
 *
 * Trasa `POST /api/pipeline/stages/{id}/cv-ai/command` zwraca PLAN: operacje na
 * numerach wierszy, które przeszły kontrolę serwera. Niczego nie zapisuje —
 * wybrane operacje nakłada edytor, a utrwala je zwykły autozapis. Edytor wysyła
 * TEKST wierszy (pogrubienie jako `**x**`), nigdy HTML ani pozycji.
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

export type CvCommandPreset = "shorten" | "drop_old_roles" | "order_by_requirements" | "unify_sentences";

/** Gotowe polecenia — treść trzyma serwer, tu są nazwy dla rekrutera. */
export const CV_COMMAND_PRESETS: ReadonlyArray<{ preset: CvCommandPreset; label: string }> = [
  { preset: "shorten", label: "Skróć do 2 stron" },
  { preset: "drop_old_roles", label: "Usuń najstarsze role" },
  { preset: "order_by_requirements", label: "Ułóż punkty według wymagań klienta" },
  { preset: "unify_sentences", label: "Ujednolić formę zdań" },
];

export interface CvCommandRequest {
  preset?: CvCommandPreset;
  command?: string;
  lines: CvCommandLine[];
}

export type CvPlanOperationType = "remove" | "replace" | "merge" | "reorder" | "remove_role" | "remove_section";

export interface CvPlanOperation {
  id: number;
  type: CvPlanOperationType;
  /** Wiersze operacji; dla `reorder` w nowej kolejności, dla `merge` pierwszy dostaje tekst. */
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
}

export interface CvEditorCommandApi {
  plan: (stageId: number, body: CvCommandRequest) => Promise<CvCommandResponse>;
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
};
