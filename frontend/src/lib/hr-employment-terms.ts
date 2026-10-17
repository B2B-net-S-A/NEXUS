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
    "person": "Pracownik"
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
    "person": "Wykonawca"
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
    "settlement": "Rachunek",
    "person": "Zleceniobiorca"
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
