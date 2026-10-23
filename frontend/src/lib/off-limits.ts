/**
 * Off-limits przy dodaniu do rekrutacji (21.10.2026).
 *
 * Z firm, w których mamy aktywne zamówienie, nie wyciągamy ludzi — chyba że
 * osoba sama się do nas zgłosiła. Backend odpowiada 409
 * `off_limits_confirmation_required` z listą osób; interceptor w `lib/api.ts`
 * pyta oknem (`OffLimitsConfirmHost`) i ponawia TO SAMO żądanie z nagłówkiem
 * `X-Off-Limits-Confirmation`. Dzięki temu każda droga dodania (wyszukiwanie,
 * Talent Radar, propozycje, ruch karty, „Dodaj z CV”) pyta tak samo.
 */

export const OFF_LIMITS_CODE = "off_limits_confirmation_required";
export const OFF_LIMITS_HEADER = "X-Off-Limits-Confirmation";
export const OFF_LIMITS_SKIP = "skip";

export type OffLimitsHow =
  | "linkedin_inbound"
  | "job_ad"
  | "phone_or_email"
  | "sent_cv_before"
  | "referral"
  | "left_company";

/** Odpowiedź dla jednej osoby: sposób zgłoszenia albo „Nie, to my”. */
export type OffLimitsAnswer = OffLimitsHow | typeof OFF_LIMITS_SKIP;

/** Kolejność i etykiety z `HOW_LABELS` w `services/client_off_limits.py`. */
export const OFF_LIMITS_HOW_OPTIONS: ReadonlyArray<{
  value: OffLimitsHow;
  label: string;
}> = [
  { value: "linkedin_inbound", label: "Napisał(a) do nas na LinkedInie" },
  { value: "job_ad", label: "Zaaplikował(a) na ogłoszenie" },
  { value: "phone_or_email", label: "Zadzwonił(a) albo napisał(a) maila" },
  { value: "sent_cv_before", label: "Wcześniej sam(a) przysłał(a) CV" },
  { value: "referral", label: "Polecenie innej osoby" },
  { value: "left_company", label: "Już tam nie pracuje" },
];

export interface OffLimitsPerson {
  candidate_id: number;
  name: string;
  company: string;
  client_name: string;
  source: "linkedin" | "cv";
}

export type OffLimitsAnswers = Record<number, OffLimitsAnswer>;

/** Plakietka procesu z Tablicy (`entry_off_limits`). */
export interface OffLimitsBadge {
  client_name: string;
  company: string;
  how: OffLimitsHow;
  how_label: string;
  confirmed_by_id: number | null;
  confirmed_by_name: string | null;
  confirmed_at: string | null;
}

function isPerson(value: unknown): value is OffLimitsPerson {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.candidate_id === "number" &&
    typeof v.name === "string" &&
    typeof v.client_name === "string"
  );
}

/** Osoby do potwierdzenia z błędu 409 — `null`, gdy to inny błąd. */
export function offLimitsPeopleFrom(error: unknown): OffLimitsPerson[] | null {
  const response = (error as { response?: { status?: unknown; data?: unknown } } | null)
    ?.response;
  if (response?.status !== 409) return null;
  const detail = (response.data as { detail?: unknown } | null | undefined)?.detail;
  if (!detail || typeof detail !== "object") return null;
  const { code, candidates } = detail as { code?: unknown; candidates?: unknown };
  if (code !== OFF_LIMITS_CODE || !Array.isArray(candidates)) return null;
  const people = candidates.filter(isPerson).map((p) => ({
    ...p,
    company: typeof p.company === "string" ? p.company : p.client_name,
    source: p.source === "cv" ? ("cv" as const) : ("linkedin" as const),
  }));
  return people.length > 0 ? people : null;
}

/** Wartość nagłówka — `null`, gdy nikogo nie ma kogo dodać (same „Nie”).
 *  Partia z osobami spoza okna (`othersInRequest`) idzie dalej także przy
 *  samych „Nie”: serwer wpisze je do `skipped`, a resztę doda. */
export function offLimitsHeaderValue(
  answers: OffLimitsAnswers,
  othersInRequest = false,
): string | null {
  const entries = Object.entries(answers);
  if (entries.length === 0) return null;
  if (!othersInRequest && entries.every(([, answer]) => answer === OFF_LIMITS_SKIP)) {
    return null;
  }
  return JSON.stringify(Object.fromEntries(entries));
}

/** Czy żądanie partii (`candidate_ids` w ciele: proposals/bulk, przepięcie
 *  z podobnych rekrutacji) dodaje też osoby, o które okno nie pytało. */
export function offLimitsOthersInRequest(data: unknown, people: OffLimitsPerson[]): boolean {
  let body = data;
  if (typeof body === "string") {
    try {
      body = JSON.parse(body);
    } catch {
      return false;
    }
  }
  const ids = (body as { candidate_ids?: unknown } | null | undefined)?.candidate_ids;
  if (!Array.isArray(ids)) return false;
  const asked = new Set(people.map((p) => p.candidate_id));
  return ids.some((id) => typeof id === "number" && !asked.has(id));
}

/** Komunikat po „Nie, to my się odezwaliśmy”. */
export function offLimitsDeclinedMessage(people: OffLimitsPerson[]): string {
  if (people.length === 1) {
    const [person] = people;
    return `Nie dodano — ${person.name} pracuje w firmie ${person.client_name}, a stamtąd nie wyciągamy ludzi.`;
  }
  return `Nie dodano nikogo — te osoby pracują w firmach, z których nie wyciągamy ludzi.`;
}

/** Data potwierdzenia jak w panelu: „21.10”. */
export function offLimitsConfirmedDay(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "Europe/Warsaw",
  });
}

export interface OffLimitsAskOptions {
  /** Partia dodaje też inne osoby — „Nie” przy tych z okna ich nie zatrzymuje. */
  othersInRequest?: boolean;
}

type OffLimitsAsk = (
  people: OffLimitsPerson[],
  options?: OffLimitsAskOptions,
) => Promise<OffLimitsAnswers | null>;

let host: OffLimitsAsk | null = null;

/** Okno potwierdzenia rejestruje się tu raz (montowane w `AppShell`). */
export function registerOffLimitsHost(ask: OffLimitsAsk): () => void {
  host = ask;
  return () => {
    if (host === ask) host = null;
  };
}

/** Zapytaj człowieka; bez zamontowanego okna = brak potwierdzenia. */
export function askOffLimits(
  people: OffLimitsPerson[],
  options?: OffLimitsAskOptions,
): Promise<OffLimitsAnswers | null> {
  return host ? host(people, options) : Promise.resolve(null);
}
