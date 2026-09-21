/**
 * Parsowanie filtrów listy ofert z URL-a.
 *
 * Osobny moduł, a nie funkcja lokalna w `JobsListV2`, żeby test wiązał się
 * z TĄ SAMĄ funkcją, której używa komponent. Test odtwarzający logikę
 * przestaje cokolwiek chronić dokładnie w chwili, gdy oryginał się zmieni —
 * sprawdza wtedy własną kopię.
 */

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
 * Zakres listy: „Moje" jest DOMYŚLNE (rekrutacja v3) — adres bez parametru
 * `mine` otwiera rekrutacje zalogowanej osoby. `?mine=0` to jawne „Wszystkie"
 * i musi dać się zapisać w adresie, inaczej F5 albo link wysłany koledze
 * wracałby po cichu do „Moich". `?mine=1` (stare linki) nadal znaczy „Moje".
 *
 * Pulpit linkuje `mine=0` właśnie po to, żeby pokazać wszystkie rekrutacje —
 * potraktowanie samej obecności parametru jako `true` odwróciłoby sens linku.
 */
export function initialMineFromUrl(params: URLSearchParams): boolean {
  return params.get("mine") !== "0";
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
 * `?sort=oldest` → `"oldest"`; brak/nieznana wartość → domyślne sortowanie
 * zakresu odczytanego z TEGO SAMEGO adresu (`defaultSortForScope`).
 */
export function initialSortFromUrl(params: URLSearchParams): JobSortFilterValue {
  return pickFromUrl(
    params,
    "sort",
    JOB_SORT_VALUES,
    defaultSortForScope(initialMineFromUrl(params)),
  );
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
 * Zakres: „Moje" jest domyślne, więc w adresie zapisujemy wyłącznie jawne
 * „Wszystkie" (`mine=0`). Sortowanie: tylko gdy różni się od domyślnego dla
 * bieżącego zakresu.
 */
export function encodeJobsListUrl(
  state: JobsListUrlState,
  current: URLSearchParams = new URLSearchParams(),
): string {
  const next = new URLSearchParams(current);
  for (const key of MANAGED_KEYS) next.delete(key);
  for (const status of state.status) next.append("status", status);
  if (!state.mine) next.set("mine", "0");
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
