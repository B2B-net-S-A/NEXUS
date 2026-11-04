// Słowa według formy współpracy (etap 2, D1 i D4, 17.10.2026).
//
// Prawie cała firma jest na B2B albo zleceniu, umowa o pracę zdarza się
// pojedynczo. Od 08.07.2026 PIP może sam stwierdzić stosunek pracy, a „wniosek
// urlopowy” akceptowany przez „przełożonego” to typowy sygnał podporządkowania.
// Dlatego każdy ekran modułu bierze słowa z formy osoby: umowa o pracę —
// urlop, wniosek, przełożony, ewidencja czasu pracy; B2B — przerwa
// w świadczeniu usług, zgłoszenie, koordynator, raport godzin; zlecenie —
// nieobecność, zgłoszenie, koordynator, potwierdzenie godzin (art. 8b).
// Brak formy = jak umowa o pracę.
//
// `EMPLOYMENT_TERMS` to lustro słowo w słowo backendu
// (`backend/app/services/hr/employment_terms.py`, strażnik
// `backend/tests/test_hr_employment_terms_mirror.py` czyta ten blok jako JSON —
// cudzysłowy przy kluczach i bez przecinka na końcu zostają).

import type { EmploymentType } from "@/lib/api/hr";

export interface EmploymentTerms {
  form: string;
  form_short: string;
  /** `request` — wniosek do akceptacji (UoP); `report` — zgłoszenie (B2B, zlecenie, D5). */
  flow: "request" | "report";
  absence: string;
  absence_short: string;
  absence_accusative: string;
  absence_instrumental: string;
  absences_title: string;
  request: string;
  submit_action: string;
  dialog_title: string;
  coordinator: string;
  coordinator_genitive: string;
  timesheet: string;
  timesheet_accusative: string;
  timesheet_genitive: string;
  review_verb: string;
  review_noun: string;
  settlement: string;
  person: string;
  /** „nadgodziny” przy UoP, „godziny ponad 8 h” przy B2B i zleceniu (21.10.2026). */
  overtime: string;
  overtime_genitive: string;
  overtime_instrumental: string;
  /** Etykieta sumy miesiąca: „nadgodziny” / „ponad 8 h dziennie”. */
  overtime_stat: string;
  overtime_reason: string;
  overtime_reason_hint: string;
  overtime_reason_required: string;
  overtime_fill_note: string;
  /** „premia” przy UoP, „wynagrodzenie dodatkowe” przy B2B i zleceniu (21.10.2026). */
  bonus: string;
  bonuses: string;
  bonuses_genitive: string;
  bonuses_tab: string;
  /** Domyślny opis dnia: „Praca standardowa” przy UoP, „Realizacja usług zgodnie z umową” przy B2B i zleceniu (28.10.2026). */
  standard_description: string;
}

export const EMPLOYMENT_TERMS = {
  "uop": {
    "form": "Umowa o pracę",
    "form_short": "UoP",
    "flow": "request",
    "absence": "urlop",
    "absence_short": "urlop",
    "absence_accusative": "urlop",
    "absence_instrumental": "urlopem",
    "absences_title": "Urlop",
    "request": "wniosek",
    "submit_action": "Złóż wniosek urlopowy",
    "dialog_title": "Wniosek o nieobecność",
    "coordinator": "przełożony",
    "coordinator_genitive": "przełożonego",
    "timesheet": "Ewidencja czasu pracy",
    "timesheet_accusative": "ewidencję czasu pracy",
    "timesheet_genitive": "ewidencji czasu pracy",
    "review_verb": "akceptuje",
    "review_noun": "akceptacji",
    "settlement": "Lista płac",
    "person": "Pracownik",
    "overtime": "nadgodziny",
    "overtime_genitive": "nadgodzin",
    "overtime_instrumental": "nadgodzinami",
    "overtime_stat": "nadgodziny",
    "overtime_reason": "Uzasadnienie nadgodzin",
    "overtime_reason_hint": "Suma dnia przekroczy 8 h — napisz, czym były nadgodziny.",
    "overtime_reason_required": "Nadgodziny wymagają uzasadnienia",
    "overtime_fill_note": "nadgodziny wpisuje się w dniu, z uzasadnieniem",
    "bonus": "premia",
    "bonuses": "premie",
    "bonuses_genitive": "premii",
    "bonuses_tab": "Premie i stawka",
    "standard_description": "Praca standardowa"
  },
  "b2b": {
    "form": "B2B",
    "form_short": "B2B",
    "flow": "report",
    "absence": "przerwa w świadczeniu usług",
    "absence_short": "przerwa",
    "absence_accusative": "przerwę w świadczeniu usług",
    "absence_instrumental": "przerwą w świadczeniu usług",
    "absences_title": "Przerwy",
    "request": "zgłoszenie",
    "submit_action": "Zgłoś przerwę",
    "dialog_title": "Zgłoś przerwę w świadczeniu usług",
    "coordinator": "koordynator",
    "coordinator_genitive": "koordynatora",
    "timesheet": "Raport godzin",
    "timesheet_accusative": "raport godzin",
    "timesheet_genitive": "raportu godzin",
    "review_verb": "potwierdza",
    "review_noun": "potwierdzenia",
    "settlement": "Faktura",
    "person": "Wykonawca",
    "overtime": "godziny ponad 8 h",
    "overtime_genitive": "godzin ponad 8 h",
    "overtime_instrumental": "godzinami ponad 8 h",
    "overtime_stat": "ponad 8 h dziennie",
    "overtime_reason": "Czego dotyczyły godziny ponad 8 h",
    "overtime_reason_hint": "Dzień ponad 8 h — dopisz krótko, czego dotyczył. Koordynator zobaczy to w raporcie godzin.",
    "overtime_reason_required": "Dopisz, czego dotyczyły godziny ponad 8 h",
    "overtime_fill_note": "godziny ponad 8 h wpisuje się w dniu, z krótkim opisem",
    "bonus": "wynagrodzenie dodatkowe",
    "bonuses": "wynagrodzenie dodatkowe",
    "bonuses_genitive": "wynagrodzenia dodatkowego",
    "bonuses_tab": "Wynagrodzenie dodatkowe i stawka",
    "standard_description": "Realizacja usług zgodnie z umową"
  },
  "zlecenie": {
    "form": "Umowa zlecenie",
    "form_short": "Zlecenie",
    "flow": "report",
    "absence": "nieobecność",
    "absence_short": "nieobecność",
    "absence_accusative": "nieobecność",
    "absence_instrumental": "nieobecnością",
    "absences_title": "Nieobecności",
    "request": "zgłoszenie",
    "submit_action": "Zgłoś nieobecność",
    "dialog_title": "Zgłoś nieobecność",
    "coordinator": "koordynator",
    "coordinator_genitive": "koordynatora",
    "timesheet": "Potwierdzenie godzin",
    "timesheet_accusative": "potwierdzenie godzin",
    "timesheet_genitive": "potwierdzenia godzin",
    "review_verb": "potwierdza",
    "review_noun": "potwierdzenia",
    "settlement": "Potwierdzenie godzin",
    "person": "Zleceniobiorca",
    "overtime": "godziny ponad 8 h",
    "overtime_genitive": "godzin ponad 8 h",
    "overtime_instrumental": "godzinami ponad 8 h",
    "overtime_stat": "ponad 8 h dziennie",
    "overtime_reason": "Czego dotyczyły godziny ponad 8 h",
    "overtime_reason_hint": "Dzień ponad 8 h — dopisz krótko, czego dotyczył. Koordynator zobaczy to w potwierdzeniu godzin.",
    "overtime_reason_required": "Dopisz, czego dotyczyły godziny ponad 8 h",
    "overtime_fill_note": "godziny ponad 8 h wpisuje się w dniu, z krótkim opisem",
    "bonus": "wynagrodzenie dodatkowe",
    "bonuses": "wynagrodzenie dodatkowe",
    "bonuses_genitive": "wynagrodzenia dodatkowego",
    "bonuses_tab": "Wynagrodzenie dodatkowe i stawka",
    "standard_description": "Realizacja usług zgodnie z umową"
  }
} as const satisfies Record<EmploymentType, EmploymentTerms>;

/** Forma do słów: nieznana albo brak = umowa o pracę. */
export function formOf(type: EmploymentType | null | undefined): EmploymentType {
  return type && type in EMPLOYMENT_TERMS ? type : "uop";
}

export function employmentTerms(type: EmploymentType | null | undefined): EmploymentTerms {
  return EMPLOYMENT_TERMS[formOf(type)];
}

/** B2B i zlecenie zgłaszają nieobecność — nikt jej nie akceptuje (D5). */
export function reportsAbsence(type: EmploymentType | null | undefined): boolean {
  return employmentTerms(type).flow === "report";
}

export function capitalize(text: string): string {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

/** Przycisk zgłoszenia: „Złóż wniosek urlopowy”, „Zgłoś przerwę”, „Zgłoś nieobecność”. */
export function absenceActionLabel(form: EmploymentType | null | undefined): string {
  return employmentTerms(form).submit_action;
}

/** Nazwa raportu miesiąca: ewidencja czasu pracy, raport godzin, potwierdzenie godzin. */
export function timesheetCardTitle(form: EmploymentType | null | undefined): string {
  return employmentTerms(form).timesheet;
}

/** To samo w bierniku, do zadania „Wyślij … za październik”. */
export function timesheetAccusative(form: EmploymentType | null | undefined): string {
  return employmentTerms(form).timesheet_accusative;
}

/** „Przełożony” albo „Koordynator” — etykieta przy osobie. */
export function coordinatorLabel(form: EmploymentType | null | undefined): string {
  return capitalize(employmentTerms(form).coordinator);
}

export const MANDATE_HOURS_NOTE =
  "Liczba godzin w miesiącu — potwierdzenie z umowy zlecenia (art. 8b ustawy o minimalnym wynagrodzeniu)";
