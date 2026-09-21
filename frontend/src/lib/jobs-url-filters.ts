/**
 * Parsowanie filtrów listy ofert z URL-a.
 *
 * Osobny moduł, a nie funkcja lokalna w `JobsListV2`, żeby test wiązał się
 * z TĄ SAMĄ funkcją, której używa komponent. Test odtwarzający logikę
 * przestaje cokolwiek chronić dokładnie w chwili, gdy oryginał się zmieni —
 * sprawdza wtedy własną kopię.
 */

import { hasRole, type UserRole } from "@/store/auth";

export const JOB_STATUS_VALUES = ["draft", "published", "closed"] as const;

export type JobStatusFilterValue = (typeof JOB_STATUS_VALUES)[number];

const VALID: ReadonlySet<JobStatusFilterValue> = new Set(JOB_STATUS_VALUES);

function isJobStatus(value: string): value is JobStatusFilterValue {
  // Zawężenie po zbiorze typowanym na union, nie na `string` — inaczej strażnik
  // typu jest formalnie niepoprawny (TypeScript uwierzyłby mu na słowo dla
  // dowolnego stringa).
  return (VALID as ReadonlySet<string>).has(value);
}

/**
 * `?status=published&status=draft` → `["published", "draft"]`.
 *
 * Wartości spoza kontraktu są odrzucane, a nie przepuszczane do API — ręcznie
 * podrasowany URL ma dać pusty filtr, nie 422 z backendu.
 */
export function initialStatusFromUrl(
  params: URLSearchParams,
): JobStatusFilterValue[] {
  return params.getAll("status").filter(isJobStatus);
}

/**
 * Role, które PROWADZĄ rekrutacje — dla nich lista startuje w „Moich".
 * Admin, Head of Recruitment, Finanse i viewer `user` nadzorują albo czytają
 * całość i zwykle nie mają własnych rekrutacji, więc startują we „Wszystkich"
 * (decyzja właściciela, rekrutacja v3).
 */
export const RECRUITMENT_RUNNING_ROLES: readonly UserRole[] = [
  "recruiter",
  "sourcer",
  "tac",
  "talent_community_manager",
  "delivery_lead",
];

type ScopeUser = Parameters<typeof hasRole>[0];

/**
 * Domyślny zakres listy dla użytkownika: `true` = „Moje". Semantyka `hasRole`
 * — konto wielorolowe z KTÓRĄKOLWIEK z ról prowadzących dostaje „Moje".
 * Brak użytkownika (store jeszcze niezhydratowany) = „Wszystkie".
 */
export function defaultMineForUser(user: ScopeUser): boolean {
  return hasRole(user, ...RECRUITMENT_RUNNING_ROLES);
}

/**
 * Jawny zakres z adresu: `?mine=1` → „Moje", `?mine=0` → „Wszystkie",
 * brak/inna wartość → `null` („bez wyboru — obowiązuje domyślny roli").
 * Jawny parametr ZAWSZE wygrywa z domyślnym: pulpit linkuje `mine=0`, żeby
 * pokazać wszystkie rekrutacje, a link wysłany koledze ma otworzyć to samo.
 */
export function mineOverrideFromUrl(params: URLSearchParams): boolean | null {
  const raw = params.get("mine");
  if (raw === "1") return true;
  if (raw === "0") return false;
  return null;
}

/** Zakres faktycznie obowiązujący: jawny wybór albo domyślny roli. */
export function resolveMine(
  override: boolean | null,
  user: ScopeUser,
): boolean {
  return override ?? defaultMineForUser(user);
}

// ── Typ, termin, sortowanie (M03-B01) ─────────────────────────────────────
//
// Do 09.2026 te trzy filtry żyły wyłącznie w `useState`: działały, ale URL
// zostawał gołym `/jobs`, więc F5, „Wstecz" z profilu rekrutacji i link
// wysłany koledze wracały do pełnej listy bez żadnego sygnału, że zawężenie
// przepadło. Teraz lista zapisuje je (razem ze statusem i „moimi") do URL-a,
// a przy montowaniu odtwarza.

// Wartości `recruitment_type` z backendu (`RecruitmentType`). `all` = brak
// parametru — nigdy nie trafia do URL-a ani do API.
export const JOB_TYPE_VALUES = [
  "all",
  "body_leasing",
  "sales_project",
  "tender",
] as const;
export type JobTypeFilterValue = (typeof JOB_TYPE_VALUES)[number];

export const JOB_DEADLINE_PRESETS = [
  "any",
  "overdue",
  "next7",
  "next30",
  "has",
  "none",
] as const;
export type JobDeadlinePreset = (typeof JOB_DEADLINE_PRESETS)[number];

export const JOB_SORT_VALUES = [
  "attention",
  "newest",
  "oldest",
  "deadline",
] as const;
export type JobSortFilterValue = (typeof JOB_SORT_VALUES)[number];

/**
 * Domyślne sortowanie zależy od zakresu: w „Moich" pierwsze są rekrutacje,
 * w których ruch należy do rekrutera (`sort=attention`), w „Wszystkich" —
 * najnowsze, jak dotąd. Wartość domyślna dla danego zakresu NIE trafia do
 * adresu, więc `/jobs` i `/jobs?mine=0` zostają czyste.
 */
export function defaultSortForScope(mine: boolean): JobSortFilterValue {
  return mine ? "attention" : "newest";
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

/** `?type=tender` → `"tender"`; brak/nieznana wartość → `"all"`. */
export function initialTypeFromUrl(params: URLSearchParams): JobTypeFilterValue {
  return pickFromUrl(params, "type", JOB_TYPE_VALUES, "all");
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

export const JOB_PRIORITY_WORK_VALUES = [
  "any",
  "assigned",
  "carry_over",
  "either",
] as const;
export type JobPriorityWorkFilterValue = (typeof JOB_PRIORITY_WORK_VALUES)[number];

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
  key: "responsible" | "client" | "cc",
): number[] {
  const out: number[] = [];
  for (const raw of params.getAll(key)) {
    if (!/^\d+$/.test(raw.trim())) continue;
    const n = Number(raw);
    if (Number.isSafeInteger(n) && n > 0 && !out.includes(n)) out.push(n);
  }
  return out;
}

/** Przełącznik zapisany jako `?klucz=1`; wszystko inne → `false`. */
export function initialFlagFromUrl(
  params: URLSearchParams,
  key: "sourcing" | "active_search" | "open" | "no_owner",
): boolean {
  return params.get(key) === "1";
}

/** `?priority=carry_over` → `"carry_over"`; brak/nieznana → `"any"`. */
export function initialPriorityWorkFromUrl(
  params: URLSearchParams,
): JobPriorityWorkFilterValue {
  return pickFromUrl(params, "priority", JOB_PRIORITY_WORK_VALUES, "any");
}

export interface JobsListUrlState {
  status: readonly JobStatusFilterValue[];
  mine: boolean;
  /** Domyślny zakres ROLI (`defaultMineForUser`) — jego nie zapisujemy. */
  defaultMine: boolean;
  type: JobTypeFilterValue;
  deadline: JobDeadlinePreset;
  sort: JobSortFilterValue;
  q?: string;
  responsibleIds?: readonly number[];
  clientIds?: readonly number[];
  ccIds?: readonly number[];
  needsSourcing?: boolean;
  activeInSearch?: boolean;
  openOnly?: boolean;
  noOwnerOnly?: boolean;
  priorityWork?: JobPriorityWorkFilterValue;
}

const MANAGED_KEYS = [
  "status",
  "mine",
  "type",
  "deadline",
  "sort",
  "q",
  "responsible",
  "client",
  "cc",
  "sourcing",
  "active_search",
  "open",
  "no_owner",
  "priority",
] as const;

/**
 * Stan filtrów → querystring (bez `?`). Wartości domyślne NIE są zapisywane,
 * więc lista bez zawężeń ma czysty adres `/jobs`. Parametry, którymi ta lista
 * nie zarządza, zostają nietknięte.
 *
 * Zakres trafia do adresu tylko wtedy, gdy różni się od domyślnego ROLI
 * (`mine=0` u rekrutera, `mine=1` u admina). Sortowanie: tylko gdy różni się
 * od domyślnego dla bieżącego zakresu.
 */
export function encodeJobsListUrl(
  state: JobsListUrlState,
  current: URLSearchParams = new URLSearchParams(),
): string {
  const next = new URLSearchParams(current);
  for (const key of MANAGED_KEYS) next.delete(key);
  for (const status of state.status) next.append("status", status);
  if (state.mine !== state.defaultMine) next.set("mine", state.mine ? "1" : "0");
  if (state.type !== "all") next.set("type", state.type);
  if (state.deadline !== "any") next.set("deadline", state.deadline);
  if (state.sort !== defaultSortForScope(state.mine)) next.set("sort", state.sort);
  const q = state.q?.trim();
  if (q) next.set("q", q);
  for (const id of state.responsibleIds ?? []) next.append("responsible", String(id));
  for (const id of state.clientIds ?? []) next.append("client", String(id));
  for (const id of state.ccIds ?? []) next.append("cc", String(id));
  if (state.needsSourcing) next.set("sourcing", "1");
  if (state.activeInSearch) next.set("active_search", "1");
  if (state.openOnly) next.set("open", "1");
  if (state.noOwnerOnly) next.set("no_owner", "1");
  if (state.priorityWork && state.priorityWork !== "any") {
    next.set("priority", state.priorityWork);
  }
  return next.toString();
}
