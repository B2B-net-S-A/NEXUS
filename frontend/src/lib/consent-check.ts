/**
 * Wynik sprawdzenia zrzutu zgody RODO przy wgraniu (F37, 27.10.2026).
 *
 * Backend (`services/cv_consent_check.py`): model przepisuje nagłówek maila
 * i akapit zgody, kod porównuje je z kandydatem i rekrutacją. Zrzut, który
 * nie pasuje, wraca BEZ pokwitowania — rekruter wgrywa inny albo zapisuje go
 * z powodem (wariant A), a Delivery Lead widzi to w QC CV.
 */

export type ConsentCheckStatus = "ok" | "mismatch" | "unavailable";

export interface ConsentCheckLine {
  code: string;
  detail: string;
}

export interface ConsentCheck {
  status: ConsentCheckStatus;
  problems: ConsentCheckLine[];
  passed: ConsentCheckLine[];
  override?: { reason: string; by: number; at: string } | null;
}

export interface ConsentUploadResult {
  /** Puste, gdy zrzut nie pasuje i nie podano powodu — obraz nie jest zapisany. */
  consent_token: string | null;
  filename: string;
  storage_key?: string | null;
  /** Brak w odpowiedziach sprzed sprawdzania. */
  check?: ConsentCheck | null;
}

/** Lustro `OVERRIDE_REASON_MIN` w `cv_consent_check.py`. */
export const CONSENT_OVERRIDE_REASON_MIN = 5;

/** Zrzut nie pasuje, a pokwitowania nie ma: decyzja rekrutera przed zapisem. */
export function needsConsentDecision(result: ConsentUploadResult): boolean {
  return !result.consent_token && result.check?.status === "mismatch";
}

export function overrideReasonValid(reason: string): boolean {
  return reason.trim().replace(/\s+/g, " ").length >= CONSENT_OVERRIDE_REASON_MIN;
}

/** Komunikat po dołączeniu zgody — mówi, co sprawdzono, a nie tylko „OK”. */
export function consentAttachedMessage(check: ConsentCheck | null | undefined, replaced: boolean): string {
  const base = replaced ? "Wymieniono zrzut zgody — CV przerysowane." : "Dołączono zrzut zgody — CV można pobrać.";
  if (!check) return base;
  if (check.status === "ok") {
    const zob = check.passed.find((line) => line.code === "zob");
    return zob ? `${base} Zgoda pasuje: ${zob.detail}.` : `${base} Zgoda pasuje do rekrutacji.`;
  }
  if (check.status === "unavailable") {
    return `${base} AI nie sprawdziło zrzutu — Delivery Lead obejrzy go w QC CV.`;
  }
  return `${base} Zapisano mimo uwag AI — Delivery Lead zobaczy powód w QC CV.`;
}
