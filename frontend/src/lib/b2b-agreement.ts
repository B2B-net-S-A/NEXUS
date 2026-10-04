/**
 * Umowa B2B w rekrutacji (04.10.2026) — czyste reguły prezentacji.
 *
 * Stan umowy żyje w rejestrze Generatora; karta Tablicy, panel osoby
 * i Generator tylko go pokazują. Tu są: podpis źródła podpowiedzi formularza,
 * plakietka karty i etykieta kolumny pary w rejestrze.
 */

import type { B2BAgreementPrefill } from "@/lib/api";
import { BOARD_COLUMN_LABEL, type BoardColumnKey } from "@/lib/board-stages";
import { formatIsoDatePl } from "@/lib/date-pl";

/** Pole `agreement` karty Tablicy (`services/agreement_status.py`). */
export interface CardAgreement {
  id: number;
  number: string;
  contract_status: string;
  signature_status: string;
  created_at: string | null;
  signed_at: string | null;
  signature_requested_at: string | null;
  contract_id: number | null;
}

export type AgreementTone = "info" | "warning" | "success";

export interface AgreementBadge {
  label: string;
  tone: AgreementTone;
  title: string;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** Pełne dni od chwili `iso` do `now` (0 dla dziś i dat z przyszłości). */
export function daysSince(iso: string | null | undefined, now: Date): number | null {
  if (!iso) return null;
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return null;
  return Math.max(0, Math.floor((now.getTime() - at) / DAY_MS));
}

/**
 * Plakietka karty. Anulowana, zakończona i „bez projektu” nic nie mówią
 * o tej rekrutacji — bez plakietki.
 */
export function agreementBadge(
  agreement: CardAgreement | null | undefined,
  now: Date = new Date(),
): AgreementBadge | null {
  if (!agreement) return null;
  if (agreement.signature_status === "signed_both") {
    return {
      label: "Umowa podpisana",
      tone: "success",
      title: `Umowa ${agreement.number} podpisana obustronnie.`,
    };
  }
  if (agreement.contract_status !== "in_progress") return null;
  if (agreement.signature_requested_at) {
    return {
      label: "Prośba o podpis",
      tone: "info",
      title: `Umowa ${agreement.number}: rekruter poprosił o potwierdzenie podpisu.`,
    };
  }
  const days = daysSince(agreement.created_at, now) ?? 0;
  return {
    label: days >= 1 ? `Do podpisu · ${days} d` : "Umowa wygenerowana",
    tone: days >= 7 ? "warning" : "info",
    title: `Umowa ${agreement.number} wygenerowana, czeka na podpis.`,
  };
}

const RATE_SOURCE_LABEL: Record<NonNullable<B2BAgreementPrefill["rate"]>["source"], string> = {
  card: "z karty rekomendacji",
  this_job: "podana w tej rekrutacji",
  rate_from: "„Stawka od” kandydata",
};

/** „z karty rekomendacji · 01.10.2026” — podpis pod polem stawki. */
export function prefillRateSource(rate: B2BAgreementPrefill["rate"]): string | null {
  if (!rate) return null;
  const label = RATE_SOURCE_LABEL[rate.source];
  const at = rate.at ? formatIsoDatePl(rate.at.slice(0, 10)) : null;
  return at ? `${label} · ${at}` : label;
}

/** Kolumna Tablicy pary w rejestrze; nieznany klucz = brak etykiety. */
export function pairColumnLabel(key: string | null | undefined): string | null {
  if (!key) return null;
  return (BOARD_COLUMN_LABEL as Record<string, string>)[key as BoardColumnKey] ?? null;
}

/** Niepodpisana umowa „W trakcie” pary — okna zatrudnienia i rezygnacji pytają o nią. */
export function pendingAgreement(
  agreement: CardAgreement | null | undefined,
): CardAgreement | null {
  if (!agreement) return null;
  return agreement.signature_status === "unsigned" &&
    agreement.contract_status === "in_progress"
    ? agreement
    : null;
}

/** Podpisana umowa z żywym kontraktem — rezygnacja prowadzi do zakończenia współpracy. */
export function signedAgreementWithContract(
  agreement: CardAgreement | null | undefined,
): CardAgreement | null {
  if (!agreement) return null;
  return agreement.signature_status === "signed_both" && agreement.contract_id !== null
    ? agreement
    : null;
}
