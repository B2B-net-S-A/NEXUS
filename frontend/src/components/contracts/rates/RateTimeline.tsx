"use client";
// „Stawki w czasie” w zakładce „Pieniądze” (wariant A z 19.11.2026): mały
// wykres schodkowy i pod nim zwarta tabela kroków (Od · Klient · Kandydat ·
// Marża · Źródło). Wpisy zastąpione tego samego dnia nie mają wierszy — zostaje
// po nich jedna linia „Pominięto N …”. Jeden krok to jedno zdanie bez wykresu.
// Wykres na jednej osi tylko w jednej walucie (Bosch: klient w EUR, kandydat
// w PLN — wtedy same kroki w tabeli).
import { useId } from "react";

import { StatusDot } from "@/components/ds/StatusDot";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl as formatDate } from "@/lib/date-pl";
import { currencySymbol } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { PlnConversion } from "./PlnConversion";
import { RateStepChart } from "./RateStepChart";
import { formatPercent, formatRateNumber } from "./rate-format";
import { STEP_SOURCE_LABEL, describeRateChanges, type ChartModel, type RateStepRow } from "./rate-steps";

export interface RateTimelineProps {
  rows: RateStepRow[];
  /** `null` przy jednym kroku albo różnych walutach. */
  chart: ChartModel | null;
  sameCurrency: boolean;
  clientCurrency: string;
  candidateCurrency: string;
  /** „zł/h”, „EUR/h”… */
  clientUnit: string;
  candidateUnit: string;
  /** Kurs EUR/PLN dla kwot w EUR; `null` = bez przeliczeń. */
  clientExchangeRate: number | null;
  candidateExchangeRate: number | null;
  superseded: { client: number; candidate: number };
  contractStart: string | null;
  hasAnyRate: boolean;
  today: string;
}

// Jednostka w nagłówku: obok nazwy kolumny, a w wąskiej karcie (okno edycji
// w „Przeglądzie”, ok. 290 px) pod nią — inaczej tabela wychodzi poza kartę.
const HEAD_UNIT =
  "block text-[11px] font-normal normal-case tracking-normal text-muted-foreground @2xl:ml-1 @2xl:inline";

function sourceTestId(row: RateStepRow): string | undefined {
  if (row.clientStepId != null) return `client-rate-schedule-${row.clientStepId}-source`;
  if (row.candidateStepId != null) return `candidate-rate-schedule-${row.candidateStepId}-source`;
  return undefined;
}

function Amount({ value }: { value: number | null }) {
  return value == null ? <span className={CALM_EMPTY}>—</span> : <>{formatRateNumber(value)}</>;
}

function ChartLegend() {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
      <li className="flex items-center gap-1.5">
        <span aria-hidden="true" className="h-0.5 w-4 rounded-full bg-primary" />
        klient
      </li>
      <li className="flex items-center gap-1.5">
        <span aria-hidden="true" className="h-0.5 w-4 rounded-full bg-muted-foreground" />
        kandydat
      </li>
      <li className="flex items-center gap-1.5">
        <span aria-hidden="true" className="h-2.5 w-4 rounded-sm bg-success/15" />
        marża
      </li>
    </ul>
  );
}

function SingleStep({ row, clientUnit, candidateUnit }: { row: RateStepRow; clientUnit: string; candidateUnit: string }) {
  return (
    <p className="text-[13px] leading-5 text-foreground" data-testid="rate-single-step">
      <span className="font-medium">{`Od ${formatDate(row.date)}`}</span>
      {row.state === "planned" ? " (zaplanowana): " : " bez zmian: "}
      {row.client != null ? `klient płaci ${formatRateNumber(row.client)} ${clientUnit}` : "bez stawki klienta"}
      {", "}
      {row.candidate != null
        ? `kandydat dostaje ${formatRateNumber(row.candidate)} ${candidateUnit}`
        : "bez stawki kandydata"}
      <span className="text-muted-foreground">
        {" (źródło: "}
        <span data-testid={sourceTestId(row)}>{STEP_SOURCE_LABEL[row.source]}</span>)
      </span>
      .
      {row.note ? (
        <span className="mt-0.5 block text-xs text-muted-foreground" title={row.note}>
          {row.note}
        </span>
      ) : null}
    </p>
  );
}

function StepTable({
  rows,
  sameCurrency,
  clientUnit,
  candidateUnit,
  clientExchangeRate,
  candidateExchangeRate,
}: Pick<
  RateTimelineProps,
  "rows" | "sameCurrency" | "clientUnit" | "candidateUnit" | "clientExchangeRate" | "candidateExchangeRate"
>) {
  const cell = "py-2 pr-2 @2xl:pr-4";
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]" data-testid="rate-steps-table">
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className={cn(CALM_HEAD, cell, "text-left")}>
              Od
            </th>
            <th scope="col" className={cn(CALM_HEAD, cell, "text-right")}>
              Klient<span className={HEAD_UNIT}>{clientUnit}</span>
            </th>
            <th scope="col" className={cn(CALM_HEAD, cell, "text-right")}>
              Kandydat<span className={HEAD_UNIT}>{candidateUnit}</span>
            </th>
            {sameCurrency ? (
              <th scope="col" className={cn(CALM_HEAD, cell, "text-right")}>
                Marża<span className={HEAD_UNIT}>{clientUnit}</span>
              </th>
            ) : null}
            <th scope="col" className={cn(CALM_HEAD, "hidden py-2 pl-1 text-left @2xl:table-cell")}>
              Źródło
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const margin =
              sameCurrency && row.client != null && row.candidate != null ? row.client - row.candidate : null;
            const marginPct = margin != null && row.client ? (margin / row.client) * 100 : null;
            const source = STEP_SOURCE_LABEL[row.source];
            return (
              <tr key={row.date} className={cn(CALM_ROW, "align-middle")} data-testid={`rate-step-${row.date}`}>
                <td className={cn(cell, "whitespace-nowrap")}>
                  <span className={cn("tabular-nums text-foreground", row.state === "current" && "font-medium")}>
                    {formatDate(row.date)}
                  </span>
                  {row.state === "current" ? (
                    <StatusDot tone="success" className="mt-0.5 flex">
                      obowiązuje
                    </StatusDot>
                  ) : row.state === "planned" ? (
                    <StatusDot tone="info" className="mt-0.5 flex">
                      zaplanowana
                    </StatusDot>
                  ) : null}
                  {/* W wąskiej kolumnie (okno edycji) źródło stoi pod datą. */}
                  <span className={cn(CALM_SUBLINE, "line-clamp-2 whitespace-normal @2xl:hidden")}>
                    {source}
                    {row.note ? ` · ${row.note}` : ""}
                  </span>
                </td>
                <td
                  className={cn(
                    cell,
                    CALM_AMOUNT,
                    row.clientChanged ? "font-medium text-foreground" : "text-muted-foreground",
                  )}
                >
                  <Amount value={row.client} />
                  <PlnConversion
                    amount={row.client}
                    exchangeRate={clientExchangeRate}
                    testId={row.clientStepId != null ? `client-rate-schedule-${row.clientStepId}-pln` : undefined}
                    className="block text-[11.5px]"
                  />
                </td>
                <td
                  className={cn(
                    cell,
                    CALM_AMOUNT,
                    row.candidateChanged ? "font-medium text-foreground" : "text-muted-foreground",
                  )}
                >
                  <Amount value={row.candidate} />
                  <PlnConversion
                    amount={row.candidate}
                    exchangeRate={candidateExchangeRate}
                    testId={
                      row.candidateStepId != null ? `candidate-rate-schedule-${row.candidateStepId}-pln` : undefined
                    }
                    className="block text-[11.5px]"
                  />
                </td>
                {sameCurrency ? (
                  <td className={cn(cell, CALM_AMOUNT, "text-foreground")}>
                    <Amount value={margin} />
                    {marginPct != null ? <span className={CALM_SUBLINE}>{formatPercent(marginPct)}</span> : null}
                  </td>
                ) : null}
                <td className="hidden max-w-[22rem] py-2 pl-1 @2xl:table-cell">
                  <span className="text-foreground" data-testid={sourceTestId(row)}>
                    {source}
                  </span>
                  {row.note ? (
                    <span className={cn(CALM_SUBLINE, "truncate")} title={row.note}>
                      {row.note}
                    </span>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function RateTimeline(props: RateTimelineProps) {
  const headingId = useId();
  const { rows, chart, sameCurrency, superseded, contractStart } = props;
  const showChart = chart !== null && rows.length > 1;
  const supersededTotal = superseded.client + superseded.candidate;
  const supersededWhere = [superseded.client ? "klient" : null, superseded.candidate ? "kandydat" : null]
    .filter(Boolean)
    .join(", ");
  const firstDate = rows[0]?.date ?? null;
  const startsLater = contractStart !== null && firstDate !== null && contractStart < firstDate;

  return (
    <section
      aria-labelledby={headingId}
      className="rounded-xl border border-border bg-card p-4 shadow-xs"
      data-testid="rate-timeline"
    >
      <div className="mb-2 flex min-h-7 flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <h2 id={headingId} className="text-[13.5px] font-semibold text-foreground">
          Stawki w czasie
        </h2>
        {showChart ? <ChartLegend /> : null}
      </div>

      {rows.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">
          {props.hasAnyRate
            ? "Harmonogram stawek jest pusty — obowiązują stawki z kontraktu."
            : "Kontrakt nie ma jeszcze stawek — wejdą z zamówienia klienta albo z aneksu."}
        </p>
      ) : rows.length === 1 ? (
        <SingleStep row={rows[0]} clientUnit={props.clientUnit} candidateUnit={props.candidateUnit} />
      ) : (
        <>
          {showChart && chart ? (
            <RateStepChart
              segments={chart.segments}
              axis={chart.axis}
              today={props.today}
              unit={props.clientUnit}
              description={describeRateChanges(rows, { client: props.clientUnit, candidate: props.candidateUnit })}
            />
          ) : !sameCurrency ? (
            <p className="mb-1 text-[13px] text-muted-foreground" data-testid="rate-timeline-mixed-currency">
              Klient płaci w {currencySymbol(props.clientCurrency)}, kandydat dostaje w{" "}
              {currencySymbol(props.candidateCurrency)} — wykres na jednej osi byłby mylący, kroki są w tabeli.
            </p>
          ) : null}
          <div className={showChart ? "mt-3" : undefined}>
            <StepTable {...props} />
          </div>
        </>
      )}

      {supersededTotal > 0 || startsLater ? (
        <p className="mt-2 text-xs leading-5 text-muted-foreground">
          {supersededTotal > 0 ? (
            <span data-testid="rate-steps-superseded">
              Pominięto{" "}
              {countPl(supersededTotal, "wpis zastąpiony", "wpisy zastąpione", "wpisów zastąpionych")} tego samego
              dnia ({supersededWhere}).
            </span>
          ) : null}
          {supersededTotal > 0 && startsLater ? " " : null}
          {startsLater && firstDate ? (
            <span>
              Umowa trwa od {formatDate(contractStart)}, a harmonogram stawek zaczyna się {formatDate(firstDate)}.
            </span>
          ) : null}
        </p>
      ) : null}
    </section>
  );
}
