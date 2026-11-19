/**
 * Formularz „Twoje warunki” dla kandydata (link z maila, bez logowania).
 *
 * Czyste funkcje: teksty PL/EN, przeliczenie stawki, budowa ciała żądania
 * i walidacja. Ten sam zakres i ta sama reguła 168 h co backend
 * (`backend/app/services/candidate_terms.py`). Decyzje Artura 16–17.11.2026.
 */

export type Lang = "pl" | "en";
export type Mode = "remote" | "hybrid" | "onsite";
export type RateUnit = "hour" | "month";
export type Currency = "PLN" | "EUR";
export type StartKind = "now" | "date" | "notice";
export type NoticeUnit = "weeks" | "months";

export const MODES: Mode[] = ["remote", "hybrid", "onsite"];
export const HOURS_PER_MONTH = 168;
export const RATE_MIN_HOURLY = 20;
export const RATE_MAX_HOURLY = 1000;
export const MAX_CITIES = 5;
export const CITY_SUGGESTIONS = [
  "Warszawa",
  "Gdańsk",
  "Gdynia",
  "Łódź",
  "Kraków",
  "Katowice",
  "Wrocław",
  "Poznań",
];

export interface TermsState {
  rateAmount: string;
  rateUnit: RateUnit;
  currency: Currency;
  modes: Mode[];
  onsiteDays: number | null;
  cities: string[];
  startKind: StartKind | null;
  startDate: string;
  noticeValue: string;
  noticeUnit: NoticeUnit;
}

export const EMPTY_STATE: TermsState = {
  rateAmount: "",
  rateUnit: "hour",
  currency: "PLN",
  modes: [],
  onsiteDays: null,
  cities: [],
  startKind: null,
  startDate: "",
  noticeValue: "",
  noticeUnit: "months",
};

export interface TermsPayload {
  rate?: { amount: string; unit: RateUnit; currency: Currency };
  modes: Mode[];
  onsite_days?: number;
  cities: string[];
  start?: { kind: StartKind; date?: string; value?: number; unit?: NoticeUnit };
}

export type FieldError = "rate" | "rate_range" | "start" | "empty";

/** Kwota z pola tekstowego: spacje i przecinek dziesiętny jak u ludzi. */
export function parseAmount(raw: string): number | null {
  const clean = raw.replace(/\s/g, "").replace(",", ".");
  if (!clean) return null;
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return NaN;
  return Number(clean);
}

export function hourlyRate(amount: number, unit: RateUnit): number {
  const value = unit === "month" ? amount / HOURS_PER_MONTH : amount;
  return Math.round(value * 100) / 100;
}

/** Podpowiedź, gdy kwota nie pasuje do jednostki (25 000 „za godzinę”). */
export function unitHint(amount: number | null, unit: RateUnit): "looks_monthly" | "looks_hourly" | null {
  if (amount == null || Number.isNaN(amount)) return null;
  if (unit === "hour" && amount > RATE_MAX_HOURLY) return "looks_monthly";
  if (unit === "month" && amount < (RATE_MIN_HOURLY * HOURS_PER_MONTH) / 2) return "looks_hourly";
  return null;
}

export function officeNeeded(modes: Mode[]): boolean {
  return modes.includes("hybrid") || modes.includes("onsite");
}

export function buildPayload(
  state: TermsState,
): { payload: TermsPayload; errors: FieldError[] } {
  const errors: FieldError[] = [];
  const payload: TermsPayload = { modes: [], cities: [] };
  const amount = parseAmount(state.rateAmount);
  if (amount != null) {
    if (Number.isNaN(amount) || amount <= 0) {
      errors.push("rate");
    } else {
      const hourly = hourlyRate(amount, state.rateUnit);
      if (hourly < RATE_MIN_HOURLY || hourly > RATE_MAX_HOURLY) errors.push("rate_range");
      else payload.rate = { amount: String(amount), unit: state.rateUnit, currency: state.currency };
    }
  }
  payload.modes = MODES.filter((m) => state.modes.includes(m));
  if (payload.modes.includes("hybrid") && state.onsiteDays != null) {
    payload.onsite_days = state.onsiteDays;
  }
  if (officeNeeded(payload.modes)) {
    payload.cities = state.cities.slice(0, MAX_CITIES);
  }
  if (state.startKind === "now") payload.start = { kind: "now" };
  else if (state.startKind === "date") {
    if (!state.startDate) errors.push("start");
    else payload.start = { kind: "date", date: state.startDate };
  } else if (state.startKind === "notice") {
    const value = Number(state.noticeValue);
    if (!state.noticeValue || !Number.isInteger(value) || value < 0) errors.push("start");
    else if (state.noticeUnit === "months" && value > 6) errors.push("start");
    else if (state.noticeUnit === "weeks" && value > 26) errors.push("start");
    else payload.start = { kind: "notice", value, unit: state.noticeUnit };
  }
  const empty =
    !payload.rate && !payload.modes.length && !payload.start;
  if (empty && !errors.length) errors.push("empty");
  return { payload, errors };
}

/** Ostatnia odpowiedź kandydata z API → stan formularza (przy ponownym wejściu). */
export function stateFromAnswers(answers: Record<string, unknown> | null | undefined): TermsState {
  if (!answers) return EMPTY_STATE;
  const rate = answers.rate as { amount?: string; unit?: RateUnit; currency?: Currency } | null;
  const start = answers.start as
    | { kind?: StartKind; date?: string | null; value?: number | null; unit?: NoticeUnit | null }
    | null;
  const modes = Array.isArray(answers.modes)
    ? (answers.modes as string[]).filter((m): m is Mode => (MODES as string[]).includes(m))
    : [];
  return {
    rateAmount: rate?.amount ?? "",
    rateUnit: rate?.unit ?? "hour",
    currency: rate?.currency ?? "PLN",
    modes,
    onsiteDays: typeof answers.onsite_days === "number" ? answers.onsite_days : null,
    cities: Array.isArray(answers.cities) ? (answers.cities as string[]) : [],
    startKind: start?.kind ?? null,
    startDate: start?.date ?? "",
    noticeValue: start?.value != null ? String(start.value) : "",
    noticeUnit: start?.unit ?? "months",
  };
}

/** Dodaj miasto bez duplikatu (wielkość liter bez znaczenia), najwyżej 5. */
export function addCity(cities: string[], raw: string): string[] {
  const city = raw.trim().replace(/\s+/g, " ");
  if (city.length < 2 || city.length > 60) return cities;
  if (cities.some((c) => c.toLocaleLowerCase("pl") === city.toLocaleLowerCase("pl"))) return cities;
  if (cities.length >= MAX_CITIES) return cities;
  return [...cities, city];
}

export const TEXT = {
  pl: {
    lang: "English",
    title: "Ostatni krok",
    lead: "Trzy pytania, 30 sekund. Każde jest nieobowiązkowe — odpowiedz na te, które chcesz.",
    forJob: "Po zgłoszeniu na",
    rate: "Minimalna stawka na B2B",
    rateHelp: "Kwota netto, poniżej której nie chcesz rozmawiać.",
    perHour: "za godzinę",
    perMonth: "za miesiąc",
    looksMonthly: "To wygląda na kwotę miesięczną. Przełączyć na „za miesiąc”?",
    looksHourly: "To wygląda na kwotę godzinową. Przełączyć na „za godzinę”?",
    switchUnit: "Przełącz",
    modes: "Tryb pracy",
    modesHelp: "Możesz zaznaczyć kilka.",
    mode: { remote: "Zdalnie", hybrid: "Hybrydowo", onsite: "W biurze" },
    days: "Ile dni w tygodniu w biurze",
    cities: "Miasta, do których możesz dojeżdżać",
    cityPlaceholder: "Wpisz miasto i Enter",
    addCity: "Dodaj",
    removeCity: "Usuń",
    start: "Od kiedy możesz zacząć",
    startNow: "Od zaraz",
    startDate: "Od daty",
    startNotice: "Mam okres wypowiedzenia",
    weeks: "tygodnie",
    months: "miesiące",
    submit: "Zapisz warunki",
    saving: "Zapisuję…",
    errors: {
      rate: "Podaj kwotę liczbą, np. 120 albo 18 500.",
      rate_range: "Ta stawka wychodzi poza 20–1000 zł za godzinę. Sprawdź kwotę i jednostkę.",
      start: "Uzupełnij datę albo okres wypowiedzenia (do 6 miesięcy).",
      empty: "Wypełnij choć jedno pytanie.",
      network: "Nie udało się zapisać. Sprawdź połączenie i spróbuj jeszcze raz — wpisane odpowiedzi zostają.",
    },
    savedTitle: "Komplet",
    savedLead: "Rekruter zobaczy Twoje warunki od razu przy zgłoszeniu. Możesz je poprawić tym samym linkiem do",
    edit: "Popraw odpowiedzi",
    summaryRate: "Stawka",
    summaryModes: "Tryb",
    summaryCities: "Miasta",
    summaryStart: "Start",
    expiredTitle: "Ten link wygasł",
    expiredLead: "Twoje zgłoszenie nadal jest u nas, razem z CV.",
    invalidTitle: "Ten link nie działa",
    invalidLead: "Otwórz go jeszcze raz prosto z maila. Jeśli kopiujesz adres, sprawdź, czy skopiował się w całości.",
    optoutTitle: "Nie chcesz takich pytań?",
    optoutLead: "Nie wyślemy Ci już prośby o warunki. Twoje zgłoszenie zostaje bez zmian.",
    optoutButton: "Nie chcę dostawać takich pytań",
    optoutDoneTitle: "Gotowe",
    optoutDone: "Nie wyślemy Ci już takich pytań. Twoje zgłoszenie zostaje bez zmian.",
    privacy: "Informacje o przetwarzaniu danych",
    loading: "Wczytuję…",
    kicker: "Zgłoszenie przyjęte",
    steps: ["Zgłoszenie", "CV", "Twoje warunki"],
    expiredStep: "link wygasł",
    notice: "wypowiedzenia",
    weekForms: ["tydzień", "tygodnie", "tygodni"],
    monthForms: ["miesiąc", "miesiące", "miesięcy"],
  },
  en: {
    lang: "Polski",
    title: "One last step",
    lead: "Three questions, 30 seconds. Every one is optional — answer the ones you want.",
    forJob: "For your application to",
    rate: "Minimum B2B rate",
    rateHelp: "Net amount below which you would not consider an offer.",
    perHour: "per hour",
    perMonth: "per month",
    looksMonthly: "This looks like a monthly amount. Switch to “per month”?",
    looksHourly: "This looks like an hourly amount. Switch to “per hour”?",
    switchUnit: "Switch",
    modes: "Work mode",
    modesHelp: "You can choose more than one.",
    mode: { remote: "Remote", hybrid: "Hybrid", onsite: "On site" },
    days: "Days per week in the office",
    cities: "Cities you can commute to",
    cityPlaceholder: "Type a city and press Enter",
    addCity: "Add",
    removeCity: "Remove",
    start: "When can you start",
    startNow: "Right away",
    startDate: "From a date",
    startNotice: "I have a notice period",
    weeks: "weeks",
    months: "months",
    submit: "Save my terms",
    saving: "Saving…",
    errors: {
      rate: "Enter the amount as a number, e.g. 120 or 18 500.",
      rate_range: "This rate is outside PLN 20–1000 per hour. Check the amount and the unit.",
      start: "Add the date or the notice period (up to 6 months).",
      empty: "Answer at least one question.",
      network: "Could not save. Check your connection and try again — your answers stay here.",
    },
    savedTitle: "All set",
    savedLead: "The recruiter will see your terms right away with your application. You can change them with the same link until",
    edit: "Change answers",
    summaryRate: "Rate",
    summaryModes: "Mode",
    summaryCities: "Cities",
    summaryStart: "Start",
    expiredTitle: "This link has expired",
    expiredLead: "Your application is still with us, together with your CV.",
    invalidTitle: "This link doesn’t work",
    invalidLead: "Open it again straight from the email. If you copy the address, check that you copied all of it.",
    optoutTitle: "Don’t want questions like this?",
    optoutLead: "We won’t send you requests for your terms again. Your application stays as it is.",
    optoutButton: "Stop these questions",
    optoutDoneTitle: "Done",
    optoutDone: "We won’t send you these questions again. Your application stays as it is.",
    privacy: "Privacy information",
    loading: "Loading…",
    kicker: "Application received",
    steps: ["Application", "CV", "Your terms"],
    expiredStep: "link expired",
    notice: "notice",
    weekForms: ["week", "weeks", "weeks"],
    monthForms: ["month", "months", "months"],
  },
} as const;

export function rateSummary(state: TermsState, lang: Lang): string | null {
  const amount = parseAmount(state.rateAmount);
  if (amount == null || Number.isNaN(amount)) return null;
  const t = TEXT[lang];
  const formatted = amount.toLocaleString(lang === "pl" ? "pl-PL" : "en-GB");
  const unit = state.rateUnit === "hour" ? t.perHour : t.perMonth;
  const extra =
    state.rateUnit === "month" && state.currency === "PLN"
      ? ` (≈ ${hourlyRate(amount, "month").toLocaleString(lang === "pl" ? "pl-PL" : "en-GB")} ${state.currency}/h)`
      : "";
  return `${formatted} ${state.currency} ${unit}${extra}`;
}

/** Polska odmiana po liczbie: 1 miesiąc, 2 miesiące, 5 miesięcy. */
export function pluralForm(n: number, forms: readonly [string, string, string] | readonly string[]): string {
  if (n === 1) return forms[0];
  const last = n % 10;
  const lastTwo = n % 100;
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return forms[1];
  return forms[2];
}

/** Ile z trzech pytań ma odpowiedź — wypełnia trzeci odcinek paska. */
export function answeredCount(state: TermsState): number {
  const amount = parseAmount(state.rateAmount);
  const rate = amount != null && !Number.isNaN(amount) && amount > 0;
  return [rate, state.modes.length > 0, state.startKind != null].filter(Boolean).length;
}
