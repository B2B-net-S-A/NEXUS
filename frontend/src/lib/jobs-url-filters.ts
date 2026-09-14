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
 * `?mine=1` → true. Wszystko inne → false.
 *
 * Pulpit linkuje `mine=0` właśnie po to, żeby pokazać wszystkie oferty —
 * potraktowanie samej obecności parametru jako `true` odwróciłoby sens linku.
 */
export function initialMineFromUrl(params: URLSearchParams): boolean {
  return params.get("mine") === "1";
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

export const JOB_SORT_VALUES = ["newest", "oldest", "deadline"] as const;
export type JobSortFilterValue = (typeof JOB_SORT_VALUES)[number];

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

/** `?sort=oldest` → `"oldest"`; brak/nieznana wartość → `"newest"`. */
export function initialSortFromUrl(params: URLSearchParams): JobSortFilterValue {
  return pickFromUrl(params, "sort", JOB_SORT_VALUES, "newest");
}

export interface JobsListUrlState {
  status: readonly JobStatusFilterValue[];
  mine: boolean;
  type: JobTypeFilterValue;
  deadline: JobDeadlinePreset;
  sort: JobSortFilterValue;
}

const MANAGED_KEYS = ["status", "mine", "type", "deadline", "sort"] as const;

/**
 * Stan filtrów → querystring (bez `?`). Wartości domyślne NIE są zapisywane,
 * więc lista bez zawężeń ma czysty adres `/jobs`. Parametry, którymi ta lista
 * nie zarządza, zostają nietknięte.
 *
 * `mine=0` z linku pulpitu znika — znaczy to samo co brak parametru, a
 * zostawienie go obok stanu, który użytkownik mógł już zmienić, dałoby URL
 * mówiący co innego niż ekran.
 */
export function encodeJobsListUrl(
  state: JobsListUrlState,
  current: URLSearchParams = new URLSearchParams(),
): string {
  const next = new URLSearchParams(current);
  for (const key of MANAGED_KEYS) next.delete(key);
  for (const status of state.status) next.append("status", status);
  if (state.mine) next.set("mine", "1");
  if (state.type !== "all") next.set("type", state.type);
  if (state.deadline !== "any") next.set("deadline", state.deadline);
  if (state.sort !== "newest") next.set("sort", state.sort);
  return next.toString();
}
