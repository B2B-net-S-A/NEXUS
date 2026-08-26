import { AlertCircle, Banknote, RefreshCw, TrendingUp } from "lucide-react";

import { formatCurrency, formatDate } from "@/lib/utils";

export interface EurPlnRate {
  rate: number;
  effective_date: string;
  source: string;
  table: string;
  table_no?: string | null;
}

interface RateScheduleEntry {
  id: number;
  rate: number;
  effective_from: string;
}

export interface FinancialRatesContract {
  rate_candidate: number | null;
  rate_client: number | null;
  candidate_rate_schedule: RateScheduleEntry[];
  client_rate_schedule: RateScheduleEntry[];
  framework_rate: number | null;
  currency: string | null;
  rate_unit: "hourly" | "daily" | "monthly";
  billing_hours_per_month: number;
  margin: number | null;
  client_name: string | null;
  eur_pln_rate?: EurPlnRate | null;
}

const RATE_UNIT_SUFFIX: Record<FinancialRatesContract["rate_unit"], string> = {
  monthly: "/mies.",
  daily: "/dz.",
  hourly: "/h",
};

const RATE_UNIT_LABELS: Record<FinancialRatesContract["rate_unit"], string> = {
  monthly: "Miesięcznie",
  daily: "Dziennie",
  hourly: "Godzinowo",
};

const PLN_AMOUNT_FORMATTER = new Intl.NumberFormat("pl-PL", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const NBP_RATE_FORMATTER = new Intl.NumberFormat("pl-PL", {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

export function formatPlnAmount(amount: number): string {
  return `${PLN_AMOUNT_FORMATTER.format(amount)} zł`;
}

export function formatNbpRate(rate: number): string {
  return `${NBP_RATE_FORMATTER.format(rate)} zł`;
}

export function formatNbpDate(date: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!match) return formatDate(date);
  return `${match[3]}.${match[2]}.${match[1]}`;
}

function monthlyMultiplier(
  rateUnit: FinancialRatesContract["rate_unit"],
  billingHoursPerMonth: number,
): number {
  if (rateUnit === "daily") return 22;
  if (rateUnit === "hourly") return billingHoursPerMonth || 160;
  return 1;
}

function PlnConversion({
  amount,
  exchangeRate,
  unitSuffix = "",
  testId,
}: {
  amount: number | null;
  exchangeRate: EurPlnRate | null;
  unitSuffix?: string;
  testId: string;
}) {
  if (amount === null || exchangeRate === null) return null;

  return (
    <span
      className="whitespace-nowrap text-xs font-normal text-muted-foreground"
      data-testid={testId}
    >
      <span className="sr-only">W przybliżeniu </span>
      <span aria-hidden="true">≈</span> {formatPlnAmount(amount * exchangeRate.rate)}
      {unitSuffix}
    </span>
  );
}

export function FinancialRatesCard({ contract }: { contract: FinancialRatesContract }) {
  // The API redacts this field to null for non-finance callers and historical
  // rows can also predate the PLN default. The parent currently gates the card,
  // but keeping the component null-safe prevents a legacy row from crashing the
  // whole contract detail page.
  const currency = contract.currency || "PLN";
  const unitSuffix = RATE_UNIT_SUFFIX[contract.rate_unit];
  const monthlyMargin =
    contract.margin === null
      ? null
      : contract.margin *
        monthlyMultiplier(contract.rate_unit, contract.billing_hours_per_month);
  const marginPct =
    contract.rate_client && contract.rate_client > 0 && contract.margin !== null
      ? ((contract.margin / contract.rate_client) * 100).toFixed(1)
      : null;
  const exchangeRateCandidate = contract.eur_pln_rate ?? null;
  const exchangeRate =
    currency.toUpperCase() === "EUR" &&
    exchangeRateCandidate !== null &&
    Number.isFinite(exchangeRateCandidate.rate) &&
    exchangeRateCandidate.rate > 0
      ? exchangeRateCandidate
      : null;

  // Ostrzeżenie o przekroczeniu stawki z umowy ramowej — tylko dla klienta Nordea
  // (u innych klientów świeciłoby się wszędzie; sygnalizujemy wyłącznie dla Nordei).
  const isNordeaClient = (contract.client_name ?? "").toLowerCase().includes("nordea");
  const frameworkRateExceeded =
    isNordeaClient &&
    contract.framework_rate != null &&
    contract.rate_client != null &&
    contract.rate_client > contract.framework_rate;

  return (
    <div className="space-y-3">
      <div className="bg-card dark:bg-muted rounded-2xl shadow-xs p-6 space-y-3">
        <h2 className="text-sm font-semibold text-foreground dark:text-muted-foreground flex items-center gap-2">
          <Banknote className="w-4 h-4" /> Stawki finansowe
        </h2>
        <div className="text-xs text-muted-foreground dark:text-muted-foreground flex items-center justify-between">
          <span>Jednostka: {RATE_UNIT_LABELS[contract.rate_unit]}</span>
          {contract.rate_unit === "hourly" && (
            <span>{contract.billing_hours_per_month} h/mies.</span>
          )}
        </div>
        <div className="space-y-1 text-sm">
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground dark:text-muted-foreground">Klient</span>
            <span className="flex flex-wrap items-baseline justify-end gap-x-2 gap-y-0.5 text-right tabular-nums">
              <span className="whitespace-nowrap font-medium">
                {formatCurrency(contract.rate_client, currency)}
                <span className="text-xs opacity-70">{unitSuffix}</span>
              </span>
              <PlnConversion
                amount={contract.rate_client}
                exchangeRate={exchangeRate}
                unitSuffix={unitSuffix}
                testId="rate-client-pln"
              />
            </span>
          </div>
          {contract.client_rate_schedule.length > 1 && (
            <RateSchedule
              currency={currency}
              entries={contract.client_rate_schedule}
              unitSuffix={unitSuffix}
            />
          )}
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground dark:text-muted-foreground">Kandydat</span>
            <span className="flex flex-wrap items-baseline justify-end gap-x-2 gap-y-0.5 text-right tabular-nums">
              <span className="whitespace-nowrap font-medium">
                {formatCurrency(contract.rate_candidate, currency)}
                <span className="text-xs opacity-70">{unitSuffix}</span>
              </span>
              <PlnConversion
                amount={contract.rate_candidate}
                exchangeRate={exchangeRate}
                unitSuffix={unitSuffix}
                testId="rate-candidate-pln"
              />
            </span>
          </div>
          {contract.candidate_rate_schedule.length > 1 && (
            <RateSchedule
              currency={currency}
              entries={contract.candidate_rate_schedule}
              unitSuffix={unitSuffix}
            />
          )}
          <div className="flex justify-between gap-4 pt-2 border-t border-border dark:border-border">
            <span className="text-muted-foreground dark:text-muted-foreground flex items-center gap-1">
              <TrendingUp className="w-3.5 h-3.5" /> Marża
            </span>
            <span
              className={`flex flex-wrap items-baseline justify-end gap-x-2 gap-y-0.5 text-right tabular-nums ${
                (contract.margin ?? 0) > 0 ? "text-emerald-600" : "text-destructive"
              }`}
            >
              <span className="whitespace-nowrap font-bold">
                {formatCurrency(contract.margin, currency)}
                <span className="text-xs opacity-70">{unitSuffix}</span>
                {marginPct && <span className="ml-1 text-xs opacity-70">({marginPct}%)</span>}
              </span>
              <PlnConversion
                amount={contract.margin}
                exchangeRate={exchangeRate}
                unitSuffix={unitSuffix}
                testId="margin-pln"
              />
            </span>
          </div>
          {contract.rate_unit !== "monthly" && monthlyMargin !== null && (
            <div className="flex justify-between gap-4 pt-1 text-xs text-muted-foreground dark:text-muted-foreground">
              <span>Marża miesięcznie (≈)</span>
              <span className="flex flex-wrap items-baseline justify-end gap-x-2 gap-y-0.5 text-right tabular-nums">
                <span className="whitespace-nowrap">
                  {formatCurrency(monthlyMargin, currency)}
                </span>
                <PlnConversion
                  amount={monthlyMargin}
                  exchangeRate={exchangeRate}
                  testId="monthly-margin-pln"
                />
              </span>
            </div>
          )}
          {contract.framework_rate != null && (
            <div
              className={
                frameworkRateExceeded
                  ? "flex justify-between items-center gap-2 mt-2 rounded-lg bg-destructive/10 border border-destructive/20 px-2.5 py-2 text-xs text-destructive"
                  : "flex justify-between pt-2 mt-1 border-t border-border dark:border-border text-xs text-muted-foreground dark:text-muted-foreground"
              }
              title={
                frameworkRateExceeded
                  ? `Stawka klienta (${formatCurrency(contract.rate_client, currency)}${unitSuffix}) przekracza stawkę z umowy ramowej`
                  : undefined
              }
            >
              <span className="flex items-center gap-1.5">
                {frameworkRateExceeded && (
                  <AlertCircle className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                )}
                Z umowy ramowej
              </span>
              <span className={frameworkRateExceeded ? "font-semibold whitespace-nowrap" : ""}>
                {formatCurrency(contract.framework_rate, currency)}
                <span className="opacity-70">{unitSuffix}</span>
              </span>
            </div>
          )}
        </div>
      </div>
      {exchangeRate && (
        <div
          className="flex items-start gap-2 rounded-2xl bg-card px-6 py-3 text-[11px] leading-relaxed text-muted-foreground shadow-xs dark:bg-muted"
          data-testid="eur-pln-rate-note"
        >
          <RefreshCw className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
          <p>
            Kurs EUR/PLN z tabeli A NBP na dzień {formatNbpDate(exchangeRate.effective_date)}:
            1 € = {formatNbpRate(exchangeRate.rate)}
          </p>
        </div>
      )}
    </div>
  );
}

function RateSchedule({
  currency,
  entries,
  unitSuffix,
}: {
  currency: string;
  entries: RateScheduleEntry[];
  unitSuffix: string;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const sorted = [...entries].sort((a, b) => a.effective_from.localeCompare(b.effective_from));
  const past = sorted.filter((entry) => entry.effective_from <= today);
  const currentId = (past.length ? past[past.length - 1] : sorted[0]).id;

  return (
    <div className="pt-1 pl-2 border-l-2 border-border space-y-1">
      {sorted.map((entry) => (
        <div
          key={entry.id}
          className={`flex justify-between text-xs ${
            entry.id === currentId ? "text-foreground font-medium" : "text-muted-foreground"
          }`}
        >
          <span>
            od {formatDate(entry.effective_from)}
            {entry.id === currentId && <span className="ml-1 opacity-70">(aktualna)</span>}
          </span>
          <span>
            {formatCurrency(entry.rate, currency)}
            <span className="opacity-70">{unitSuffix}</span>
          </span>
        </div>
      ))}
    </div>
  );
}
