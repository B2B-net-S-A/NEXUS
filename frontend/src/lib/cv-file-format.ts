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

/** Etykieta przycisku pliku Word. */
export function wordLabel(kind: "docx" | "docx_classic"): string {
  return kind === "docx_classic" ? "Word (klasyczne)" : "Pobierz Word";
}

/** Dopisuje `layout=classic` do adresu pliku Word („Word (klasyczne)” przy Nowym CV). */
export function withClassicLayout(path: string, classic: boolean): string {
  if (!classic) return path;
  return `${path}${path.includes("?") ? "&" : "?"}layout=classic`;
}
