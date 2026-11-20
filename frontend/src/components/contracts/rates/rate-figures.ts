// Trzy liczby karty „Stawki finansowe” (wariant A z 19.11.2026): „Klient płaci
// · Konsultant dostaje · Marża” z odpowiednikiem miesięcznym, i ocena stawki
// z umowy ramowej. Czyste funkcje — karta tylko je pokazuje.
import { HOURS_PER_MONTH, MD_PER_MONTH } from "@/lib/work-time";

export type ContractRateUnit = "hourly" | "daily" | "monthly";

/** Kwota w złotych: PLN bez zmian, EUR po kursie NBP; inna waluta albo brak kursu → `null`. */
export function amountInPln(amount: number | null, currency: string, eurPln: number | null): number | null {
  if (amount === null) return null;
  const code = currency.toUpperCase();
  if (code === "PLN") return amount;
  if (code === "EUR" && eurPln !== null) return amount * eurPln;
  return null;
}

/** Mnożnik stawki do miesiąca jak w backendzie (`Contract.monthly_rate`). */
export function monthlyMultiplier(rateUnit: ContractRateUnit, billingHoursPerMonth: number | null | undefined): number {
  if (rateUnit === "daily") return MD_PER_MONTH;
  if (rateUnit === "hourly") return billingHoursPerMonth || HOURS_PER_MONTH;
  return 1;
}

export interface RateFiguresInput {
  rateClient: number | null;
  rateCandidate: number | null;
  /** Marża z API (w walucie klienta); przy różnych walutach API daje `null`. */
  margin: number | null;
  clientCurrency: string;
  candidateCurrency: string;
  rateUnit: ContractRateUnit;
  billingHoursPerMonth: number | null | undefined;
  /** Kurs EUR/PLN z NBP, już sprawdzony (skończony, dodatni), albo `null`. */
  eurPln: number | null;
}

export interface RateFigures {
  sameCurrency: boolean;
  /** Godziny albo MD w miesiącu, przy których liczymy odpowiednik miesięczny. */
  multiplier: number;
  /** Stawka miesięczna sama jest miesięczna — bez drugiej linii. */
  showMonthly: boolean;
  clientMonthly: number | null;
  candidateMonthly: number | null;
  /** Marża w tej samej walucie; przy różnych walutach jej nie liczymy. */
  margin: number | null;
  marginPct: number | null;
  marginMonthly: number | null;
  /**
   * Różne waluty (Bosch: klient w EUR, konsultant w PLN): różnica w złotych po
   * kursie NBP — tylko orientacyjnie w zdaniu, nigdy jako marża.
   */
  approxPlnDifference: number | null;
  approxPlnDifferencePct: number | null;
  approxPlnDifferenceMonthly: number | null;
}

export function buildRateFigures(input: RateFiguresInput): RateFigures {
  const sameCurrency = input.clientCurrency.toUpperCase() === input.candidateCurrency.toUpperCase();
  const multiplier = monthlyMultiplier(input.rateUnit, input.billingHoursPerMonth);
  const showMonthly = input.rateUnit !== "monthly";
  const monthly = (value: number | null) => (showMonthly && value !== null ? value * multiplier : null);
  const margin = sameCurrency ? input.margin : null;
  const marginPct =
    margin !== null && input.rateClient !== null && input.rateClient > 0 ? (margin / input.rateClient) * 100 : null;
  const clientPln = amountInPln(input.rateClient, input.clientCurrency, input.eurPln);
  const candidatePln = amountInPln(input.rateCandidate, input.candidateCurrency, input.eurPln);
  const approx = !sameCurrency && clientPln !== null && candidatePln !== null ? clientPln - candidatePln : null;
  const approxPct = approx !== null && clientPln !== null && clientPln > 0 ? (approx / clientPln) * 100 : null;
  return {
    sameCurrency,
    multiplier,
    showMonthly,
    clientMonthly: monthly(input.rateClient),
    candidateMonthly: monthly(input.rateCandidate),
    margin,
    marginPct,
    marginMonthly: monthly(margin),
    approxPlnDifference: approx,
    approxPlnDifferencePct: approxPct,
    approxPlnDifferenceMonthly: monthly(approx),
  };
}

export type FrameworkVerdict = { kind: "over"; overBy: number | null } | { kind: "within" } | null;

/**
 * Stawka klienta wobec stawki z umowy ramowej — tylko u Nordei (u innych
 * klientów ostrzeżenie świeciłoby się wszędzie). Stawka ramowa jest w walucie
 * stawki kandydata, jak na karcie od początku. `null` = bez oceny (inny klient,
 * brak stawki albo kwot nie da się porównać).
 */
export function frameworkVerdict(input: {
  frameworkRate: number | null;
  rateClient: number | null;
  clientCurrency: string;
  frameworkCurrency: string;
  eurPln: number | null;
  clientName: string | null;
}): FrameworkVerdict {
  const isNordea = (input.clientName ?? "").toLowerCase().includes("nordea");
  if (!isNordea || input.frameworkRate === null || input.rateClient === null) return null;
  if (input.clientCurrency.toUpperCase() === input.frameworkCurrency.toUpperCase()) {
    return input.rateClient > input.frameworkRate
      ? { kind: "over", overBy: input.rateClient - input.frameworkRate }
      : { kind: "within" };
  }
  const clientPln = amountInPln(input.rateClient, input.clientCurrency, input.eurPln);
  const frameworkPln = amountInPln(input.frameworkRate, input.frameworkCurrency, input.eurPln);
  if (clientPln === null || frameworkPln === null) return null;
  return clientPln > frameworkPln ? { kind: "over", overBy: null } : { kind: "within" };
}
