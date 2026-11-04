/**
 * Historia wersji CV etapu i powrót pliku Word (Edytor CV 2, PR 5).
 *
 * Trzy trasy TYLKO DO ODCZYTU — żadna nie zapisuje szkicu:
 *
 * - `GET  /api/candidates/stages/{id}/cv/branded/versions` — zatwierdzone wersje,
 * - `GET  /api/candidates/stages/{id}/cv/branded/versions/{n}` — treść jednej wersji,
 * - `POST /api/candidates/stages/{id}/cv/branded/import-preview` — plik Word
 *   zamieniony na HTML edytora (bez zapisu; `…/upload` z okna „Użyj innego CV”
 *   zapisuje od razu i odłącza CV od generatora — to inna funkcja).
 *
 * Przywrócenie wersji i przyjęcie treści z Worda robi EDYTOR jedną cofalną
 * zmianą, a utrwala je zwykły autozapis (jedna ścieżka zapisu).
 */

import api from "@/lib/api";

export interface CvVersionSummary {
  /** Numer wersji etapu (`branded_version` w chwili zatwierdzenia). */
  version: number;
  /** ISO 8601; `null` dla starych wierszy bez daty. */
  approved_at: string | null;
  /** Imię i nazwisko zatwierdzającego (nie e-mail); `null`, gdy nieznany. */
  approved_by_name: string | null;
  language: "pl" | "en";
  /** Czy wersja ma zamrożony plik Word do pobrania. */
  docx_available: boolean;
  /** Wersja, którą etap pokazuje teraz jako zatwierdzoną. */
  is_current: boolean;
}

export interface CvVersionsResponse {
  /** Od najnowszej. Pusta lista = CV nie było jeszcze zatwierdzone. */
  versions: CvVersionSummary[];
}

export interface CvVersionContent {
  version: number;
  /** HTML zatwierdzonej wersji (ten sam kształt co `content_html` edytora). */
  content_html: string;
  language: "pl" | "en";
  approved_at: string | null;
}

export interface CvImportPreview {
  /** Treść pliku Word jako HTML edytora — NIC nie zostało zapisane. */
  content_html: string;
  /** Nazwa wgranego pliku, do pokazania w panelu. */
  filename: string;
  /**
   * Plik ma układ szablonu B2B („Dlaczego nasz kandydat?”, „Nazwa firmy:”).
   * `false` = wygląda na CV kandydata (29.10.2026); brak w starszych odpowiedziach.
   */
  b2b_template?: boolean;
}

export interface CvEditorHistoryApi {
  versions: (stageId: number) => Promise<CvVersionsResponse>;
  version: (stageId: number, version: number) => Promise<CvVersionContent>;
  importPreview: (stageId: number, file: File) => Promise<CvImportPreview>;
}

const base = (stageId: number) => `/api/candidates/stages/${stageId}/cv/branded`;

export const networkHistoryApi: CvEditorHistoryApi = {
  versions: (stageId) => api.get<CvVersionsResponse>(`${base(stageId)}/versions`).then((r) => r.data),
  version: (stageId, version) =>
    api.get<CvVersionContent>(`${base(stageId)}/versions/${version}`).then((r) => r.data),
  importPreview: (stageId, file) => {
    const form = new FormData();
    form.append("file", file);
    return api
      .post<CvImportPreview>(`${base(stageId)}/import-preview`, form, {
        // Jawnie: instancja `api` ma domyślne `application/json`, a axios przy
        // tym nagłówku serializuje `FormData` do JSON-a — plik nie opuściłby
        // przeglądarki (strażnik `formdata-multipart.test.ts`).
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((r) => r.data);
  },
};
