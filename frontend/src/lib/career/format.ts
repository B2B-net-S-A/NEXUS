/**
 * Teksty strony kariery wyprowadzane z danych API (czyste funkcje, testowalne).
 *
 * Motyw terminala pisze wartości małymi literami w nawiasach: `[warszawa]`,
 * `[hybryda · 2 dni]`. Pusta wartość = wiersz znika (nie „[—]"), bo pusty
 * parametr na stronie publicznej czyta się jak błąd, nie jak brak informacji.
 */
import type { CareerJobParams, CareerRecruiterJob, RemotePolicy } from "./api";

const REMOTE_LABEL: Record<RemotePolicy, string> = {
  remote: "zdalnie",
  hybrid: "hybryda",
  onsite: "stacjonarnie",
};

export function remoteLabel(policy: RemotePolicy | null | undefined): string | null {
  return policy ? (REMOTE_LABEL[policy] ?? null) : null;
}

function daysLabel(days: number): string {
  if (days === 1) return "1 dzień";
  return `${days} dni`;
}

export interface ParamRow {
  key: string;
  label: string;
  value: string;
}

function lower(value: string | null | undefined): string | null {
  const v = value?.trim();
  return v ? v.toLocaleLowerCase("pl-PL") : null;
}

/** „warszawa · hybryda” / „zdalnie” — wiersz listy rekrutacji. */
export function jobLocationLabel(
  job: Pick<CareerRecruiterJob, "city" | "remote_policy">,
): string {
  const city = job.city?.trim().toLocaleLowerCase("pl-PL");
  const mode = remoteLabel(job.remote_policy);
  if (job.remote_policy === "remote") return mode ?? "";
  return [city, mode].filter(Boolean).join(" · ");
}

/** Wiersze panelu // PARAMETRY. */
export function paramRows(params: CareerJobParams | null | undefined): ParamRow[] {
  if (!params) return [];
  const rows: ParamRow[] = [];
  const city = lower(params.city);
  if (city) rows.push({ key: "city", label: "lokalizacja", value: city });
  const mode = remoteLabel(params.remote_policy);
  if (mode) {
    const hybrid = params.remote_policy === "hybrid";
    const days =
      hybrid && params.onsite_days_per_month
        ? ` · ${daysLabel(params.onsite_days_per_month)} w miesiącu`
        : hybrid && params.onsite_days_per_week
          ? ` · ${daysLabel(params.onsite_days_per_week)}`
          : "";
    rows.push({ key: "mode", label: "tryb", value: `${mode}${days}` });
  }
  const seniority = lower(params.seniority);
  if (seniority) rows.push({ key: "seniority", label: "poziom", value: seniority });
  const contract = lower(params.contract);
  if (contract) rows.push({ key: "contract", label: "umowa", value: contract });
  const start = [params.start?.trim(), lower(params.duration)].filter(Boolean).join(" · ");
  if (start) rows.push({ key: "start", label: "start", value: start });
  return rows;
}

/** Krótka linia parametrów: „warszawa · hybryda · b2b · senior" (OG, mobile). */
export function paramsSummary(params: CareerJobParams | null | undefined): string {
  if (!params) return "";
  return [
    lower(params.city),
    remoteLabel(params.remote_policy),
    lower(params.contract),
    lower(params.seniority),
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Nazwa wymagania jako „identyfikator": „Java 17+ i Spring Boot" → java_17_i_spring_boot. */
export function requirementHandle(name: string): string {
  const handle = name
    .toLocaleLowerCase("pl-PL")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ł/g, "l")
    .replace(/[^a-z0-9+#.]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return handle || name;
}

/** Akapity opisu: podwójny znak nowej linii dzieli akapity. */
export function aboutParagraphs(about: string | null | undefined): string[] {
  if (!about) return [];
  return about
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
}

/** Odmiana imienia do „rozmowa z {kim}" — tylko najczęstsze końcówki, reszta bez zmian. */
export function instrumentalName(firstName: string): string {
  const name = firstName.trim();
  if (!name) return "rekruterem";
  if (/a$/i.test(name)) return `${name.slice(0, -1)}ą`; // Marta → Martą
  if (/ek$/i.test(name)) return `${name.slice(0, -2)}kiem`; // Marek → Markiem
  if (/[kg]$/i.test(name)) return `${name}iem`; // Jacek → (ek wyżej), Oleg → Olegiem
  return `${name}em`; // Tomasz → Tomaszem, Jan → Janem
}

/** „do Marty" / „do Tomasza". */
export function genitiveName(firstName: string): string {
  const name = firstName.trim();
  if (!name) return "rekrutera";
  if (/[kg]a$/i.test(name)) return `${name.slice(0, -1)}i`; // Olga → Olgi
  if (/ia$/i.test(name)) return `${name.slice(0, -1)}`; // Kasia → Kasi
  if (/ja$/i.test(name)) return `${name.slice(0, -2)}i`; // Maja → Mai
  if (/la$/i.test(name)) return `${name.slice(0, -1)}i`; // Ola → Oli
  if (/a$/i.test(name)) return `${name.slice(0, -1)}y`; // Marta → Marty
  if (/ek$/i.test(name)) return `${name.slice(0, -2)}ka`; // Marek → Marka
  return `${name}a`; // Tomasz → Tomasza
}

