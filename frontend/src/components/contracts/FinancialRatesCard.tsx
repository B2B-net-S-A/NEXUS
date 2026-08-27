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
  rate_client_currency?: string | null;
  rate_candidate_currency?: string | null;
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

function amountInPln(
  amount: number | null,
  currency: string,
  eurPlnRate: EurPlnRate | null,
): number | null {
  if (amount === null) return null;
  const normalizedCurrency = currency.toUpperCase();
  if (normalizedCurrency === "PLN") return amount;
  if (normalizedCurrency === "EUR" && eurPlnRate !== null) {
    return amount * eurPlnRate.rate;
  }
  return null;
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
  const legacyCurrency = contract.currency || "PLN";
  const clientCurrency = contract.rate_client_currency || legacyCurrency;
  const candidateCurrency = contract.rate_candidate_currency || legacyCurrency;
  const normalizedClientCurrency = clientCurrency.toUpperCase();
  const normalizedCandidateCurrency = candidateCurrency.toUpperCase();
  const unitSuffix = RATE_UNIT_SUFFIX[contract.rate_unit];
  const exchangeRateCandidate = contract.eur_pln_rate ?? null;
  const eurPlnRate =
    exchangeRateCandidate !== null &&
    Number.isFinite(exchangeRateCandidate.rate) &&
    exchangeRateCandidate.rate > 0
      ? exchangeRateCandidate
      : null;
  const clientExchangeRate = normalizedClientCurrency === "EUR" ? eurPlnRate : null;
  const candidateExchangeRate =
    normalizedCandidateCurrency === "EUR" ? eurPlnRate : null;
  const currenciesDiffer = normalizedClientCurrency !== normalizedCandidateCurrency;
  const clientRatePln = amountInPln(
    contract.rate_client,
    clientCurrency,
    eurPlnRate,
  );
  const candidateRatePln = amountInPln(
    contract.rate_candidate,
    candidateCurrency,
    eurPlnRate,
  );
  // The API intentionally returns margin=null for unlike currencies. Calculate
  // it only when both rates can be compared in PLN; unsupported currencies stay
  // empty instead of producing a plausible-looking but false value.
  const mixedCurrencyMargin =
    currenciesDiffer && clientRatePln !== null && candidateRatePln !== null
      ? clientRatePln - candidateRatePln
      : null;
  const displayedMargin = currenciesDiffer ? mixedCurrencyMargin : contract.margin;
  const marginCurrency = currenciesDiffer ? "PLN" : clientCurrency;
  const marginExchangeRate =
    !currenciesDiffer && normalizedClientCurrency === "EUR" ? eurPlnRate : null;
  const monthlyMargin =
    displayedMargin === null
      ? null
      : displayedMargin *
        monthlyMultiplier(contract.rate_unit, contract.billing_hours_per_month);
  const comparableClientRate = currenciesDiffer ? clientRatePln : contract.rate_client;
  const marginPct =
    comparableClientRate && comparableClientRate > 0 && displayedMargin !== null
      ? ((displayedMargin / comparableClientRate) * 100).toFixed(1)
      : null;

  // Ostrzeżenie o przekroczeniu stawki z umowy ramowej — tylko dla klienta Nordea
  // (u innych klientów świeciłoby się wszędzie; sygnalizujemy wyłącznie dla Nordei).
  const isNordeaClient = (contract.client_name ?? "").toLowerCase().includes("nordea");
  const frameworkRatePln = amountInPln(
    contract.framework_rate,
    candidateCurrency,
    eurPlnRate,
  );
  const frameworkRateExceeded =
    isNordeaClient &&
    contract.framework_rate != null &&
    contract.rate_client != null &&
    (normalizedClientCurrency === normalizedCandidateCurrency
      ? contract.rate_client > contract.framework_rate
      : clientRatePln !== null &&
        frameworkRatePln !== null &&
        clientRatePln > frameworkRatePln);

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
                {formatCurrency(contract.rate_client, clientCurrency)}
                <span className="text-xs opacity-70">{unitSuffix}</span>
              </span>
              <PlnConversion
                amount={contract.rate_client}
                exchangeRate={clientExchangeRate}
                unitSuffix={unitSuffix}
                testId="rate-client-pln"
              />
            </span>
          </div>
          {contract.client_rate_schedule.length > 1 && (
            <RateSchedule
              currency={clientCurrency}
              entries={contract.client_rate_schedule}
              unitSuffix={unitSuffix}
              exchangeRate={clientExchangeRate}
              testIdPrefix="client-rate-schedule"
            />
          )}
          <div className="flex justify-between gap-4">
            <span className="text-muted-foreground dark:text-muted-foreground">Kandydat</span>
            <span className="flex flex-wrap items-baseline justify-end gap-x-2 gap-y-0.5 text-right tabular-nums">
              <span className="whitespace-nowrap font-medium">
                {formatCurrency(contract.rate_candidate, candidateCurrency)}
                <span className="text-xs opacity-70">{unitSuffix}</span>
              </span>
              <PlnConversion
                amount={contract.rate_candidate}
                exchangeRate={candidateExchangeRate}
                unitSuffix={unitSuffix}
                testId="rate-candidate-pln"
              />
            </span>
          </div>
          {contract.candidate_rate_schedule.length > 1 && (
            <RateSchedule
              currency={candidateCurrency}
              entries={contract.candidate_rate_schedule}
              unitSuffix={unitSuffix}
              exchangeRate={candidateExchangeRate}
              testIdPrefix="candidate-rate-schedule"
            />
          )}
          <div className="flex justify-between gap-4 pt-2 border-t border-border dark:border-border">
            <span className="text-muted-foreground dark:text-muted-foreground flex items-center gap-1">
              <TrendingUp className="w-3.5 h-3.5" /> Marża
            </span>
            <span
              className={`flex flex-wrap items-baseline justify-end gap-x-2 gap-y-0.5 text-right tabular-nums ${
                displayedMargin === null
                  ? "text-muted-foreground"
                  : displayedMargin > 0
                    ? "text-emerald-600"
                    : "text-destructive"
              }`}
            >
              <span className="whitespace-nowrap font-bold">
                {displayedMargin === null
                  ? "—"
                  : formatCurrency(displayedMargin, marginCurrency)}
                {displayedMargin !== null && (
                  <span className="text-xs opacity-70">{unitSuffix}</span>
                )}
                {marginPct && <span className="ml-1 text-xs opacity-70">({marginPct}%)</span>}
              </span>
              <PlnConversion
                amount={displayedMargin}
                exchangeRate={marginExchangeRate}
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
                  {formatCurrency(monthlyMargin, marginCurrency)}
                </span>
                <PlnConversion
                  amount={monthlyMargin}
                  exchangeRate={marginExchangeRate}
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
                  ? `Stawka klienta (${formatCurrency(contract.rate_client, clientCurrency)}${unitSuffix}) przekracza stawkę z umowy ramowej`
                  : undefined
              }
            >
              <span className="flex items-center gap-1.5">
                {frameworkRateExceeded && (
                  <AlertCircle className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                )}
                Z umowy ramowej
              </span>
              <span
                className={`flex flex-wrap items-baseline justify-end gap-x-2 ${
                  frameworkRateExceeded ? "font-semibold" : ""
                }`}
              >
                <span className="whitespace-nowrap">
                  {formatCurrency(contract.framework_rate, candidateCurrency)}
                  <span className="opacity-70">{unitSuffix}</span>
                </span>
                <PlnConversion
                  amount={contract.framework_rate}
                  exchangeRate={candidateExchangeRate}
                  unitSuffix={unitSuffix}
                  testId="framework-rate-pln"
                />
              </span>
            </div>
          )}
        </div>
      </div>
      {eurPlnRate &&
        (normalizedClientCurrency === "EUR" || normalizedCandidateCurrency === "EUR") && (
        <div
          className="flex items-start gap-2 rounded-2xl bg-card px-6 py-3 text-[11px] leading-relaxed text-muted-foreground shadow-xs dark:bg-muted"
          data-testid="eur-pln-rate-note"
        >
          <RefreshCw className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
          <p>
            Kurs EUR/PLN z tabeli A NBP na dzień {formatNbpDate(eurPlnRate.effective_date)}:
            1 € = {formatNbpRate(eurPlnRate.rate)}
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
  exchangeRate,
  testIdPrefix,
}: {
  currency: string;
  entries: RateScheduleEntry[];
  unitSuffix: string;
  exchangeRate: EurPlnRate | null;
  testIdPrefix: string;
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
          <span className="flex flex-wrap items-baseline justify-end gap-x-2">
            <span className="whitespace-nowrap">
              {formatCurrency(entry.rate, currency)}
              <span className="opacity-70">{unitSuffix}</span>
            </span>
            <PlnConversion
              amount={entry.rate}
              exchangeRate={exchangeRate}
              unitSuffix={unitSuffix}
              testId={`${testIdPrefix}-${entry.id}-pln`}
            />
          </span>
        </div>
      ))}
    </div>
  );
}
