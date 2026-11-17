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
  futureConsent: boolean | null;
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
  futureConsent: null,
};

export interface TermsPayload {
  rate?: { amount: string; unit: RateUnit; currency: Currency };
  modes: Mode[];
  onsite_days?: number;
  cities: string[];
  start?: { kind: StartKind; date?: string; value?: number; unit?: NoticeUnit };
  future_consent?: boolean;
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
  if (state.futureConsent != null) payload.future_consent = state.futureConsent;
  const empty =
    !payload.rate && !payload.modes.length && !payload.start && payload.future_consent == null;
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
    futureConsent: typeof answers.future_consent === "boolean" ? answers.future_consent : null,
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
    title: "Twoje warunki",
    lead: "Kilka pytań, ok. 2 minuty. Każde jest nieobowiązkowe — wypełnij tylko to, co chcesz.",
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
    consent: "Możecie proponować mi także inne rekrutacje (zgoda na 12 miesięcy).",
    submit: "Zapisz warunki",
    saving: "Zapisuję…",
    errors: {
      rate: "Podaj kwotę liczbą, np. 120 albo 18 500.",
      rate_range: "Ta stawka wychodzi poza 20–1000 zł za godzinę. Sprawdź kwotę i jednostkę.",
      start: "Uzupełnij datę albo okres wypowiedzenia (do 6 miesięcy).",
      empty: "Wypełnij choć jedno pytanie.",
      network: "Nie udało się zapisać. Sprawdź połączenie i spróbuj jeszcze raz — wpisane odpowiedzi zostają.",
    },
    savedTitle: "Dziękujemy, zapisane",
    savedLead: "Rekruter zobaczy Twoje warunki przy kolejnej propozycji. Możesz je poprawić tym samym linkiem do",
    edit: "Popraw odpowiedzi",
    summaryRate: "Stawka",
    summaryModes: "Tryb",
    summaryCities: "Miasta",
    summaryStart: "Start",
    expiredTitle: "Ten link wygasł",
    expiredLead: "Jeśli chcesz podać warunki, odpowiedz na maila od nas — trafi do rekrutera.",
    invalidTitle: "Ten link jest nieprawidłowy",
    invalidLead: "Sprawdź, czy skopiowałeś go z maila w całości.",
    optoutTitle: "Nie chcesz dostawać takich pytań?",
    optoutLead: "Nie wyślemy Ci już prośby o warunki. Twoja aplikacja zostaje bez zmian.",
    optoutButton: "Nie chcę dostawać takich pytań",
    optoutDone: "Gotowe. Nie wyślemy Ci już takich pytań.",
    privacy: "Informacje o przetwarzaniu danych",
    loading: "Wczytuję…",
  },
  en: {
    lang: "Polski",
    title: "Your terms",
    lead: "A few questions, about 2 minutes. Every one is optional — answer only what you want.",
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
    consent: "You may also offer me other positions (consent for 12 months).",
    submit: "Save my terms",
    saving: "Saving…",
    errors: {
      rate: "Enter the amount as a number, e.g. 120 or 18 500.",
      rate_range: "This rate is outside PLN 20–1000 per hour. Check the amount and the unit.",
      start: "Add the date or the notice period (up to 6 months).",
      empty: "Answer at least one question.",
      network: "Could not save. Check your connection and try again — your answers stay here.",
    },
    savedTitle: "Thank you, saved",
    savedLead: "The recruiter will see your terms with the next proposal. You can change them with the same link until",
    edit: "Change answers",
    summaryRate: "Rate",
    summaryModes: "Mode",
    summaryCities: "Cities",
    summaryStart: "Start",
    expiredTitle: "This link has expired",
    expiredLead: "If you want to share your terms, reply to our email — it goes to the recruiter.",
    invalidTitle: "This link is not valid",
    invalidLead: "Check that you copied the whole link from the email.",
    optoutTitle: "Don’t want questions like this?",
    optoutLead: "We won’t send you requests for your terms again. Your application stays as it is.",
    optoutButton: "Stop these questions",
    optoutDone: "Done. We won’t send you these questions again.",
    privacy: "Privacy information",
    loading: "Loading…",
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
