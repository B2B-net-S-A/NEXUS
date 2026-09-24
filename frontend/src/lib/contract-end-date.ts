/**
 * Umowa B2B jest bezterminowa, dopóki ktoś jej ręcznie nie zakończy (09.2026).
 *
 * Lustro `backend/app/services/b2b_contract_end_date.py`. Data zakończenia
 * umowy B2B przepisywana z końca ZAMÓWIENIA wysyłała konsultantów do
 * „Zakończonych" mimo trwającej współpracy, więc formularze nie oferują jej
 * dla B2B — datę ustawia „Zakończ współpracę" (powód + data, także przyszła).
 * Backend odrzuca taką datę 422-ką z tym samym
 * zdaniem, gdyby przyszła ze starej karty przeglądarki.
 */

// Status „Zakończony” nie jest już osobną drogą — ustawia go wyłącznie okno
// „Zakończ współpracę” (0367); tekst mówił inaczej (audyt 24.09, N3).
export const B2B_END_DATE_HOW =
  "Datę zakończenia ustawia okno „Zakończ współpracę” (powód i data zakończenia projektu).";

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
 * przesuwa datę zakończenia). Zakończoną umowę przywraca „Cofnij zakończenie”
 * albo „Powrót po przerwie” (0368), nie aneks.
 */
export function b2bExtensionLocked(state: ContractEndDateState): boolean {
  if ((state.contract_type ?? "b2b") !== "b2b") return false;
  return !state.terminated_at && !state.termination_reason;
}

export const B2B_EXTENSION_HINT =
  "Umowa B2B bez zakończenia jest bezterminowa — nie ma czego przedłużać. Przedłuż zamówienie klienta. Zakończenie wpisane przez pomyłkę cofa „Cofnij zakończenie”, a powrót konsultanta po przerwie — „Powrót po przerwie”.";

/**
 * Data, którą „Zakończ współpracę” podstawia przy przejściu na „Zakończony”.
 *
 * Operator wpisał ją przed chwilą w formularzu edycji — dialog ma ją przyjąć,
 * a nie pytać o to samo drugi raz. Pusta wartość z formularza (pole było
 * zablokowane dla bezterminowej B2B) cofa się do daty zapisanej na umowie;
 * brak obu zostawia dialogowi jego własną wartość domyślną (dzisiaj).
 */
export function terminationSeedDate(
  formEndDate: string | null | undefined,
  contractEndDate: string | null | undefined,
): string | undefined {
  return formEndDate || contractEndDate || undefined;
}
