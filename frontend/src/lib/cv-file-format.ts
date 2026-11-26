/**
 * W jakim pliku klient chce CV (reguła CV klienta, decyzja Artura z 25.11.2026).
 *
 * `null` = bez wymagań: pobranie jak dotąd, plik idzie za układem CV
 * (Klasyczne → Word, Nowe CV → PDF). Karta „CV do klienta”, edytor, dok panelu
 * i wynik generatora stawiają na pierwszym miejscu przycisk tego formatu;
 * reszta zostaje w „Więcej”.
 *
 * Etap 2 (25.11.2026): przy „Nowym CV” Word ma nowy wygląd (strona 1 jak w PDF,
 * dalej tabele) — serwer daje go sam z `…/docx`. Dotychczasowy klasyczny Word
 * zostaje w „Więcej” jako „Word (klasyczne)” (`?layout=classic`).
 */

import type { CvLayout } from "@/lib/api";

export type CvFileFormat = "docx" | "pdf" | "both";
/** `docx_classic` — klasyczny Word przy „Nowym CV” (tylko w „Więcej”). */
export type CvFileKind = "docx" | "pdf" | "docx_classic";

export const CV_FILE_FORMAT_LABEL: Record<CvFileFormat, string> = {
  docx: "Word",
  pdf: "PDF",
  both: "Word i PDF",
};

export function cvFileFormat(value: unknown): CvFileFormat | null {
  return value === "docx" || value === "pdf" || value === "both" ? value : null;
}

export interface CvDownloadPlan {
  /** Przyciski na wierzchu, w kolejności; pierwszy to główne pobranie. */
  primary: CvFileKind[];
  /** Pozostałe pliki — w menu „Więcej”. */
  inMenu: CvFileKind[];
}

export function cvDownloadPlan(format: CvFileFormat | null | undefined, layout: CvLayout): CvDownloadPlan {
  const isNew = layout === "new";
  const classicWord: CvFileKind[] = isNew ? ["docx_classic"] : [];
  switch (format) {
    case "docx":
      return { primary: ["docx"], inMenu: ["pdf", ...classicWord] };
    case "pdf":
      return { primary: ["pdf"], inMenu: ["docx", ...classicWord] };
    case "both":
      return { primary: ["docx", "pdf"], inMenu: classicWord };
    default:
      // Bez wymagań — jak przed 25.11.2026: Nowe CV = PDF i Word, klasyczne = Word.
      return isNew
        ? { primary: ["pdf", "docx"], inMenu: classicWord }
        : { primary: ["docx"], inMenu: ["pdf"] };
  }
}

/**
 * Przyciski miejsca bez menu „Więcej” (dok panelu, pasek podglądu „CV firmowe”):
 * Word i PDF obok siebie, plik klienta pierwszy. „Word (klasyczne)” zostaje
 * w karcie „CV do klienta”. Bez wymagań — jak dotąd: Word, potem PDF.
 */
export function cvDownloadsWithoutMenu(
  format: CvFileFormat | null | undefined,
  layout: CvLayout,
): ("docx" | "pdf")[] {
  if (!format) return ["docx", "pdf"];
  const plan = cvDownloadPlan(format, layout);
  return [...plan.primary, ...plan.inMenu].filter(
    (kind): kind is "docx" | "pdf" => kind !== "docx_classic",
  );
}

/** Etykieta przycisku pliku Word. */
export function wordLabel(kind: "docx" | "docx_classic"): string {
  return kind === "docx_classic" ? "Word (klasyczne)" : "Pobierz Word";
}

/**
 * Wiersz listy CV podpięty w rekrutacji (pliki kandydata, „Moje wygenerowane
 * CV”): plik z reguły klienta na wierzchu, reszta w „⋯” (25.11.2026). Pola
 * daje `GET /api/cv-generator/generated` przy CV etapu.
 */
export function stageCvRowPlan(item: {
  client_file_format?: unknown;
  stage_cv_layout?: CvLayout | null;
}): CvDownloadPlan {
  return cvDownloadPlan(cvFileFormat(item.client_file_format), item.stage_cv_layout === "new" ? "new" : "classic");
}

/** Etykieta pozycji pobrania pliku CV etapu w menu wiersza. */
export function cvKindMenuLabel(kind: CvFileKind): string {
  return kind === "pdf" ? "Pobierz PDF" : wordLabel(kind);
}

/** Dopisuje `layout=classic` do adresu pliku Word („Word (klasyczne)” przy Nowym CV). */
export function withClassicLayout(path: string, classic: boolean): string {
  if (!classic) return path;
  return `${path}${path.includes("?") ? "&" : "?"}layout=classic`;
}
