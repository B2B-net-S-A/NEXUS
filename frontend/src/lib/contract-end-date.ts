/**
 * Umowa B2B jest bezterminowa, dopóki ktoś jej ręcznie nie zakończy (09.2026).
 *
 * Lustro `backend/app/services/b2b_contract_end_date.py`. Data zakończenia
 * umowy B2B przepisywana z końca ZAMÓWIENIA wysyłała konsultantów do
 * „Zakończonych" mimo trwającej współpracy, więc formularze nie oferują jej
 * dla B2B — datę ustawia „Zakończ współpracę" (powód + data, także przyszła)
 * albo status „Zakończony". Backend odrzuca taką datę 422-ką z tym samym
 * zdaniem, gdyby przyszła ze starej karty przeglądarki.
 */

export const B2B_END_DATE_HOW =
  "Datę zakończenia ustawia „Zakończ współpracę” (powód i data) albo status „Zakończony”.";

export const B2B_INDEFINITE_HINT = `Umowa B2B jest bezterminowa. ${B2B_END_DATE_HOW}`;

const CLOSED_STATUSES = new Set(["ended", "void"]);

export interface ContractEndDateState {
  contract_type?: string | null;
  status?: string | null;
  terminated_at?: string | null;
  termination_reason?: string | null;
}

/**
 * Czy pole daty zakończenia jest dla tej umowy zablokowane.
 *
 * Aneksu `early_termination` frontend nie widzi w tym obiekcie — takie umowy
 * pokazują pole zablokowane, a backend (który go widzi) i tak przepuści
 * wyłącznie nieruszoną datę. Zakończenie ręczne robi się przez
 * „Zakończ współpracę", które ustawia `terminated_at`.
 */
export function b2bEndDateLocked(state: ContractEndDateState): boolean {
  if ((state.contract_type ?? "b2b") !== "b2b") return false;
  if (state.status && CLOSED_STATUSES.has(state.status)) return false;
  return !state.terminated_at && !state.termination_reason;
}

/**
 * Aneks „Przedłużenie" dla umowy B2B — tylko po ręcznym zakończeniu (wtedy
 * przesuwa datę zakończenia). Umowę B2B zakończoną bez wypowiedzenia
 * przywraca się statusem „Aktywny" (wraca bezterminowa), nie aneksem.
 */
export function b2bExtensionLocked(state: ContractEndDateState): boolean {
  if ((state.contract_type ?? "b2b") !== "b2b") return false;
  return !state.terminated_at && !state.termination_reason;
}

export const B2B_EXTENSION_HINT =
  "Umowa B2B bez zakończenia jest bezterminowa — nie ma czego przedłużać. Przedłuż zamówienie klienta; zakończoną umowę przywróć statusem „Aktywny”.";
