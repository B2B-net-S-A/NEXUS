/**
 * „Twoje warunki” pod linkiem z maila z raportem kompetencji (`/raport/<token>`,
 * decyzje Artura 25.11.2026).
 *
 * Czyste funkcje: teksty, stan formularza z warunków, walidacja i ciało żądania.
 * Te same pola i reguły co formularz raportu na stronie b2bnetwork.ai
 * (`src/lib/application.ts` w b2bnetwork-www) i backend
 * (`ReportConditions` + `ConditionsSubmit` w `api/public_competence_report.py`).
 */

export type Contract = "b2b" | "uop" | "any";
export type WorkMode = "remote" | "hybrid" | "onsite";
export type Start = "now" | "1m" | "2-3m" | "browsing";

export const CONTRACTS: readonly Contract[] = ["b2b", "uop", "any"];
export const WORK_MODES: readonly WorkMode[] = ["remote", "hybrid", "onsite"];
export const STARTS: readonly Start[] = ["now", "1m", "2-3m", "browsing"];
export const RATE_MIN = 1;
export const RATE_MAX = 2000;
export const OFFICE_DAYS_MAX = 5;
export const CITIES_MAX = 10;
/** Te same miasta co na stronie (mapa na stronie głównej). */
export const CITY_OPTIONS = ["Warszawa", "Kraków", "Wrocław", "Gdańsk", "Poznań", "Łódź"];

/** Warunki tak, jak je zwraca i przyjmuje API (`ReportConditions`). */
export interface ReportConditions {
  rate: number;
  current_rate: number | null;
  contract: Contract;
  modes: WorkMode[];
  office_days_max: number | null;
  office_cities: string[];
  start: Start | null;
}

export interface ReportView {
  conditions: ReportConditions;
  opted_out: boolean;
  sent_at: string | null;
}

export interface ConditionsState {
  rate: string;
  currentRate: string;
  contract: Contract | null;
  modes: WorkMode[];
  /** "" = nie wybrano. */
  officeDays: string;
  cities: string[];
  start: Start | null;
}

export type ConditionsField = "rate" | "currentRate" | "contract" | "modes" | "officeDays" | "cities" | "start";
export type ConditionsErrors = Partial<Record<ConditionsField, string>>;

export const EMPTY_STATE: ConditionsState = {
  rate: "",
  currentRate: "",
  contract: null,
  modes: [],
  officeDays: "",
  cities: [],
  start: null,
};

export const TEXT = {
  title: "Twoje warunki",
  lead: "To warunki, z którymi jesteś w naszej bazie. Zmień je, jeśli coś się zmieniło.",
  sentOn: "Raport wysłaliśmy",
  loading: "Wczytujemy Twoje warunki…",
  rate: "Ile chcesz zarabiać",
  rateUnit: "zł/h netto, B2B",
  currentRate: "Ile zarabiasz teraz",
  optional: "(opcjonalnie)",
  currentUnit: "zł/h",
  contract: "Forma współpracy",
  contractOptions: { b2b: "B2B", uop: "Umowa o pracę", any: "Obojętnie" } satisfies Record<Contract, string>,
  modes: "Tryb pracy",
  modeOptions: { remote: "Zdalnie", hybrid: "Hybrydowo", onsite: "W biurze" } satisfies Record<WorkMode, string>,
  officeDays: "Najwięcej dni w biurze w tygodniu",
  cities: "Gdzie możesz dojeżdżać",
  otherCity: "+ inne miasto",
  otherCityLabel: "Inne miasto",
  otherCityPlaceholder: "np. Katowice",
  addCity: "Dodaj",
  start: "Od kiedy możesz zacząć",
  startOptions: {
    now: "Od zaraz",
    "1m": "Za miesiąc",
    "2-3m": "Za 2–3 miesiące",
    browsing: "Tylko sprawdzam",
  } satisfies Record<Start, string>,
  submit: "Zapisz warunki",
  saving: "Zapisujemy…",
  savedTitle: "Zapisaliśmy",
  savedLead:
    "Rekruter weźmie nowe warunki pod uwagę, a następny raport policzymy już według nich.",
  edit: "Zmień jeszcze raz",
  loadErrorTitle: "Coś poszło nie tak",
  loadErrorLead: "Nie udało się wczytać Twoich warunków. Odśwież stronę za chwilę.",
  invalidTitle: "Ten link nie działa",
  invalidLead:
    "Link jest nieprawidłowy albo wygasł. Sprawdź, czy skopiowałeś go w całości. Gdy wyślesz CV ze strony jeszcze raz, przyjdzie nowy.",
  optoutTitle: "Nie chcesz dostawać raportów?",
  optoutLead:
    "Po wypisie nie wyślemy Ci już raportu kompetencji. Twoje warunki zostają w bazie, dopóki ich nie zmienisz albo nie poprosisz o usunięcie danych.",
  optoutButton: "Wypisz mnie z raportów",
  optoutDoneTitle: "Wypisaliśmy Cię",
  optoutDone: "Nie wyślemy Ci już raportu kompetencji.",
  privacy: "Informacja o danych osobowych",
  errors: {
    rateRequired: "Wpisz stawkę, na jaką chcesz pracować.",
    rate: "Wpisz stawkę liczbą całkowitą od 1 do 2000, np. 150.",
    currentRate: "Wpisz stawkę liczbą całkowitą od 1 do 2000 albo zostaw pole puste.",
    contract: "Wybierz formę współpracy.",
    modes: "Wybierz co najmniej jeden tryb pracy.",
    officeDays: "Wybierz, ile najwięcej dni w tygodniu możesz być w biurze.",
    citiesRequired: "Wybierz co najmniej jedno miasto albo dopisz swoje.",
    citiesMax: "Wybierz najwyżej 10 miast.",
    start: "Wybierz, od kiedy możesz zacząć.",
    network: "Nie udało się zapisać. Sprawdź połączenie i spróbuj jeszcze raz.",
    optout: "Nie udało się wypisać. Sprawdź połączenie i spróbuj jeszcze raz.",
  },
} as const;

/** Dni w biurze i miasta mają sens tylko przy pracy hybrydowej albo w biurze. */
export const needsOffice = (modes: readonly WorkMode[]): boolean => modes.some((m) => m !== "remote");

const same = (a: string, b: string): boolean => a.toLocaleLowerCase("pl") === b.toLocaleLowerCase("pl");

/** Miasta bez pustych i powtórzeń (bez względu na wielkość liter), w kolejności wpisania. */
export function normalizeCities(cities: readonly string[]): string[] {
  const out: string[] = [];
  for (const raw of cities) {
    const city = raw.trim().replace(/\s+/g, " ");
    if (city && !out.some((c) => same(c, city))) out.push(city);
  }
  return out;
}

/** Dopisz miasto (z listy podpowiedzi bierze jej pisownię). */
export function addCity(cities: readonly string[], draft: string): string[] {
  const [city] = normalizeCities([draft]);
  if (!city || cities.length >= CITIES_MAX || cities.some((c) => same(c, city))) return [...cities];
  return [...cities, CITY_OPTIONS.find((o) => same(o, city)) ?? city];
}

export function toggleCity(cities: readonly string[], city: string): string[] {
  return cities.some((c) => same(c, city)) ? cities.filter((c) => !same(c, city)) : addCity(cities, city);
}

export function hasCity(cities: readonly string[], city: string): boolean {
  return cities.some((c) => same(c, city));
}

/** Stawka liczbą całkowitą 1–2000 zł/h, spacje ignorowane. Zła = null. */
export function parseWholeRate(value: string): number | null {
  const v = value.replace(/\s/g, "");
  if (!/^\d{1,4}$/.test(v)) return null;
  const n = Number(v);
  return n >= RATE_MIN && n <= RATE_MAX ? n : null;
}

export function stateFromConditions(c: ReportConditions): ConditionsState {
  return {
    rate: String(c.rate),
    currentRate: c.current_rate == null ? "" : String(c.current_rate),
    contract: c.contract,
    modes: WORK_MODES.filter((m) => c.modes.includes(m)),
    officeDays: c.office_days_max == null ? "" : String(c.office_days_max),
    cities: [...c.office_cities],
    start: c.start,
  };
}

export function toggleMode(modes: readonly WorkMode[], mode: WorkMode): WorkMode[] {
  const next = modes.includes(mode) ? modes.filter((m) => m !== mode) : [...modes, mode];
  return WORK_MODES.filter((m) => next.includes(m));
}

export function validate(s: ConditionsState): ConditionsErrors {
  const e = TEXT.errors;
  const errors: ConditionsErrors = {};
  if (!s.rate.trim()) errors.rate = e.rateRequired;
  else if (parseWholeRate(s.rate) === null) errors.rate = e.rate;
  if (s.currentRate.trim() && parseWholeRate(s.currentRate) === null) errors.currentRate = e.currentRate;
  if (!s.contract) errors.contract = e.contract;
  if (!s.modes.length) errors.modes = e.modes;
  if (needsOffice(s.modes)) {
    const days = s.officeDays.trim();
    if (!/^\d$/.test(days) || Number(days) > OFFICE_DAYS_MAX) errors.officeDays = e.officeDays;
    const cities = normalizeCities(s.cities);
    if (!cities.length) errors.cities = e.citiesRequired;
    else if (cities.length > CITIES_MAX) errors.cities = e.citiesMax;
  }
  if (!s.start) errors.start = e.start;
  return errors;
}

/** Stan → ciało `POST …/conditions` albo błędy pól. Przy samej pracy zdalnej bez dni i miast. */
export function buildPayload(s: ConditionsState): { payload: ReportConditions | null; errors: ConditionsErrors } {
  const errors = validate(s);
  if (Object.keys(errors).length) return { payload: null, errors };
  const office = needsOffice(s.modes);
  return {
    errors,
    payload: {
      rate: parseWholeRate(s.rate) as number,
      current_rate: s.currentRate.trim() ? parseWholeRate(s.currentRate) : null,
      contract: s.contract as Contract,
      modes: WORK_MODES.filter((m) => s.modes.includes(m)),
      office_days_max: office ? Number(s.officeDays) : null,
      office_cities: office ? normalizeCities(s.cities) : [],
      start: s.start,
    },
  };
}

/** Dzień wysyłki raportu, np. „25 listopada”. */
export function formatSentDay(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d, 12)).toLocaleDateString("pl-PL", {
    day: "numeric",
    month: "long",
    timeZone: "Europe/Warsaw",
  });
}
