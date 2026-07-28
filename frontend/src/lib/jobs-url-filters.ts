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
