/**
 * Marża na żywo w przeglądzie Delivery Leada (D9, 08.10.2026).
 *
 * DL wpisuje stawkę do klienta, a obok widzi marżę na godzinę i na miesiąc:
 * stawka do klienta − stawka kandydata, obie sprowadzone do PLN/h tą samą
 * regułą co odznaka „ponad budżet” (`rateToHourly`: dzień ÷ 8, miesiąc ÷ 168),
 * a miesiąc = 168 h (`lib/work-time.ts`). Inna waluta po którejkolwiek
 * stronie = „nie do porównania”, nigdy zmyślona liczba.
 */

import type { RateUnit } from "@/lib/api";
import { rateToHourly } from "@/lib/rate-to-hourly";
import { HOURS_PER_MONTH } from "@/lib/work-time";

export interface MarginInput {
  clientAmount: number | string | null | undefined;
  clientUnit: RateUnit;
  clientCurrency: string;
  candidateAmount: number | string | null | undefined;
  candidateUnit: RateUnit | null | undefined;
  candidateCurrency: string | null | undefined;
  /** Mediana marży PLN/h u klienta (tylko z dostępem do kwot). */
  clientMedianHourly?: number | null;
}

export type MarginResult =
  | { kind: "empty" }
  | { kind: "not_comparable"; reason: "currency" | "candidate_rate" }
  | {
      kind: "ok";
      clientHourly: number;
      candidateHourly: number;
      hourly: number;
      monthly: number;
      /** Udział marży w stawce do klienta (0–100). */
      percent: number;
      /** Marża poniżej mediany klienta (gdy znamy medianę). */
      belowMedian: boolean;
      /** Stawka do klienta niższa niż koszt — strata. */
      negative: boolean;
    };

const round2 = (value: number) => Math.round(value * 100) / 100;

export function parseRateInput(raw: string): number | null {
  const value = Number.parseFloat(raw.replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(value) && value > 0 ? value : null;
}

export function computeMargin(input: MarginInput): MarginResult {
  const rawClient =
    typeof input.clientAmount === "string" ? parseRateInput(input.clientAmount) : input.clientAmount;
  if (rawClient == null || !(rawClient > 0)) return { kind: "empty" };
  if ((input.clientCurrency || "PLN").toUpperCase() !== "PLN") {
    return { kind: "not_comparable", reason: "currency" };
  }
  const candidateHourly = rateToHourly(
    input.candidateAmount ?? null,
    input.candidateUnit ?? null,
    input.candidateCurrency ?? "PLN",
  );
  if (candidateHourly == null) {
    return {
      kind: "not_comparable",
      reason:
        input.candidateCurrency && input.candidateCurrency.toUpperCase() !== "PLN"
          ? "currency"
          : "candidate_rate",
    };
  }
  const clientHourly = rateToHourly(rawClient, input.clientUnit, "PLN");
  if (clientHourly == null) return { kind: "empty" };
  const hourly = round2(clientHourly - candidateHourly);
  const median = input.clientMedianHourly;
  return {
    kind: "ok",
    clientHourly,
    candidateHourly,
    hourly,
    monthly: Math.round(hourly * HOURS_PER_MONTH),
    percent: clientHourly > 0 ? Math.round((hourly / clientHourly) * 1000) / 10 : 0,
    belowMedian: median != null && hourly < median,
    negative: hourly < 0,
  };
}

export function formatPln(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toLocaleString("pl-PL", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })} zł`;
}

/** „140 zł/h” — kwota PLN/h z dwoma miejscami tylko przy groszach. */
export function formatHourly(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const digits = Number.isInteger(value) ? 0 : 2;
  return `${formatPln(value, digits)}/h`;
}
