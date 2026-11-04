/**
 * „Szczegóły administracyjne” umowy w Generatorze (0524, decyzje Artura
 * 26.10.2026). Rekruter i Delivery Lead to odbiorcy premii z reguły automatu
 * (tylko do odczytu); wpisuje się replacement i wymiar FTE. Czyste funkcje —
 * kafelek i oba formularze (B2B, zlecenie) korzystają z tych samych.
 */

import type {
  AgreementAdminFields,
  AgreementFte,
  B2BAgreementAdminDefaults,
  B2BReplaceableContract,
} from "@/lib/api";

export const FTE_OPTIONS: AgreementFte[] = ["1", "0.75", "0.5", "0.25"];
/** Premie rekrutera i DL-a przychodzą po 168 h pracy kontraktora. */
export const BONUS_HOURS = 168;
const HOURS_PER_DAY = 8;

export interface AgreementAdminValue {
  /** null = nikt jeszcze nie wybrał (przed rekrutacją). */
  isReplacement: boolean | null;
  replaced: B2BReplaceableContract | null;
  fte: AgreementFte | null;
}

export const EMPTY_ADMIN_VALUE: AgreementAdminValue = {
  isReplacement: null,
  replaced: null,
  fte: null,
};

/**
 * Wartości po wybraniu rekrutacji: zastępstwo z tytułu (z osobą, gdy serwer
 * ją jednoznacznie wskazał), inaczej „Nie”; FTE 1 — rekrutacja nie ma pola FTE,
 * a pełny etat ma każda z 4495 rekrutacji na kopii produkcji.
 */
export function adminDefaults(
  defaults: B2BAgreementAdminDefaults | null | undefined,
): AgreementAdminValue {
  return {
    isReplacement: Boolean(defaults?.replacement_from_title),
    replaced: defaults?.replacement_from_title
      ? (defaults.replaced ?? null)
      : null,
    fte: "1",
  };
}

export function isAdminComplete(value: AgreementAdminValue): boolean {
  return (
    value.fte !== null &&
    value.isReplacement !== null &&
    (!value.isReplacement || value.replaced !== null)
  );
}

/** Pola żądania `/render` i `/mandate/render`. */
export function adminPayload(value: AgreementAdminValue): AgreementAdminFields {
  return {
    is_replacement: value.isReplacement,
    replaced_contract_id: value.isReplacement
      ? (value.replaced?.contract_id ?? null)
      : null,
    fte: value.fte,
  };
}

/** Odtworzenie wyboru przy „Popraw umowę” (zapisany payload + osoba z serwera). */
export function adminFromSaved(
  form: AgreementAdminFields,
  replaced: B2BReplaceableContract | null | undefined,
): AgreementAdminValue | null {
  if (form.is_replacement == null && form.fte == null) return null;
  const fte = FTE_OPTIONS.find((f) => Number(f) === Number(form.fte)) ?? null;
  return {
    isReplacement: form.is_replacement ?? null,
    replaced: form.is_replacement ? (replaced ?? null) : null,
    fte,
  };
}

export function fteLabel(fte: AgreementFte): string {
  return fte.replace(".", ",");
}

/** Ile dni roboczych (po 8 h) zajmie 168 h pracy przy danym FTE. */
export function bonusBusinessDays(fte: AgreementFte): number {
  return Math.ceil(BONUS_HOURS / (HOURS_PER_DAY * Number(fte)));
}

/**
 * Pełne miesiące kontraktu osoby zastąpionej (start → koniec). Krócej niż
 * rok = gwarancja: za placement-zastępstwo premia DL się nie należy
 * (decyzja Artura 26.10.2026; rekruterzy od 2027).
 */
export function monthsWorked(contract: B2BReplaceableContract): number | null {
  if (!contract.start_date || !contract.end_date) return null;
  const [sy, sm, sd] = contract.start_date.split("-").map(Number);
  const [ey, em, ed] = contract.end_date.split("-").map(Number);
  // Ostatni dzień pracy wlicza się: liczymy do dnia po nim.
  const after = new Date(Date.UTC(ey, em - 1, ed + 1));
  const months =
    (after.getUTCFullYear() - sy) * 12 +
    (after.getUTCMonth() + 1 - sm) -
    (after.getUTCDate() < sd ? 1 : 0);
  return Math.max(0, months);
}

export function underWarranty(
  contract: B2BReplaceableContract | null,
): boolean {
  if (!contract) return false;
  const months = monthsWorked(contract);
  return months !== null && months < 12;
}
