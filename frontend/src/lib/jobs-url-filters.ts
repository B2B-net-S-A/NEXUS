/**
 * Parsowanie filtrów listy ofert z URL-a.
 *
 * Osobny moduł, a nie funkcja lokalna w `JobsListV2`, żeby test wiązał się
 * z TĄ SAMĄ funkcją, której używa komponent. Test odtwarzający logikę
 * przestaje cokolwiek chronić dokładnie w chwili, gdy oryginał się zmieni —
 * sprawdza wtedy własną kopię.
 */

import { hasRole, type UserRole } from "@/store/auth";
import {
  PRIORITY_LEVELS,
  isPriorityLevel,
  type PriorityLevel,
} from "@/lib/request-priority";
import type { RequestStage } from "@/lib/request-stage";

/**
 * Role, które PROWADZĄ rekrutacje — dla nich lista startuje w „Moich".
 * Admin, Head of Recruitment, Finanse i viewer `user` nadzorują albo czytają
 * całość i zwykle nie mają własnych rekrutacji, więc startują w „Otwartych"
 * (decyzja właściciela, 24.09.2026 — do tego dnia „Wszystkie" razem
 * z ~4 tys. zamkniętych rekrutacji z Traffita).
 */
export const RECRUITMENT_RUNNING_ROLES: readonly UserRole[] = [
  "recruiter",
  "talent_community_manager",
  "delivery_lead",
];

type ScopeUser = Parameters<typeof hasRole>[0];

/**
 * Zakres listy: „Moje" (jestem Rekruterem albo Delivery Leadem, bez
 * zamkniętych), „Moja kategoria" (niezamknięte rekrutacje z mojej kategorii
 * kompetencji — do wzięcia, nie moje; 02.10.2026), „Otwarte" (wszystko poza
 * zamkniętymi — backend `open_only`) albo „Wszystkie" (cały rejestr).
 */
export type JobScope = "mine" | "category" | "open" | "all";

/** Kolejność przełącznika zakresu na ekranie. */
export const JOB_SCOPE_VALUES: readonly JobScope[] = [
  "mine",
  "category",
  "open",
  "all",
];

/**
 * Domyślny zakres użytkownika. Semantyka `hasRole` — konto wielorolowe
 * z KTÓRĄKOLWIEK z ról prowadzących dostaje „Moje". Brak użytkownika (store
 * jeszcze niezhydratowany) = „Otwarte".
 */
export function defaultScopeForUser(user: ScopeUser): JobScope {
  return hasRole(user, ...RECRUITMENT_RUNNING_ROLES) ? "mine" : "open";
}

/**
 * Jawny zakres z adresu (zawsze wygrywa z domyślnym roli):
 * `?mine=1` → „Moje", `?mycat=1` → „Moja kategoria", `?open=1` → „Otwarte",
 * `?mine=0` → „Wszystkie" (stare linki pulpitu `mine=0&status=published`
 * znaczą to samo co dotąd), brak → `null` = „obowiązuje domyślny roli".
 * `mine=0&open=1` → „Otwarte": `mine=0` mówiło dawniej tylko „nie moje",
 * a `open=1` zawęża dalej. Przy kilku kluczach naraz wygrywa węższy zakres.
 */
export function scopeOverrideFromUrl(params: URLSearchParams): JobScope | null {
  if (params.get("mine") === "1") return "mine";
  if (params.get("mycat") === "1") return "category";
  if (params.get("open") === "1") return "open";
  if (params.get("mine") === "0") return "all";
  return null;
}

/**
 * Czy zalogowana osoba ma kategorię kompetencji. Wiemy to z liczników listy
 * (`quick-counts.my_category`): liczba = ma, `null` albo brak pola = nie ma,
 * a dopóki liczniki nie przyszły — jeszcze nie wiadomo.
 */
export type CategoryScopeState = "available" | "unavailable" | "pending";

/**
 * Jawny wybór zakresu po uwzględnieniu kategorii osoby. „Moja kategoria"
 * istnieje tylko dla osoby z kategorią — `?mycat=1` u kogoś bez kategorii
 * (link od kolegi, zakładka sprzed zmiany składu kategorii) znaczy „bez
 * wyboru", czyli zakres domyślny roli. Póki nie wiadomo, wybór zostaje.
 */
export function effectiveScopeOverride(
  override: JobScope | null,
  category: CategoryScopeState,
): JobScope | null {
  return override === "category" && category === "unavailable" ? null : override;
}

/** Zakres faktycznie obowiązujący: jawny wybór albo domyślny roli. */
export function resolveScope(
  override: JobScope | null,
  user: ScopeUser,
): JobScope {
  return override ?? defaultScopeForUser(user);
}

/**
 * Parametry zakresu dla `GET /api/jobs` (i klucza zapytania). „Moje" to moje
 * NIEZAMKNIĘTE (decyzja Artura 26.09.2026) — zamknięte, w tym archiwum
 * z Traffita, widać wyłącznie we „Wszystkie"; liczniki `quick-counts`
 * zakresu „Moje" liczą tym samym warunkiem. „Moja kategoria" idzie SAMA
 * (`my_category=true`): serwer sam ogranicza ją do niezamkniętych.
 */
export function scopeQueryFlags(scope: JobScope): {
  mine: boolean;
  myCategory: boolean;
  openOnly: boolean;
} {
  return {
    mine: scope === "mine",
    myCategory: scope === "category",
    openOnly: scope === "mine" || scope === "open",
  };
}

// ── Typ, termin, sortowanie (M03-B01) ─────────────────────────────────────
//
// Do 09.2026 te trzy filtry żyły wyłącznie w `useState`: działały, ale URL
// zostawał gołym `/jobs`, więc F5, „Wstecz" z profilu rekrutacji i link
// wysłany koledze wracały do pełnej listy bez żadnego sygnału, że zawężenie
// przepadło. Teraz lista zapisuje je (razem ze statusem i „moimi") do URL-a,
// a przy montowaniu odtwarza.

export const JOB_DEADLINE_PRESETS = [
  "any",
  "overdue",
  "this_week",
  "next7",
  "next14",
  "next30",
  "has",
  "none",
  "range",
] as const;
export type JobDeadlinePreset = (typeof JOB_DEADLINE_PRESETS)[number];

/** Local-date ISO (YYYY-MM-DD) — bez przejścia przez UTC (off-by-one o północy). */
export function isoLocalDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Zakres „od–do" terminu (preset `range`); puste pole = brak granicy. */
export interface JobDeadlineRange {
  from?: string;
  to?: string;
}

export interface JobDeadlineQueryParams {
  deadline_from?: string;
  deadline_to?: string;
  has_deadline?: boolean;
}

/**
 * Preset terminu → parametry `GET /api/jobs`. Okna liczy PRZEGLĄDARKA
 * w lokalnej dacie użytkownika (ta sama para dat idzie do licznika
 * „Deadline ≤ 7 dni") — serwer w innej strefie potrafiłby wypaść o dzień.
 *
 * - „Po terminie" = termin najpóźniej wczoraj.
 * - „W tym tygodniu" = od dziś do niedzieli (minione dni tygodnia to już
 *   „po terminie").
 * - „Zakres dat" = granice wpisane przez użytkownika; niepoprawna data jest
 *   pomijana, a nie wysyłana (422).
 */
export function deadlineQueryParams(
  preset: JobDeadlinePreset,
  range: JobDeadlineRange = {},
  now: Date = new Date(),
): JobDeadlineQueryParams {
  if (preset === "any") return {};
  if (preset === "has") return { has_deadline: true };
  if (preset === "none") return { has_deadline: false };
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const addDays = (n: number) => {
    const d = new Date(today);
    d.setDate(d.getDate() + n);
    return d;
  };
  if (preset === "overdue") return { deadline_to: isoLocalDate(addDays(-1)) };
  if (preset === "this_week") {
    // getDay(): 0 = niedziela. Do niedzieli włącznie.
    const toSunday = (7 - today.getDay()) % 7;
    return {
      deadline_from: isoLocalDate(today),
      deadline_to: isoLocalDate(addDays(toSunday)),
    };
  }
  if (preset === "range") {
    const out: JobDeadlineQueryParams = {};
    if (range.from && ISO_DATE.test(range.from)) out.deadline_from = range.from;
    if (range.to && ISO_DATE.test(range.to)) out.deadline_to = range.to;
    return out;
  }
  const days = preset === "next7" ? 7 : preset === "next14" ? 14 : 30;
  return {
    deadline_from: isoLocalDate(today),
    deadline_to: isoLocalDate(addDays(days)),
  };
}

/** `?dl_from=2026-10-01&dl_to=2026-10-31` → zakres (tylko poprawne daty). */
export function initialDeadlineRangeFromUrl(
  params: URLSearchParams,
): JobDeadlineRange {
  const from = params.get("dl_from") ?? "";
  const to = params.get("dl_to") ?? "";
  return {
    from: ISO_DATE.test(from) ? from : undefined,
    to: ISO_DATE.test(to) ? to : undefined,
  };
}

// ── „Wysłanych do klienta" (osoby na „CV wysłane" albo dalej) ─────────────

export const JOB_SENT_VALUES = ["any", "none", "1", "3", "5"] as const;
export type JobSentFilterValue = (typeof JOB_SENT_VALUES)[number];

/** Filtr → `min_sent`/`max_sent` backendu (liczba OSÓB, nie wierszy). */
export function sentQueryParams(value: JobSentFilterValue): {
  min_sent?: number;
  max_sent?: number;
} {
  if (value === "any") return {};
  if (value === "none") return { max_sent: 0 };
  return { min_sent: Number(value) };
}

export const JOB_SORT_VALUES = [
  "attention",
  "newest",
  "oldest",
  "deadline",
] as const;
export type JobSortFilterValue = (typeof JOB_SORT_VALUES)[number];

/**
 * Domyślne sortowanie zależy od zakresu: w „Moich" pierwsze są rekrutacje,
 * w których ruch należy do rekrutera (`sort=attention`), w „Mojej kategorii",
 * „Otwartych" i „Wszystkich" — najnowsze. Wartość domyślna dla danego zakresu
 * NIE trafia do adresu, więc `/jobs` i `/jobs?mine=0` zostają czyste.
 */
export function defaultSortForScope(scope: JobScope): JobSortFilterValue {
  return scope === "mine" ? "attention" : "newest";
}

function pickFromUrl<T extends string>(
  params: URLSearchParams,
  key: string,
  allowed: readonly T[],
  fallback: T,
): T {
  const raw = params.get(key);
  // Wartość spoza kontraktu = wartość domyślna, nie 422 z backendu.
  return raw != null && (allowed as readonly string[]).includes(raw)
    ? (raw as T)
    : fallback;
}

/** `?deadline=none` → `"none"`; brak/nieznana wartość → `"any"`. */
export function initialDeadlineFromUrl(
  params: URLSearchParams,
): JobDeadlinePreset {
  return pickFromUrl(params, "deadline", JOB_DEADLINE_PRESETS, "any");
}

/**
 * `?sort=oldest` → `"oldest"`; brak/nieznana wartość → `null`, czyli
 * „sortowanie idzie za zakresem" (`defaultSortForScope`).
 */
export function sortOverrideFromUrl(
  params: URLSearchParams,
): JobSortFilterValue | null {
  const raw = params.get("sort");
  return raw != null && (JOB_SORT_VALUES as readonly string[]).includes(raw)
    ? (raw as JobSortFilterValue)
    : null;
}

// ── Pozostałe filtry (audyt 17.09.2026) ────────────────────────────────────
//
// Lista zapisywała do URL-a 5 z 14 filtrów. Wyszukiwarka, osoby, klienci,
// kategorie kompetencji, przełączniki i Priority Work ginęły po F5 i po
// „Wstecz" z profilu rekrutacji — bez sygnału, że zawężenie przepadło.

/** `?q=java` → `"java"`; brak → `""`. */
export function initialSearchFromUrl(params: URLSearchParams): string {
  return params.get("q") ?? "";
}

/**
 * `?client=3&client=7` → `[3, 7]`. Wartości niebędące dodatnią liczbą
 * całkowitą są odrzucane (ręcznie podrasowany URL = brak zawężenia, nie 422).
 */
export function initialIdsFromUrl(
  params: URLSearchParams,
  key: "client" | "cc" | "lead" | "who",
): number[] {
  const out: number[] = [];
  for (const raw of params.getAll(key)) {
    if (!/^\d+$/.test(raw.trim())) continue;
    const n = Number(raw);
    if (Number.isSafeInteger(n) && n > 0 && !out.includes(n)) out.push(n);
  }
  return out;
}

/**
 * Przełącznik zapisany jako `?klucz=1`; wszystko inne → `false`.
 * `open=1` NIE jest przełącznikiem — to zakres „Otwarte"
 * (`scopeOverrideFromUrl`).
 */
export function initialFlagFromUrl(params: URLSearchParams, key: "nobody"): boolean {
  return params.get(key) === "1";
}

/** `?sent=3` → `"3"`; brak/nieznana wartość → `"any"`. */
export function initialSentFromUrl(params: URLSearchParams): JobSentFilterValue {
  return pickFromUrl(params, "sent", JOB_SENT_VALUES, "any");
}

// ── Priorytet i data otwarcia (02.10.2026) ────────────────────────────────

/** Poziomy w kolejności ekranu (P1 · P2 · Przyjmujemy), bez powtórzeń. */
function orderedPriorityLevels(values: readonly string[]): PriorityLevel[] {
  return PRIORITY_LEVELS.filter((level) => values.includes(level));
}

/**
 * `?prio=p1,accepting` → `["p1", "accepting"]`. Klucz to `prio`, NIE
 * `priority`: `priority` należał do filtra Priority Work sprzed 25.09.2026
 * i jest zdejmowany z adresu (`MANAGED_KEYS`). Nieznana wartość odpada.
 */
export function initialPriorityLevelsFromUrl(
  params: URLSearchParams,
): PriorityLevel[] {
  const raw = params
    .getAll("prio")
    .flatMap((value) => value.split(","))
    .map((value) => value.trim())
    .filter(isPriorityLevel);
  return orderedPriorityLevels(raw);
}

/** Zakres „Data otwarcia" (od–do, obie daty włącznie); puste pole = brak granicy. */
export interface JobOpenedRange {
  from?: string;
  to?: string;
}

/** Granice, które przyjmuje serwer (`FILTER_DATE_MIN` / `FILTER_DATE_MAX`). */
const FILTER_DATE_MIN = "1900-01-01";
const FILTER_DATE_MAX = "2100-12-31";

/**
 * Data, którą można wysłać jako granicę zakresu: prawdziwy dzień kalendarza
 * z lat 1900–2100. Pole daty podczas wpisywania roku oddaje wartości pośrednie
 * („0002-10-01", „0020-10-01"…), a filtry tej listy działają od razu — bez
 * tej bramki każda cyfra roku kończyłaby się odpowiedzią 422.
 */
export function isFilterDate(value: string | null | undefined): value is string {
  if (!value || !ISO_DATE.test(value)) return false;
  if (value < FILTER_DATE_MIN || value > FILTER_DATE_MAX) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

/** `?op_from=2026-09-01&op_to=2026-09-30` → zakres (tylko poprawne daty). */
export function initialOpenedRangeFromUrl(params: URLSearchParams): JobOpenedRange {
  const from = params.get("op_from");
  const to = params.get("op_to");
  return {
    from: isFilterDate(from) ? from : undefined,
    to: isFilterDate(to) ? to : undefined,
  };
}

/** Data „od" późniejsza niż „do" — taki zakres nie zawęża niczego. */
export function openedRangeReversed(range: JobOpenedRange): boolean {
  return isFilterDate(range.from) && isFilterDate(range.to) && range.from > range.to;
}

/**
 * „Data otwarcia" → `opened_from` / `opened_to` listy. Doby liczy SERWER
 * w kalendarzu firmy (Europe/Warsaw), więc idą same daty. Odwrócony zakres
 * i niepełna data nie są wysyłane wcale: serwer odpowiada na nie 422, a to
 * tylko pomyłka w trakcie wpisywania drugiej daty — pasek prosi o poprawkę.
 */
export function openedQueryParams(range: JobOpenedRange = {}): {
  opened_from?: string;
  opened_to?: string;
} {
  if (openedRangeReversed(range)) return {};
  const out: { opened_from?: string; opened_to?: string } = {};
  if (isFilterDate(range.from)) out.opened_from = range.from;
  if (isFilterDate(range.to)) out.opened_to = range.to;
  return out;
}

export interface JobsListUrlState {
  scope: JobScope;
  /** Domyślny zakres ROLI (`defaultScopeForUser`) — jego nie zapisujemy. */
  defaultScope: JobScope;
  deadline: JobDeadlinePreset;
  /** Granice presetu `range` — zapisywane tylko przy nim. */
  deadlineRange?: JobDeadlineRange;
  sort: JobSortFilterValue;
  q?: string;
  /** Pigułki „Stan requestu” (`stage`, LUB). */
  stages?: readonly RequestStage[];
  clientIds?: readonly number[];
  ccIds?: readonly number[];
  deliveryLeadIds?: readonly number[];
  /** „Rekruter” — id osób (`who`). */
  workedBy?: readonly number[];
  /** „Bez rekrutera” (`nobody=1`). */
  nobodyWorking?: boolean;
  sent?: JobSentFilterValue;
  /** „Priorytet” (`prio=p1,accepting`). */
  priorityLevels?: readonly PriorityLevel[];
  /** „Data otwarcia” (`op_from` / `op_to`). */
  openedRange?: JobOpenedRange;
}

const SCOPE_URL: Record<JobScope, [key: string, value: string]> = {
  mine: ["mine", "1"],
  category: ["mycat", "1"],
  open: ["open", "1"],
  all: ["mine", "0"],
};

const MANAGED_KEYS = [
  "mine",
  "mycat",
  "open",
  "deadline",
  "dl_from",
  "dl_to",
  "sort",
  "q",
  "stage",
  "client",
  "cc",
  "lead",
  "who",
  "nobody",
  "sent",
  "prio",
  "op_from",
  "op_to",
  // Klucze kolumny filtrów sprzed 25.09.2026 (typ, status, osoba
  // odpowiedzialna, „Szybkie”, Priority Work, dwa rzędy statusu). Lista ich
  // już nie czyta — zapisane zakładki przeglądarki działają, a pierwszy zapis
  // filtrów zdejmuje je z adresu. `priority` to dawny filtr Priority Work —
  // priorytet rekrutacji ma własny klucz `prio`.
  "type",
  "status",
  "responsible",
  "sourcing",
  "active_search",
  "no_owner",
  "priority",
  "rs",
  "ws",
] as const;

/**
 * Stan filtrów → querystring (bez `?`). Wartości domyślne NIE są zapisywane,
 * więc lista bez zawężeń ma czysty adres `/jobs`. Parametry, którymi ta lista
 * nie zarządza, zostają nietknięte.
 *
 * Zakres trafia do adresu tylko wtedy, gdy różni się od domyślnego ROLI
 * (`mine=0`/`open=1` u rekrutera, `mine=1`/`mine=0` u admina). Sortowanie:
 * tylko gdy różni się od domyślnego dla bieżącego zakresu.
 */
export function encodeJobsListUrl(
  state: JobsListUrlState,
  current: URLSearchParams = new URLSearchParams(),
): string {
  const next = new URLSearchParams(current);
  for (const key of MANAGED_KEYS) next.delete(key);
  if (state.scope !== state.defaultScope) {
    const [key, value] = SCOPE_URL[state.scope];
    next.set(key, value);
  }
  if (state.deadline !== "any") next.set("deadline", state.deadline);
  if (state.deadline === "range") {
    const { from, to } = state.deadlineRange ?? {};
    if (from && ISO_DATE.test(from)) next.set("dl_from", from);
    if (to && ISO_DATE.test(to)) next.set("dl_to", to);
  }
  if (state.sort !== defaultSortForScope(state.scope)) next.set("sort", state.sort);
  const q = state.q?.trim();
  if (q) next.set("q", q);
  for (const stage of state.stages ?? []) next.append("stage", stage);
  for (const id of state.clientIds ?? []) next.append("client", String(id));
  for (const id of state.ccIds ?? []) next.append("cc", String(id));
  for (const id of state.deliveryLeadIds ?? []) next.append("lead", String(id));
  for (const id of state.workedBy ?? []) next.append("who", String(id));
  if (state.nobodyWorking) next.set("nobody", "1");
  if (state.sent && state.sent !== "any") next.set("sent", state.sent);
  const levels = orderedPriorityLevels(state.priorityLevels ?? []);
  if (levels.length > 0) next.set("prio", levels.join(","));
  const { from: openedFrom, to: openedTo } = state.openedRange ?? {};
  if (isFilterDate(openedFrom)) next.set("op_from", openedFrom);
  if (isFilterDate(openedTo)) next.set("op_to", openedTo);
  return next.toString();
}
