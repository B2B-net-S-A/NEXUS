// Umowa zlecenia w Generatorze Umów (decyzje Artura 26.10.2026): ten sam
// rejestr co B2B, bez numeru, DPA opcjonalne, PESEL / dowód / adres tylko
// w pliku. Logika formularza bez Reacta — testy w `__tests__/b2b-mandate.test.ts`.

import type { B2BMandatePayload } from "@/lib/api";

/** Lustro `mandate.DEFAULT_DPA_PURPOSE` (backend) — cel ze wzoru z 04.09.2026. */
export const MANDATE_DPA_PURPOSE_DEFAULT =
  "wykonywanie czynności administracyjnych, wdrożeniowych, monitoringowych " +
  "i utrzymaniowych dotyczących platformy AI oraz infrastruktury, określonych " +
  "w § 1 Umowy Zlecenia.";

export const MANDATE_MAX_TASKS = 10;

export interface MandateFormState {
  candidateId: number | null;
  jobId: number | null;
  signingDate: string;
  periodFrom: string;
  periodTo: string;
  gender: "m" | "f";
  partnerName: string;
  partnerInstrumental: string;
  partnerEmail: string;
  partnerPhone: string;
  homeAddress: string;
  idDocument: string;
  pesel: string;
  tasks: string[];
  rate: string;
  withDpa: boolean;
  dpaPurpose: string;
}

export type MandateField =
  | "signingDate"
  | "periodFrom"
  | "periodTo"
  | "partnerName"
  | "pesel"
  | "tasks"
  | "rate";

export function emptyMandateForm(today: string): MandateFormState {
  return {
    candidateId: null,
    jobId: null,
    signingDate: today,
    periodFrom: today,
    periodTo: "",
    gender: "m",
    partnerName: "",
    partnerInstrumental: "",
    partnerEmail: "",
    partnerPhone: "",
    homeAddress: "",
    idDocument: "",
    pesel: "",
    tasks: [""],
    rate: "",
    withDpa: true,
    dpaPurpose: MANDATE_DPA_PURPOSE_DEFAULT,
  };
}

const PESEL_WEIGHTS = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3];

/** 11 cyfr i poprawna cyfra kontrolna — ta sama reguła co na serwerze. */
export function peselValid(value: string): boolean {
  if (!/^\d{11}$/.test(value)) return false;
  const sum = PESEL_WEIGHTS.reduce((acc, w, i) => acc + w * Number(value[i]), 0);
  return (10 - (sum % 10)) % 10 === Number(value[10]);
}

export function parseRate(raw: string): number | null {
  const v = raw.trim().replace(/\s/g, "").replace(",", ".");
  if (!v) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** Błędy pól; pusty obiekt = można wysłać. Minimum stawki sprawdza serwer
 *  (tabela z Ustawień → Płace może zmienić się bez wdrożenia frontu). */
export function mandateErrors(
  state: MandateFormState,
): Partial<Record<MandateField, string>> {
  const errors: Partial<Record<MandateField, string>> = {};
  if (!state.partnerName.trim()) errors.partnerName = "Wpisz imię i nazwisko.";
  if (!state.signingDate) errors.signingDate = "Podaj datę zawarcia umowy.";
  if (!state.periodFrom) errors.periodFrom = "Podaj początek zlecenia.";
  if (!state.periodTo) errors.periodTo = "Podaj koniec zlecenia.";
  else if (state.periodFrom && state.periodTo < state.periodFrom)
    errors.periodTo = "Koniec zlecenia nie może być przed jego początkiem.";
  const pesel = state.pesel.trim();
  if (pesel && !peselValid(pesel))
    errors.pesel = "PESEL ma 11 cyfr i poprawną cyfrę kontrolną.";
  if (!state.tasks.some((t) => t.trim()))
    errors.tasks = "Wpisz co najmniej jedną czynność z § 1.";
  const rate = parseRate(state.rate);
  if (rate === null || rate <= 0)
    errors.rate = "Podaj stawkę brutto za godzinę.";
  return errors;
}

/** Etykieta wiersza rejestru — lustro `mandate.mandate_label` (backend). */
export function mandateLabel(signingDate: string): string {
  const [y, m, d] = signingDate.split("-");
  return y && m && d ? `Zlecenie z dnia ${d}.${m}.${y}` : "Umowa zlecenia";
}

function blankToNull(value: string): string | null {
  const v = value.trim();
  return v ? v : null;
}

export function mandatePayload(state: MandateFormState): B2BMandatePayload {
  // Para (kandydat, rekrutacja) idzie razem albo wcale — jak przy B2B.
  const paired = state.candidateId !== null && state.jobId !== null;
  return {
    candidate_id: paired ? state.candidateId : null,
    job_id: paired ? state.jobId : null,
    client_name: null,
    signing_date: state.signingDate,
    period_from: state.periodFrom,
    period_to: state.periodTo,
    gender: state.gender,
    partner_name: state.partnerName.trim(),
    partner_instrumental: blankToNull(state.partnerInstrumental),
    partner_email: blankToNull(state.partnerEmail),
    partner_phone: blankToNull(state.partnerPhone),
    home_address: blankToNull(state.homeAddress),
    id_document: blankToNull(state.idDocument),
    pesel: blankToNull(state.pesel),
    tasks: state.tasks.map((t) => t.trim()).filter(Boolean),
    gross_hourly_rate: parseRate(state.rate) ?? 0,
    with_dpa: state.withDpa,
    dpa_purpose: state.withDpa ? blankToNull(state.dpaPurpose) : null,
  };
}
