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
 *
 * `download` podaje przycisk „Pobierz” (miejsce w aplikacji) — serwer zapisuje
 * wtedy pobranie pliku; podgląd woła bez niego.
 */

import api, { type CVBrandedState } from "@/lib/api";
import {
  fetchAuthenticatedDownload,
  postAuthenticatedDownload,
  type AuthenticatedDownload,
} from "@/lib/authenticated-files";
import { withDownloadIntent, type CvDownloadSurface } from "@/lib/cv-download-intent";

type UrlFor = (path: string) => string;

function urlFor(opts?: { download?: CvDownloadSurface }): UrlFor {
  return (path: string) => (opts?.download ? withDownloadIntent(path, opts.download) : path);
}

async function stageBranded(stageId: number): Promise<CVBrandedState> {
  const { data } = await api.get<CVBrandedState>(`/api/candidates/stages/${stageId}/cv/branded`);
  return data;
}

async function docxFile(stageId: number, branded: CVBrandedState, url: UrlFor): Promise<AuthenticatedDownload> {
  if (branded.status === "finalized") {
    const file = await fetchAuthenticatedDownload(
      url(`/api/candidates/stages/${stageId}/cv/branded/versions/${branded.version}/docx`),
    );
    return { blob: file.blob, filename: file.filename || branded.docx_filename || "CV.docx" };
  }
  const file = await postAuthenticatedDownload(
    url(`/api/candidates/stages/${stageId}/cv/branded/preview-docx`),
    { content_html: branded.content_html ?? "", expected_revision: branded.edit_revision },
  );
  return { blob: file.blob, filename: file.filename || "SZKIC_CV.docx" };
}

async function pdfFile(stageId: number, branded: CVBrandedState, url: UrlFor): Promise<AuthenticatedDownload> {
  if (branded.status === "finalized") {
    const file = await fetchAuthenticatedDownload(
      url(`/api/candidates/stages/${stageId}/cv/branded/versions/${branded.version}/pdf`),
    );
    return { blob: file.blob, filename: file.filename || "CV.pdf" };
  }
  const file = await postAuthenticatedDownload(
    url(`/api/candidates/stages/${stageId}/cv/branded/preview-pdf`),
    { content_html: branded.content_html ?? "", expected_revision: branded.edit_revision },
  );
  return { blob: file.blob, filename: file.filename || "SZKIC_CV.pdf" };
}

/** Czy plik do klienta to PDF „Nowego CV” (układ CV + flaga serwera, 22.11.2026). */
export function brandedIsNewLayout(branded: CVBrandedState | null | undefined): boolean {
  return branded?.new_layout_enabled === true && branded.cv_layout === "new";
}

export async function fetchStageCvFile(
  stageId: number,
  opts?: { download?: CvDownloadSurface },
): Promise<AuthenticatedDownload> {
  return docxFile(stageId, await stageBranded(stageId), urlFor(opts));
}

/**
 * Strony CV jako PDF z TEGO SAMEGO pliku Word (Edytor CV 3, J2): wersja
 * zatwierdzona → `…/versions/{n}/pdf`, szkic → `…/preview-pdf` z bieżącej
 * treści. 503 = PDF chwilowo niedostępny, podgląd wraca wtedy do pliku Word.
 * Przy układzie „Nowe CV” te same trasy oddają PDF nowego układu.
 */
export async function fetchStageCvPdf(
  stageId: number,
  opts?: { download?: CvDownloadSurface },
): Promise<AuthenticatedDownload> {
  return pdfFile(stageId, await stageBranded(stageId), urlFor(opts));
}

/**
 * Plik, który idzie do klienta (kolejka Cpro, 22.11.2026): w układzie
 * „Nowe CV” — PDF tego układu (Word nowego wyglądu ma stronę 1 jako obraz), inaczej plik Word
 * jak dotąd. Jedno żądanie o stan CV etapu, potem jedno o plik.
 */
export async function fetchStageCvForClient(
  stageId: number,
  opts?: { download?: CvDownloadSurface },
): Promise<AuthenticatedDownload> {
  const branded = await stageBranded(stageId);
  const url = urlFor(opts);
  return brandedIsNewLayout(branded) ? pdfFile(stageId, branded, url) : docxFile(stageId, branded, url);
}
