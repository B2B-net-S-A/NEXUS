/**
 * Czy stawka w zamówieniu albo umowie zgadza się ze stawką z rekrutacji (D7).
 *
 * Stawka do klienta, którą Delivery Lead zapisał przy wysyłce CV, jest punktem
 * odniesienia dla przychodu w zamówieniu klienta; stawka kandydata od rekrutera
 * — dla kosztu w zamówieniu i w umowie B2B. Różnica NIGDY nie blokuje zapisu
 * (decyzja Artura 07.10.2026): formularz pokazuje notkę, zamówienie z maila
 * idzie do sprawdzenia.
 *
 * Reguła: godzina; dzień i MD = 8 godzin; miesiąc tylko z miesiącem; waluta
 * inna niż PLN = nieporównywalne; tolerancja 0,01 zł/h.
 *
 * Lustro backendu: `backend/app/services/recruitment_rate_check.py`, wspólne
 * przypadki `lib/__fixtures__/recruitment-rate-check-cases.json`.
 */

import { HOURS_PER_MD } from "@/lib/work-time";

export type RateCheckResult = "equal" | "differs" | "not_comparable";

type Amount = number | string | null | undefined;

const TOLERANCE = 0.01;

const UNIT_ALIASES: Record<string, "hour" | "day" | "month"> = {
  hour: "hour",
  hourly: "hour",
  h: "hour",
  day: "day",
  daily: "day",
  md: "day",
  month: "month",
  monthly: "month",
};

export function normalizeRateUnit(
  unit: string | null | undefined,
): "hour" | "day" | "month" | null {
  if (!unit) return null;
  return UNIT_ALIASES[unit.trim().toLowerCase()] ?? null;
}

function toNumber(value: Amount): number | null {
  if (value == null || value === "") return null;
  const numeric =
    typeof value === "number"
      ? value
      : Number.parseFloat(String(value).replace(",", ".").trim());
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  return numeric;
}

function isPln(currency: string | null | undefined): boolean {
  return (currency ?? "PLN").trim().toUpperCase() === "PLN";
}

/** `["hour", zł/h]` albo `["month", zł/mc]`; `null` = nieporównywalne. */
export function comparableAmount(
  value: Amount,
  unit: string | null | undefined,
  currency: string | null | undefined = "PLN",
): ["hour" | "month", number] | null {
  const numeric = toNumber(value);
  const kind = normalizeRateUnit(unit);
  if (numeric == null || kind == null || !isPln(currency)) return null;
  if (kind === "day") return ["hour", numeric / HOURS_PER_MD];
  return [kind, numeric];
}

/** Stawka w PLN/h (dzień i MD ÷ 8); miesiąc i inna waluta = `null`. */
export function hourlyPln(
  value: Amount,
  unit: string | null | undefined,
  currency: string | null | undefined = "PLN",
): number | null {
  const amount = comparableAmount(value, unit, currency);
  if (amount == null || amount[0] !== "hour") return null;
  return amount[1];
}

export function compareRates(
  reference: { value: Amount; unit?: string | null; currency?: string | null },
  actual: { value: Amount; unit?: string | null; currency?: string | null },
): RateCheckResult {
  const ref = comparableAmount(reference.value, reference.unit, reference.currency);
  const act = comparableAmount(actual.value, actual.unit, actual.currency);
  if (ref == null || act == null || ref[0] !== act[0]) return "not_comparable";
  // Grosze po zaokrągleniu — float nie może zamienić 0,01 w 0,0100000001.
  const diff = Math.abs(Math.round(ref[1] * 10000) - Math.round(act[1] * 10000));
  return diff <= TOLERANCE * 10000 ? "equal" : "differs";
}

const UNIT_LABEL: Record<"hour" | "day" | "month", string> = {
  hour: "zł/h",
  day: "zł/MD",
  month: "zł/mc",
};

/** „165 zł/h”, „1320,50 zł/MD”. */
export function formatRecruitmentRate(
  value: Amount,
  unit: string | null | undefined,
): string {
  const numeric = toNumber(value);
  if (numeric == null) return "—";
  const rounded = Math.round(numeric * 100) / 100;
  const text = Number.isInteger(rounded)
    ? String(rounded)
    : rounded.toFixed(2).replace(".", ",");
  const kind = normalizeRateUnit(unit);
  return kind ? `${text} ${UNIT_LABEL[kind]}` : text;
}
