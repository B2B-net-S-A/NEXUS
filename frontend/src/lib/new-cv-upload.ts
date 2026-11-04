/**
 * Nowe CV kandydata w rekrutacji (29.10.2026, decyzje Artura D1 = A).
 *
 * Rekruter wgrywa nowe CV (np. z LinkedIna) w panelu osoby, w karcie „CV do
 * klienta” albo w podglądzie. Serwer w odpowiedzi mówi, co z CV do klienta
 * pary (`company_cv`): generuje się samo z nowego pliku, pytamy, czeka na
 * potwierdzenia, zostaje (po „CV wysłane”) albo klient bierze formularz.
 *
 * Wynik wgrania żyje w pamięci zapytań pod kluczem pary (osoba, rekrutacja):
 * blok „Nowe CV” w karcie i w panelu czyta go niezależnie od tego, gdzie
 * plik wgrano, a panel potwierdzeń w karcie zaczyna z potwierdzonym plikiem.
 * Tu tylko klucz, kształt i zdania — rysuje `recruitment/NewCvProgress`.
 */

import type { NewCvCompanyCvPlan, StageCvUploadResult } from "@/lib/api";

export interface NewCvUpload {
  /** Chwila wgrania (ms) — czas oczekiwania na nową wersję liczymy od niej. */
  at: number;
  filename: string;
  documentId: number | null;
  plan: NewCvCompanyCvPlan;
  /** Wiersz etapu z CV do klienta pary (po ruchu karty bywa wcześniejszy). */
  companyStageId: number | null;
  companyStatus: string | null;
  regeneratingId: number | null;
  /** Data kopii „Oryginał CV” — klucz ramki „CV firmowe powstało z poprzedniego CV”. */
  snapshotAt: string | null;
}

export function newCvUploadKey(candidateId: number, jobId: number) {
  return ["new-cv-upload", candidateId, jobId] as const;
}

/** Odpowiedź wgrania → wpis bloku; `null`, gdy serwer nic nie mówi o CV do klienta. */
export function newCvUploadFrom(
  data: StageCvUploadResult | undefined,
  fallbackName: string,
  at: number,
): NewCvUpload | null {
  if (!data?.company_cv) return null;
  return {
    at,
    filename: data.uploaded_filename ?? fallbackName,
    documentId: data.uploaded_document_id ?? null,
    plan: data.company_cv,
    companyStageId: data.company_cv_stage_id ?? null,
    companyStatus: data.company_cv_status ?? null,
    regeneratingId: data.regenerating_document_id ?? null,
    snapshotAt: data.original_snapshot_at ?? null,
  };
}

/** Tak długo czekamy na nową wersję — jak karta „CV do klienta” na generację. */
export const NEW_CV_WAIT_MS = 5 * 60_000;

export type NewCvCompanyStep =
  | { kind: "generating" }
  | { kind: "replaced" }
  | { kind: "slow" }
  | { kind: "ask"; sentence: string }
  | { kind: "confirm" }
  | { kind: "locked" }
  | { kind: "none" };

/**
 * Krok „CV do klienta” bloku. ``attachedId`` = dokument, z którego jest teraz
 * CV do klienta pary; gdy to dokument z generacji po nowym CV — podmienione.
 */
export function newCvCompanyStep(
  upload: NewCvUpload,
  attachedId: number | null | undefined,
  now: number,
): NewCvCompanyStep {
  switch (upload.plan) {
    case "regenerating":
      if (upload.regeneratingId != null && attachedId === upload.regeneratingId) return { kind: "replaced" };
      return now - upload.at < NEW_CV_WAIT_MS ? { kind: "generating" } : { kind: "slow" };
    case "ask":
      return {
        kind: "ask",
        sentence:
          upload.companyStatus === "finalized"
            ? "CV do klienta jest już zatwierdzone."
            : "CV do klienta ktoś już poprawiał albo wybrał.",
      };
    case "confirm":
      return { kind: "confirm" };
    case "locked":
      return { kind: "locked" };
    default:
      return { kind: "none" };
  }
}
