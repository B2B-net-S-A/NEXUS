/**
 * W jakim pliku klient chce CV (reguła CV klienta, decyzja Artura z 25.11.2026).
 *
 * `null` = bez wymagań: pobranie jak dotąd, plik idzie za układem CV
 * (Klasyczne → Word, Nowe CV → PDF). Karta „CV do klienta”, edytor i wynik
 * generatora stawiają na pierwszym miejscu przycisk tego formatu; drugi
 * format zostaje w „Więcej”.
 *
 * Do etapu 2 plik Word jest zawsze w układzie klasycznym, więc klient
 * z Wordem i CV w układzie „Nowe CV” dostaje ostrzeżenie (`warnWordClassic`).
 */

import type { CvLayout } from "@/lib/api";

export type CvFileFormat = "docx" | "pdf" | "both";
export type CvFileKind = "docx" | "pdf";

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
  /** Pozostały format — w menu „Więcej”. */
  inMenu: CvFileKind[];
  /** Klient chce Worda, a CV jest w układzie „Nowe CV” (Word będzie klasyczny). */
  warnWordClassic: boolean;
}

export function cvDownloadPlan(format: CvFileFormat | null | undefined, layout: CvLayout): CvDownloadPlan {
  const isNew = layout === "new";
  switch (format) {
    case "docx":
      return { primary: ["docx"], inMenu: ["pdf"], warnWordClassic: isNew };
    case "pdf":
      return { primary: ["pdf"], inMenu: ["docx"], warnWordClassic: false };
    case "both":
      return { primary: ["docx", "pdf"], inMenu: [], warnWordClassic: isNew };
    default:
      // Bez wymagań — jak przed 25.11.2026.
      return isNew
        ? { primary: ["pdf", "docx"], inMenu: [], warnWordClassic: false }
        : { primary: ["docx"], inMenu: ["pdf"], warnWordClassic: false };
  }
}

/** Ostrzeżenie przy CV, gdy klient chce Worda, a wybrane jest Nowe CV. */
export function wordClassicWarning(format: CvFileFormat | null | undefined): string {
  return format === "both"
    ? "Klient chce Worda i PDF, a wybrane jest Nowe CV. PDF będzie w nowym układzie, a Word na razie tylko w klasycznym — wyślij oba albo przełącz na Klasyczne."
    : "Klient chce Worda, a wybrane jest Nowe CV. Word na razie powstaje tylko w układzie klasycznym — przełącz na Klasyczne albo uzgodnij z klientem PDF.";
}
