// AI na zaznaczonym fragmencie CV (Edytor CV 2, PR 3).
//
// Trasa `POST /api/pipeline/stages/{id}/cv-ai/selection` zwraca PROPOZYCJĘ
// i niczego nie zapisuje w szkicu: przyjętą propozycję nakłada edytor jedną
// cofalną zmianą, utrwala ją autozapis. Klient wysyła tekst (fragment, jego
// akapit, opis roli) — nigdy HTML ani pozycji w dokumencie. Edytor bierze
// trasę przez `CvEditorAiApi`; harness `/preview/cv-editor` podaje wersję
// z pamięci, bo podgląd nie ma sieci.

import api from "@/lib/api";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";

export type CvAiAction = "shorten" | "expand" | "rephrase" | "proofread" | "translate";

export const CV_AI_ACTIONS: ReadonlyArray<{ action: CvAiAction; label: string; title: string }> = [
  { action: "shorten", label: "Skróć", title: "Propozycja: skróć" },
  { action: "expand", label: "Rozwiń z oryginału", title: "Propozycja: rozwiń z oryginału" },
  { action: "rephrase", label: "Przeredaguj", title: "Propozycja: przeredaguj" },
  { action: "proofread", label: "Popraw język", title: "Propozycja: popraw język" },
  { action: "translate", label: "Na angielski", title: "Propozycja: na angielski" },
];

/** Stanowisko w CV, w którym stoi zaznaczony fragment. */
export interface CvAiRole {
  title: string;
  employer: string;
  points: string[];
}

export interface CvAiRequest {
  action: CvAiAction;
  /** Zaznaczony tekst; pogrubienie jako `**tekst**`. */
  fragment: string;
  /** Akapit albo punkt, w którym stoi zaznaczenie. */
  block_text: string;
  block_kind: "li" | "p";
  section: string | null;
  role?: CvAiRole;
  /** „Doprecyzuj”: wskazówka do stylu, nie źródło faktów. */
  instruction?: string;
  /** „Jeszcze raz”: propozycje już pokazane. */
  previous?: string[];
}

export interface CvAiSource {
  kind: "original" | "notes";
  quote: string;
}

export type CvAiStatus = "ok" | "rejected" | "no_source" | "not_supported" | "unavailable";

export interface CvAiResponse {
  status: CvAiStatus;
  action: string;
  /** `**tekst**` = pogrubienie — edytor zamienia je na znacznik, nigdy na HTML. */
  proposed_text: string | null;
  /** Rozwinięcie oparte na cytacie, który serwer znalazł w źródle, bez słów spoza fragmentu i cytatu. */
  verified: boolean;
  sources: CvAiSource[];
  /** Nowe nazwy w tłumaczeniu i nowe słowa z wielkiej litery na początku zdania — do sprawdzenia. */
  cautions: string[];
  reason: string | null;
  problem: string | null;
  /** Zdanie dla rekrutera: powód, gdy propozycji nie ma, albo uwaga do propozycji. */
  message: string | null;
}

export interface CvEditorAiApi {
  propose: (stageId: number, body: CvAiRequest) => Promise<CvAiResponse>;
}

export const networkAiApi: CvEditorAiApi = {
  // Po drugiej stronie liczy model — sufit dla LLM, nie CRUD-owe 30 s
  // (zerwane żądanie i tak kosztuje wywołanie modelu).
  propose: (stageId, body) =>
    api
      .post<CvAiResponse>(`/api/pipeline/stages/${stageId}/cv-ai/selection`, body, {
        timeout: SLOW_ENDPOINT_TIMEOUT_MS,
      })
      .then((r) => r.data),
};
