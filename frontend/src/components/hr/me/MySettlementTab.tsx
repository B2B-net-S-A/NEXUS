"use client";

import { useState } from "react";
import { Copy, FileDown } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadHrFile } from "@/lib/api/hr";
import {
  settlementPaths,
  useMySettlements,
  type MySettlementMonth,
  type MySettlements,
  type SettlementStep,
} from "@/lib/api/hr-settlements";
import { CALM_AMOUNT } from "@/lib/calm-table";
import { formatDayMonthPl, formatIsoDatePl } from "@/lib/date-pl";
import { capitalize } from "@/lib/hr-employment-terms";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";

import {
  SETTLEMENT_TONE,
  accountLabel,
  copyItemsText,
  documentTitle,
  formNote,
  mergeSettlementYears,
  nextStepText,
  previousMonthLine,
  settlementLayout,
  stepDetail,
  stepLabel,
} from "./settlement-format";

const STEP_DOT: Record<SettlementStep["state"], string> = {
  done: "bg-success",
  current: "bg-primary",
  warn: "bg-warning",
  todo: "bg-muted-foreground/30",
};

/** Kroki od godzin do „Opłacono” w jednym pasku (M1, M2). */
export function SettlementSteps({ steps }: { steps: readonly SettlementStep[] }) {
  return (
    <ol className="grid gap-2 sm:grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]" aria-label="Kroki rozliczenia">
      {steps.map((step) => {
        const detail = stepDetail(step);
        return (
          <li
            key={step.key}
            className="flex items-start gap-2"
            aria-current={step.state === "current" ? "step" : undefined}
          >
            <span aria-hidden className={cn("mt-1.5 size-2 shrink-0 rounded-full", STEP_DOT[step.state])} />
            <span className="min-w-0">
              <span
                className={cn(
                  "block text-sm",
                  step.state === "todo" ? "text-muted-foreground" : "font-medium text-foreground",
                )}
              >
                {stepLabel(step)}
              </span>
              {detail ? <span className="block text-xs text-muted-foreground">{detail}</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function ItemsTable({ month }: { month: MySettlementMonth }) {
  const basis = month.amount_basis === "net" ? "netto" : "brutto";
  return (
    <table className="w-full text-sm">
      <tbody>
        {month.items.map((item, index) => (
          <tr key={`${item.kind}-${item.bonus_id ?? index}`} className="border-b border-border/60">
            <td className="py-1.5 pr-3 text-foreground">{item.label}</td>
            <td className={cn(CALM_AMOUNT, "py-1.5 text-foreground")}>
              {formatMoney(item.amount, month.currency)}
            </td>
          </tr>
        ))}
        <tr>
          <td className="pt-2 font-semibold text-foreground">
            {month.employment_type === "zlecenie" ? "Wynagrodzenie brutto" : `Razem ${basis}`}
          </td>
          <td className={cn(CALM_AMOUNT, "pt-2 font-semibold text-foreground")}>
            {formatMoney(month.amount, month.currency)}
          </td>
        </tr>
      </tbody>
    </table>
  );
}

function InvoiceCard({ month }: { month: MySettlementMonth }) {
  const invoice = month.invoice;
  if (!invoice) return null;
  return (
    <Card size="sm" className="space-y-1.5" aria-labelledby={`invoice-${month.settlement_id}`}>
      <div className="flex items-center justify-between gap-2">
        <h3
          id={`invoice-${month.settlement_id}`}
          className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground"
        >
          Faktura {invoice.source === "ksef" ? "z KSeF" : "(PDF)"}
        </h3>
        <StatusDot tone={SETTLEMENT_TONE[month.status]}>{month.status_label.toLowerCase()}</StatusDot>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Numer</dt>
        <dd className="text-foreground">
          {invoice.invoice_number}
          {invoice.corrections ? ` + korekta (${invoice.corrections})` : ""}
        </dd>
        {invoice.ksef_number ? (
          <>
            <dt className="text-muted-foreground">Numer KSeF</dt>
            <dd className="break-all text-foreground">{invoice.ksef_number}</dd>
          </>
        ) : null}
        <dt className="text-muted-foreground">Netto / brutto</dt>
        <dd className="tabular-nums text-foreground">
          {formatMoney(invoice.net_total, month.currency)} / {formatMoney(invoice.gross_total, month.currency)}
        </dd>
        <dt className="text-muted-foreground">Na rachunek</dt>
        <dd className="text-foreground">{accountLabel(month.account_last4, month.account_source)}</dd>
        <dt className="text-muted-foreground">Termin</dt>
        <dd className="text-foreground">{formatIsoDatePl(month.due_on)}</dd>
      </dl>
    </Card>
  );
}

function CurrentMonth({ month }: { month: MySettlementMonth }) {
  const { showToast } = useToast();
  const [downloading, setDownloading] = useState(false);
  const b2b = month.employment_type === "b2b";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(copyItemsText(month));
      showToast("Pozycje skopiowane", "success");
    } catch {
      showToast("Nie udało się skopiować — zaznacz pozycje ręcznie.", "error");
    }
  };

  const download = async () => {
    if (month.settlement_id == null) return;
    setDownloading(true);
    try {
      await downloadHrFile(
        settlementPaths.myPdf(month.settlement_id),
        `rozliczenie-zlecenia-${month.year}-${String(month.month).padStart(2, "0")}.pdf`,
      );
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać PDF-u."), "error");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="space-y-3">
      <Card size="sm">
        <SettlementSteps steps={month.steps} />
      </Card>
      <div className={cn("grid gap-3", b2b && month.invoice ? "lg:grid-cols-[3fr_2fr]" : "")}>
        <Card
          size="sm"
          className="space-y-2"
          aria-labelledby={`month-${month.year}-${month.month}-${month.currency}`}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2
              id={`month-${month.year}-${month.month}-${month.currency}`}
              className="text-sm font-semibold text-foreground"
            >
              {capitalize(month.label)} · {documentTitle(month)}
            </h2>
            <div className="flex items-center gap-2">
              {b2b && month.items.length > 0 ? (
                <Button size="sm" variant="outline" onClick={copy}>
                  <Copy className="h-4 w-4" aria-hidden />
                  Kopiuj pozycje
                </Button>
              ) : null}
              {month.has_pdf ? (
                <Button size="sm" variant="outline" onClick={download} disabled={downloading}>
                  <FileDown className="h-4 w-4" aria-hidden />
                  {downloading ? "Pobieranie…" : "Pobierz PDF"}
                </Button>
              ) : null}
            </div>
          </div>
          {month.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Pozycje pojawią się po potwierdzeniu raportu godzin.
            </p>
          ) : (
            <ItemsTable month={month} />
          )}
          <p className="text-xs text-muted-foreground">{formNote(month.employment_type)}</p>
          <p className="text-sm text-foreground">{nextStepText(month)}</p>
        </Card>
        {b2b ? <InvoiceCard month={month} /> : null}
      </div>
    </div>
  );
}

function PreviousMonths({ months }: { months: readonly MySettlementMonth[] }) {
  if (months.length === 0) return null;
  return (
    <section className="space-y-1" aria-labelledby="settlement-previous">
      <h2
        id="settlement-previous"
        className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground"
      >
        Poprzednie miesiące
      </h2>
      <ul className="divide-y divide-border/60 rounded-lg border border-border bg-card px-3">
        {months.map((month) => (
          <li
            key={`${month.year}-${month.month}-${month.currency}`}
            className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-2"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium text-foreground">{capitalize(month.label)}</p>
              <p className="text-xs text-muted-foreground">{previousMonthLine(month)}</p>
            </div>
            <StatusDot tone={SETTLEMENT_TONE[month.status]}>
              {month.status_label.toLowerCase()}
              {month.paid_on ? ` ${formatDayMonthPl(month.paid_on)}` : ""}
            </StatusDot>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Treść zakładki dla danych (bez zapytań) — także w harnessie i testach.
 * Na górze miesiące, w których osoba ma coś do zrobienia, potem najnowszy;
 * waluty miesiąca razem (`settlementLayout`).
 */
export function MySettlementView({ data }: { data: MySettlements }) {
  if (data.months.length === 0) {
    return (
      <Card size="sm" className="text-sm text-muted-foreground">
        W {data.year} nie ma jeszcze miesięcy do rozliczenia — pozycje pojawią się po
        potwierdzeniu raportu godzin.
      </Card>
    );
  }
  const { featured, previous } = settlementLayout(data.months);
  return (
    <div className="space-y-4">
      {featured.flat().map((month) => (
        <CurrentMonth key={`${month.year}-${month.month}-${month.currency}`} month={month} />
      ))}
      <PreviousMonths months={previous} />
      {data.employment_type === "b2b" ? (
        <p className="text-xs text-muted-foreground">
          Faktury rozpoznajemy w KSeF po NIP-ie{data.nip ? "" : " — Kadry jeszcze go nie wpisały"}.
          Rachunek do przelewu: {accountLabel(data.account_last4, data.account_source)}.
        </p>
      ) : null}
    </div>
  );
}

/**
 * „Mój czas → Rozliczenie” (etap 4): dokument miesiąca według formy — B2B
 * „Do faktury” z pozycjami i fakturą z KSeF, zlecenie — rozliczenie
 * z potwierdzenia godzin z PDF-em, UoP — dane do listy płac. Tylko o sobie.
 * Bieżący rok i poprzedni (`mergeSettlementYears`) — ekran nie ma wyboru roku.
 */
export function MySettlementTab() {
  const today = warsawToday();
  const year = Number(today.slice(0, 4));
  const query = useMySettlements(year);
  // Poprzedni rok zawsze: grudzień do faktury nie znika 1.01 (audyt A2, 19.10.2026).
  const lastYear = useMySettlements(year - 1);
  const state = resolveViewState({
    isLoading: query.isLoading || lastYear.isLoading,
    isError: query.isError || lastYear.isError,
    error: query.error ?? lastYear.error,
    isSuccess: query.isSuccess && lastYear.isSuccess,
  });
  if (state === "loading") {
    return <p className="text-sm text-muted-foreground">Wczytywanie rozliczenia…</p>;
  }
  if (state !== "ready" || !query.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        description={
          state === "not_found"
            ? "Rozliczenia nie są jeszcze włączone."
            : state === "forbidden"
              ? "Rozliczenie widzą osoby z kartoteką pracownika."
              : "Nie udało się wczytać rozliczenia."
        }
        onRetry={() => {
          void query.refetch();
          void lastYear.refetch();
        }}
      />
    );
  }
  return <MySettlementView data={mergeSettlementYears(query.data, lastYear.data, today)} />;
}

