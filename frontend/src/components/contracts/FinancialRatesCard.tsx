"use client";
// Karta „Stawki finansowe” — zakładka „Pieniądze” i okno edycji w „Przeglądzie”
// (wariant A, decyzja Artura z 19.11.2026). Na górze trzy liczby „Klient płaci
// · Konsultant dostaje · Marża” z odpowiednikiem miesięcznym, obok stawka
// z umowy ramowej i kurs NBP; pod spodem „Stawki w czasie” (`rates/`).
import { useId, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";

import api from "@/lib/api";
import type { RecruitmentRate } from "@/lib/api/recruitmentRates";
import { PlnConversion } from "@/components/contracts/rates/PlnConversion";
import { RateTimeline } from "@/components/contracts/rates/RateTimeline";
import { buildRateFigures, frameworkVerdict } from "@/components/contracts/rates/rate-figures";
import {
  formatNbpDate,
  formatNbpRate,
  formatPercent,
  formatPlnAmount,
  formatRateNumber,
  formatWholeAmount,
  rateUnitLabel,
} from "@/components/contracts/rates/rate-format";
import {
  buildChartModel,
  buildStepRows,
  entryInEffect,
  liveSchedule,
  type AmendmentRef,
} from "@/components/contracts/rates/rate-steps";
// Daty ISO bez przesunięcia strefy (audyt 24.09, N8).
import { formatIsoDatePl as formatDate } from "@/lib/date-pl";
import { currencySymbol, formatMoney, rateUnitSuffix } from "@/lib/money";
import { normalizeRateUnit } from "@/lib/recruitment-rate-check";
import { cn, formatDate as formatTimestamp } from "@/lib/utils";
import { MD_PER_MONTH } from "@/lib/work-time";
import { warsawToday } from "@/lib/warsaw-date";

export { formatNbpDate, formatNbpRate, formatPlnAmount } from "@/components/contracts/rates/rate-format";

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
  /** Notatka kroku (powód aneksu, „Stawka początkowa”…). */
  note?: string | null;
  /** Krok z zamówienia klienta (tylko harmonogram stawki klienta). */
  source_order_id?: number | null;
}

interface FrameworkRateEntry {
  id: number;
  rate: number;
  effective_from: string;
  effective_to?: string | null;
}

export interface FinancialRatesContract {
  /** Klucz odczytu aneksów — po nim krok bez zamówienia dostaje źródło „aneks” albo „ręcznie”. */
  id?: number;
  rate_candidate: number | null;
  rate_client: number | null;
  candidate_rate_schedule: RateScheduleEntry[];
  client_rate_schedule: RateScheduleEntry[];
  /** Harmonogram stawki ramowej — data „do” przy stawce z umowy ramowej. */
  framework_rate_schedule?: FrameworkRateEntry[];
  framework_rate: number | null;
  currency: string | null;
  rate_client_currency?: string | null;
  rate_candidate_currency?: string | null;
  rate_unit: "hourly" | "daily" | "monthly";
  billing_hours_per_month: number;
  margin: number | null;
  client_name: string | null;
  eur_pln_rate?: EurPlnRate | null;
  /** Start umowy — podpis osi i zdanie, gdy harmonogram zaczyna się później. */
  start_date?: string | null;
  /** Koniec umowy — gdy minął, oś wykresu kończy się na nim. */
  end_date?: string | null;
  /** Koniec zamówienia klienta — koniec osi wykresu. */
  client_order_end_date?: string | null;
  latest_order_end_date?: string | null;
}

const UNIT_PHRASE: Record<FinancialRatesContract["rate_unit"], string> = {
  hourly: "Stawki godzinowe",
  daily: "Stawki dzienne (MD)",
  monthly: "Stawki miesięczne",
};

const CONTRACT_UNIT_KIND: Record<FinancialRatesContract["rate_unit"], "hour" | "day" | "month"> = {
  hourly: "hour",
  daily: "day",
  monthly: "month",
};

/**
 * Aneksy kontraktu — ten sam klucz i odczyt co licznik zakładki „Aneksy”
 * w `app/contracts/[id]/page.tsx`, więc zwykle z pamięci podręcznej. `null`
 * (brak id, ładowanie, błąd) = nie odróżniamy aneksu od wpisu ręcznego.
 */
function useContractAmendments(contractId: number | undefined): AmendmentRef[] | null {
  const query = useQuery<AmendmentRef[]>({
    queryKey: ["contract-amendments", contractId],
    queryFn: () => api.get(`/api/contracts/${contractId}/amendments`).then((r) => r.data),
    enabled: typeof contractId === "number",
    staleTime: 60_000,
  });
  return query.isSuccess && Array.isArray(query.data) ? query.data : null;
}

function validExchangeRate(rate: EurPlnRate | null | undefined): EurPlnRate | null {
  return rate != null && Number.isFinite(rate.rate) && rate.rate > 0 ? rate : null;
}

/**
 * Stawka do klienta z rekrutacji, gdy kontrakt jeszcze jej nie ma
 * (zgłoszenie Klaudii 29.10.2026). Tylko podpowiedź: przychód kontraktu
 * nadal przychodzi z zamówienia klienta, bo stawka wpisana przed zamówieniem
 * gasiłaby Finansom dzwonek „bez zamówienia” (decyzja z 04.10.2026,
 * `generator-umow-b2b-trzy-zakladki-cyklu-zycia-umowy.md`).
 */
function ClientRateFromRecruitment({
  rate,
  contract,
  candidateCurrency,
}: {
  rate: RecruitmentRate;
  contract: FinancialRatesContract;
  candidateCurrency: string;
}) {
  const value = Number(rate.client_rate_value);
  const currency = rate.client_rate_currency || "PLN";
  const kind = normalizeRateUnit(rate.client_rate_unit);
  const who = [rate.client_rate_by_name, rate.client_rate_at ? formatTimestamp(rate.client_rate_at) : null]
    .filter((item): item is string => Boolean(item))
    .join(", ");
  // Marża tylko przy tej samej jednostce i walucie co stawka kandydata —
  // przeliczanie MD na godziny czy EUR na PLN to już domysł, nie podpowiedź.
  const comparable =
    kind === CONTRACT_UNIT_KIND[contract.rate_unit] &&
    currency.toUpperCase() === candidateCurrency.toUpperCase() &&
    contract.rate_candidate != null;
  const margin = comparable ? value - (contract.rate_candidate as number) : null;
  const marginPct = margin !== null && value > 0 ? (margin / value) * 100 : null;

  return (
    <div
      className="space-y-1 rounded-lg border border-dashed border-border bg-muted/40 px-3 py-2 text-xs"
      data-testid="client-rate-from-recruitment"
    >
      <div className="flex justify-between gap-3">
        <span className="min-w-0 text-muted-foreground">
          Z rekrutacji{rate.job_title ? ` „${rate.job_title}”` : ""}
          {who ? ` (${who})` : ""}
        </span>
        <span className="whitespace-nowrap font-medium tabular-nums text-foreground">
          {formatMoney(value, currency, kind)}
        </span>
      </div>
      {margin !== null && (
        <div className="flex justify-between gap-3 text-muted-foreground">
          <span>Marża wg rekrutacji</span>
          <span className="whitespace-nowrap tabular-nums">
            {formatMoney(margin, currency, kind)}
            {marginPct !== null ? ` (${formatPercent(marginPct)})` : ""}
          </span>
        </div>
      )}
      <p className="text-muted-foreground">Stawka przychodowa wejdzie do kontraktu z zamówieniem klienta.</p>
    </div>
  );
}

const FIGURE_TONE = {
  default: "text-foreground",
  positive: "text-success-muted-foreground",
  negative: "text-destructive",
  empty: "text-muted-foreground",
} as const;

/** Jedna z trzech liczb: etykieta, kwota z jednostką, odpowiednik miesięczny. */
function RateFigure({
  label,
  value,
  unit,
  extra,
  monthly,
  tone = "default",
  testId,
}: {
  label: string;
  value: string;
  unit?: ReactNode;
  extra?: ReactNode;
  monthly?: ReactNode;
  tone?: keyof typeof FIGURE_TONE;
  testId: string;
}) {
  return (
    <div className="min-w-0" data-testid={testId}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      {/* Spacje między częściami: w flexie się nie rysują, a czytnik i schowek
          dostają „163,00 zł/h”, nie „163,00zł/h”. */}
      <dd className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
        <span className={cn("text-[26px] font-semibold leading-8 tracking-tight", FIGURE_TONE[tone])}>{value}</span>
        {unit ? <> <span className="text-xs text-muted-foreground">{unit}</span></> : null}
        {extra ? <> {extra}</> : null}
      </dd>
      {monthly ? <dd className="text-[13px] text-foreground">{monthly}</dd> : null}
    </div>
  );
}

/** Odpowiednik miesięczny („27 384 zł / mies.”); bez kwoty — bez linii. */
function monthlyLine(amount: number | null, currency: string, extra?: ReactNode): ReactNode {
  if (amount === null) return null;
  return (
    <>
      {formatWholeAmount(amount)} {currencySymbol(currency)}
      <span className="text-muted-foreground"> / mies.</span>
      {extra ? <> {extra}</> : null}
    </>
  );
}

export function FinancialRatesCard({
  contract,
  recruitmentRate = null,
}: {
  contract: FinancialRatesContract;
  /** Para z rekrutacji kontraktu — pokazywana tylko, gdy kontrakt nie ma stawki klienta. */
  recruitmentRate?: RecruitmentRate | null;
}) {
  const headingId = useId();
  const amendments = useContractAmendments(contract.id);
  const today = warsawToday();
  // The API redacts this field to null for non-finance callers and historical
  // rows can also predate the PLN default. The parent currently gates the card,
  // but keeping the component null-safe prevents a legacy row from crashing the
  // whole contract detail page.
  const legacyCurrency = contract.currency || "PLN";
  const clientCurrency = contract.rate_client_currency || legacyCurrency;
  const candidateCurrency = contract.rate_candidate_currency || legacyCurrency;
  const clientIsEur = clientCurrency.toUpperCase() === "EUR";
  const candidateIsEur = candidateCurrency.toUpperCase() === "EUR";
  const unitSuffix = rateUnitSuffix(contract.rate_unit);
  const clientUnit = rateUnitLabel(clientCurrency, contract.rate_unit);
  const candidateUnit = rateUnitLabel(candidateCurrency, contract.rate_unit);
  const eurPln = validExchangeRate(contract.eur_pln_rate);
  const eurRate = eurPln?.rate ?? null;
  const clientExchangeRate = clientIsEur ? eurRate : null;
  const candidateExchangeRate = candidateIsEur ? eurRate : null;

  const figures = buildRateFigures({
    rateClient: contract.rate_client,
    rateCandidate: contract.rate_candidate,
    margin: contract.margin,
    clientCurrency,
    candidateCurrency,
    rateUnit: contract.rate_unit,
    billingHoursPerMonth: contract.billing_hours_per_month,
    eurPln: eurRate,
  });
  const marginExchangeRate = figures.sameCurrency && clientIsEur ? eurRate : null;

  const client = liveSchedule(contract.client_rate_schedule);
  const candidate = liveSchedule(contract.candidate_rate_schedule);
  const rows = buildStepRows({
    client,
    candidate,
    fallbackClient: contract.rate_client,
    fallbackCandidate: contract.rate_candidate,
    today,
    amendments,
  });
  const chart = figures.sameCurrency
    ? buildChartModel({
        rows,
        today,
        contractStart: contract.start_date ?? null,
        contractEnd: contract.end_date ?? null,
        orderEnd: contract.latest_order_end_date ?? contract.client_order_end_date ?? null,
      })
    : null;
  const currentRow = rows.find((row) => row.state === "current") ?? null;
  const footnote = [
    UNIT_PHRASE[contract.rate_unit],
    contract.rate_unit === "hourly" ? `miesięcznie przy ${figures.multiplier} h` : null,
    contract.rate_unit === "daily" ? `miesięcznie przy ${MD_PER_MONTH} MD` : null,
    currentRow ? `obowiązują od ${formatDate(currentRow.date)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const showRecruitmentHint =
    contract.rate_client == null &&
    recruitmentRate != null &&
    !recruitmentRate.client_rate_redacted &&
    recruitmentRate.client_rate_value != null &&
    recruitmentRate.client_rate_value !== "";

  // Stawka z umowy ramowej jedną linią. Jest w walucie stawki kandydata, jak
  // na karcie od początku; ocena (limit) tylko u Nordei — `frameworkVerdict`.
  const frameworkRate = contract.framework_rate;
  const frameworkStep = entryInEffect(contract.framework_rate_schedule, today);
  const frameworkUntil =
    frameworkStep && frameworkStep.rate === frameworkRate ? (frameworkStep.effective_to ?? null) : null;
  const verdict = frameworkVerdict({
    frameworkRate,
    rateClient: contract.rate_client,
    clientCurrency,
    frameworkCurrency: candidateCurrency,
    eurPln: eurRate,
    clientName: contract.client_name,
  });
  const showNbp = eurPln !== null && (clientIsEur || candidateIsEur);
  const hasAside = frameworkRate != null || showNbp;

  const marginTone =
    figures.margin === null ? "empty" : figures.margin > 0 ? "positive" : "negative";

  return (
    <div className="@container space-y-4" data-testid="financial-rates-card">
      <section aria-labelledby={headingId} className="rounded-xl border border-border bg-card p-4 shadow-xs">
        <h2 id={headingId} className="sr-only">
          Stawki finansowe
        </h2>
        <div
          className={cn(
            "grid grid-cols-1 gap-4",
            hasAside && "@3xl:grid-cols-[minmax(0,1fr)_minmax(0,21rem)] @3xl:gap-6",
          )}
        >
          <div className="min-w-0">
            {/* Szerokość liczb jak przy kolumnie z umową ramową — bez niej nie
                rozjeżdżają się na całą kartę. */}
            <dl className="grid grid-cols-1 gap-3 @md:max-w-[40rem] @md:grid-cols-3 @md:gap-4">
              <RateFigure
                testId="figure-client"
                label="Klient płaci"
                value={formatRateNumber(contract.rate_client)}
                tone={contract.rate_client == null ? "empty" : "default"}
                unit={contract.rate_client == null ? null : clientUnit}
                extra={
                  <PlnConversion
                    amount={contract.rate_client}
                    exchangeRate={clientExchangeRate}
                    unitSuffix={unitSuffix}
                    testId="rate-client-pln"
                  />
                }
                monthly={monthlyLine(figures.clientMonthly, clientCurrency)}
              />
              <RateFigure
                testId="figure-candidate"
                label="Konsultant dostaje"
                value={formatRateNumber(contract.rate_candidate)}
                tone={contract.rate_candidate == null ? "empty" : "default"}
                unit={contract.rate_candidate == null ? null : candidateUnit}
                extra={
                  <PlnConversion
                    amount={contract.rate_candidate}
                    exchangeRate={candidateExchangeRate}
                    unitSuffix={unitSuffix}
                    testId="rate-candidate-pln"
                  />
                }
                monthly={monthlyLine(figures.candidateMonthly, candidateCurrency)}
              />
              <RateFigure
                testId="figure-margin"
                label="Marża"
                value={formatRateNumber(figures.margin)}
                tone={marginTone}
                unit={
                  !figures.sameCurrency
                    ? "różne waluty"
                    : figures.margin === null
                      ? null
                      : `${clientUnit}${figures.marginPct !== null ? ` · ${formatPercent(figures.marginPct)}` : ""}`
                }
                extra={
                  <PlnConversion
                    amount={figures.margin}
                    exchangeRate={marginExchangeRate}
                    unitSuffix={unitSuffix}
                    testId="margin-pln"
                  />
                }
                monthly={monthlyLine(
                  figures.marginMonthly,
                  clientCurrency,
                  <PlnConversion
                    amount={figures.marginMonthly}
                    exchangeRate={marginExchangeRate}
                    testId="monthly-margin-pln"
                    whole
                  />,
                )}
              />
            </dl>
            <p className="mt-3 text-xs text-muted-foreground" data-testid="rates-footnote">
              {footnote}
            </p>
            {!figures.sameCurrency ? (
              <p className="mt-1 text-xs leading-5 text-muted-foreground" data-testid="margin-mixed-currency">
                Klient płaci w {currencySymbol(clientCurrency)}, konsultant dostaje w{" "}
                {currencySymbol(candidateCurrency)} — marży w jednej walucie nie liczymy.
                {figures.approxPlnDifference !== null ? (
                  <>
                    {" "}
                    Orientacyjnie po kursie NBP różnica to{" "}
                    <span className="whitespace-nowrap text-foreground" data-testid="margin-approx-pln">
                      ≈ {formatPlnAmount(figures.approxPlnDifference)}
                      {unitSuffix}
                      {figures.approxPlnDifferencePct !== null
                        ? ` (${formatPercent(figures.approxPlnDifferencePct)})`
                        : ""}
                    </span>
                    {figures.approxPlnDifferenceMonthly !== null ? (
                      <>
                        , czyli{" "}
                        <span className="whitespace-nowrap text-foreground">
                          ≈ {formatWholeAmount(figures.approxPlnDifferenceMonthly)} zł
                        </span>{" "}
                        miesięcznie
                      </>
                    ) : null}
                    .
                  </>
                ) : null}
              </p>
            ) : null}
            {showRecruitmentHint && recruitmentRate ? (
              <div className="mt-3 @md:max-w-[40rem]">
                <ClientRateFromRecruitment
                  rate={recruitmentRate}
                  contract={contract}
                  candidateCurrency={candidateCurrency}
                />
              </div>
            ) : null}
          </div>

          {hasAside ? (
            <dl className="space-y-2.5 border-t border-border/70 pt-3 text-[12.5px] leading-5 @3xl:border-l @3xl:border-t-0 @3xl:pl-5 @3xl:pt-0">
              {frameworkRate != null ? (
                <div data-testid="framework-rate">
                  <dt className="text-[11.5px] text-muted-foreground">Z umowy ramowej</dt>
                  <dd className="text-foreground">
                    <span className="font-medium tabular-nums">
                      {formatRateNumber(frameworkRate)} {candidateUnit}
                    </span>{" "}
                    <PlnConversion
                      amount={frameworkRate}
                      exchangeRate={candidateExchangeRate}
                      unitSuffix={unitSuffix}
                      testId="framework-rate-pln"
                    />
                    {frameworkUntil ? (
                      <span className="text-muted-foreground"> do {formatDate(frameworkUntil)}</span>
                    ) : null}
                    {verdict?.kind === "within" ? (
                      <span className="text-muted-foreground"> · stawka klienta w limicie</span>
                    ) : null}
                    {verdict?.kind === "over" ? (
                      <span
                        className="mt-0.5 flex items-center gap-1 font-medium text-destructive"
                        title={`Stawka klienta (${formatRateNumber(contract.rate_client)} ${clientUnit}) przekracza stawkę z umowy ramowej`}
                        data-testid="framework-rate-exceeded"
                      >
                        <AlertCircle className="size-3.5 shrink-0" aria-hidden="true" />
                        {verdict.overBy !== null
                          ? `Stawka klienta wyższa o ${formatRateNumber(verdict.overBy)} ${clientUnit}`
                          : "Stawka klienta przekracza stawkę ramową"}
                      </span>
                    ) : null}
                  </dd>
                </div>
              ) : null}
              {showNbp && eurPln ? (
                <div data-testid="eur-pln-rate-note">
                  <dt className="text-[11.5px] text-muted-foreground">Kurs EUR/PLN</dt>
                  <dd className="text-foreground">
                    1 € = {formatNbpRate(eurPln.rate)}
                    <span className="text-muted-foreground">
                      {" "}
                      (tabela A NBP z {formatNbpDate(eurPln.effective_date)})
                    </span>
                  </dd>
                </div>
              ) : null}
            </dl>
          ) : null}
        </div>
      </section>

      <RateTimeline
        rows={rows}
        chart={chart}
        sameCurrency={figures.sameCurrency}
        clientCurrency={clientCurrency}
        candidateCurrency={candidateCurrency}
        clientUnit={clientUnit}
        candidateUnit={candidateUnit}
        clientExchangeRate={clientExchangeRate}
        candidateExchangeRate={candidateExchangeRate}
        superseded={{ client: client.superseded, candidate: candidate.superseded }}
        contractStart={contract.start_date ?? null}
        hasAnyRate={contract.rate_client != null || contract.rate_candidate != null}
        today={today}
      />
    </div>
  );
}
