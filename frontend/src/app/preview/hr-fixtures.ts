/**
 * Wspólna obsada harnessów „Ludzie w NEXUSIE” (`/preview/hr-*`, 17.10.2026).
 *
 * Osoby, klienci, e-maile, numery i kwoty są ZMYŚLONE (repo jest publiczne,
 * strażnik `harness-fictional-data.test.ts`). Role i układ odpowiadają
 * makietom raportu „Ludzie w NEXUSIE”, nazwiska nie — makieta miała zwykłe
 * polskie nazwiska, harness ma wyraźnie fikcyjne.
 */

import type { HrConfig, HrModuleKey } from "@/lib/api/hr";
import type { UserRole } from "@/store/auth";

import type { HarnessUser } from "./hr-harness";

export interface HarnessPerson extends HarnessUser {
  /** Inicjały do awatarów i list. */
  initials: string;
  jobTitle: string;
  department: string;
}

function person(
  id: number,
  name: string,
  role: UserRole,
  jobTitle: string,
  department: string,
): HarnessPerson {
  const [first, last] = name.split(" ");
  const ascii = (text: string) =>
    text
      .normalize("NFD")
      .replace(/\p{Diacritic}/gu, "")
      .replace(/ł/g, "l")
      .replace(/Ł/g, "L")
      .toLowerCase();
  return {
    id,
    name,
    email: `${ascii(first)}.${ascii(last)}@example.com`,
    role,
    roles: [role],
    initials: `${first[0]}${last[0]}`,
    jobTitle,
    department,
  };
}

/** Obsada: ta sama osoba ma ten sam numer we wszystkich harnessach HR. */
export const HR_CAST = {
  /** Rekruterka, zastępuje Kamila (makieta: pulpit, Mój miesiąc). */
  ola: person(101, "Ola Przykładowa", "recruiter", "Rekruterka", "Rekrutacja IT"),
  /** Delivery Lead na urlopie (makieta: wniosek urlopowy). */
  kamil: person(102, "Kamil Testowy", "delivery_lead", "Delivery Lead", "Delivery"),
  ewa: person(103, "Ewa Makietowa", "recruiter", "Rekruterka", "Rekrutacja IT"),
  adam: person(104, "Adam Wzorcowy", "delivery_lead", "Delivery Lead", "Delivery"),
  /** Przełożona 9 osób (makieta: Akceptacje). */
  marta: person(105, "Marta Fikcyjna", "head_of_recruitment", "Head of Recruitment", "Rekrutacja IT"),
  /** Odchodzi 30.11 (makieta: Odejście). */
  tomasz: person(106, "Tomasz Podglądowy", "recruiter", "Rekruter", "Rekrutacja IT"),
  julia: person(107, "Julia Próbna", "recruiter", "Rekruterka", "Rekrutacja IT"),
  /** Recepcja (makieta: Sprzęt). */
  zofia: person(108, "Zofia Recepcyjna", "user", "Recepcja", "Administracja"),
  /** Finanse z uprawnieniem Płace (makieta: Płace i premie). */
  piotr: person(109, "Piotr Finansowy", "finance", "Kontroler finansowy", "Finanse"),
  /** Talent Community Manager — opiekunka konsultantów (makieta: Opieka). */
  natalia: person(110, "Natalia Opiekuńcza", "talent_community_manager", "Talent Community Manager", "Delivery"),
  /** Nowa osoba (makieta: Wejście nowej osoby). */
  kacper: person(111, "Kacper Nowicjusz", "recruiter", "Rekruter", "Rekrutacja IT"),
  /** Kadry z uprawnieniami Kadry i Płace (makieta: Kartoteka osoby). */
  paulina: person(112, "Paulina Kadrowa", "user", "Specjalistka ds. kadr", "Administracja"),
  admin: person(113, "Aniela Administrująca", "admin", "Administratorka", "Administracja"),
} as const;

/** Konsultanci u klientów (kontrakty, opieka, sprzęt kontraktora). */
export const HR_CONSULTANTS = {
  michal: { id: 9101, name: "Michał Konsultantowy", email: "michal.konsultantowy@example.com" },
  karolina: { id: 9102, name: "Karolina Przykładowa", email: "karolina.przykladowa@example.com" },
  bartosz: { id: 9103, name: "Bartosz Testowy", email: "bartosz.testowy@example.com" },
  anna: { id: 9104, name: "Anna Kontraktorska", email: "anna.kontraktorska@example.com" },
  pawel: { id: 9105, name: "Paweł Makietowy", email: "pawel.makietowy@example.com" },
} as const;

/** Klienci fikcyjni (w makiecie: Nordline Bank, Vistra Telecom, Polmed IT, Arkada Insurance). */
export const HR_CLIENTS = {
  bank: { id: 7001, name: "Bank Przykładowy" },
  telecom: { id: 7002, name: "Telekom Wzorcowy" },
  clinic: { id: 7003, name: "Klinika Testowa IT" },
  insurance: { id: 7004, name: "Ubezpieczenia Fikcyjne" },
} as const;

const ALL_MODULES: Record<HrModuleKey, boolean> = {
  people: true,
  leave: true,
  time: true,
  payroll: true,
  lifecycle: true,
  care: true,
  cases: true,
  equipment: true,
  settlements: false,
};

/** Stan modułów i prawa oglądającego — wszystkie moduły włączone. */
export function hrConfig(me: Partial<HrConfig["me"]> = {}): HrConfig {
  return {
    program: true,
    modules: { ...ALL_MODULES },
    open_modules: { ...ALL_MODULES },
    me: {
      has_profile: true,
      employment_status: "active",
      is_manager: false,
      direct_reports: 0,
      is_admin: false,
      people_admin: false,
      payroll: false,
      equipment: false,
      cases: false,
      has_assigned_cases: false,
      covering: [],
      ...me,
    },
  };
}

// ── Kalendarz harnessów ─────────────────────────────────────────────────────
// Ekrany liczą „dziś” z zegara przeglądarki (Europe/Warsaw), więc klucze
// zapytań i daty w danych budujemy względem bieżącego miesiąca, a nie na
// sztywno — inaczej harness otwarty w innym miesiącu pokazywałby pustkę
// albo wysyłał niezasiane zapytanie.

/** Święta o stałej dacie (bez ruchomych) — wystarczą do rysowania fikcji. */
const FIXED_HOLIDAYS: Record<string, string> = {
  "01-01": "Nowy Rok",
  "01-06": "Trzech Króli",
  "05-01": "Święto Pracy",
  "05-03": "Święto Konstytucji 3 Maja",
  "08-15": "Wniebowzięcie NMP",
  "11-01": "Wszystkich Świętych",
  "11-11": "Narodowe Święto Niepodległości",
  "12-24": "Wigilia",
  "12-25": "Boże Narodzenie",
  "12-26": "Drugi dzień Bożego Narodzenia",
};

export type HarnessDayKind = "work" | "weekend" | "holiday";

export interface HarnessDay {
  date: string;
  /** 0 = poniedziałek … 6 = niedziela. */
  weekday: number;
  kind: HarnessDayKind;
  name: string | null;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** Dni miesiąca `YYYY-MM` z rodzajem dnia. */
export function harnessMonthDays(month: string): HarnessDay[] {
  const [year, number] = month.split("-").map(Number);
  const count = new Date(Date.UTC(year, number, 0)).getUTCDate();
  return Array.from({ length: count }, (_, index) => {
    const date = `${month}-${pad(index + 1)}`;
    const weekday = (new Date(Date.UTC(year, number - 1, index + 1)).getUTCDay() + 6) % 7;
    const holiday = FIXED_HOLIDAYS[date.slice(5)] ?? null;
    const kind: HarnessDayKind = holiday ? "holiday" : weekday >= 5 ? "weekend" : "work";
    return { date, weekday, kind, name: holiday };
  });
}

/** Dni robocze miesiąca (daty ISO). */
export function harnessWorkDays(month: string): string[] {
  return harnessMonthDays(month)
    .filter((day) => day.kind === "work")
    .map((day) => day.date);
}

/** N-ty dzień roboczy miesiąca (od 1); poza zakresem — ostatni. */
export function nthWorkDay(month: string, n: number): string {
  const days = harnessWorkDays(month);
  return days[Math.min(Math.max(n, 1), days.length) - 1];
}

/** Dzień kalendarzowy `YYYY-MM-DD` przesunięty o `delta` dni. */
export function shiftDay(day: string, delta: number): string {
  const [year, month, date] = day.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, month - 1, date + delta));
  return `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}`;
}
