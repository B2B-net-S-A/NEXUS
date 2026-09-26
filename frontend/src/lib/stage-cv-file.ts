/**
 * Plik CV firmowego ETAPU (po poprawkach QC) — do podglądu i pobrania.
 *
 * Runda 7 (R7-X4-2): przegląd DL i kolejka Cpro brały surowy DOCX
 * z generatora (`/api/cv-generator/generated/{id}/docx`), a poprawki QC
 * i edycje rekrutera żyją wyłącznie w CV etapu. Do klienta szedł wtedy inny
 * dokument niż ten, który przeszedł QC. Ta sama reguła co „Pobierz” w
 * `CvToClientCard`: wersja zatwierdzona → jej DOCX, szkic → podgląd DOCX
 * z bieżącej treści (serwer sprawdza zgodę RODO i odpowiada 409
 * `consent_required` z polskim komunikatem).
 */

import api, { type CVBrandedState } from "@/lib/api";
import {
  fetchAuthenticatedDownload,
  postAuthenticatedDownload,
  type AuthenticatedDownload,
} from "@/lib/authenticated-files";

export async function fetchStageCvFile(stageId: number): Promise<AuthenticatedDownload> {
  const { data: branded } = await api.get<CVBrandedState>(
    `/api/candidates/stages/${stageId}/cv/branded`,
  );
  if (branded.status === "finalized") {
    const file = await fetchAuthenticatedDownload(
      `/api/candidates/stages/${stageId}/cv/branded/versions/${branded.version}/docx`,
    );
    return { blob: file.blob, filename: file.filename || branded.docx_filename || "CV.docx" };
  }
  const file = await postAuthenticatedDownload(
    `/api/candidates/stages/${stageId}/cv/branded/preview-docx`,
    { content_html: branded.content_html ?? "", expected_revision: branded.edit_revision },
  );
  return { blob: file.blob, filename: file.filename || "SZKIC_CV.docx" };
}
