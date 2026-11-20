"use client";

import Link from "next/link";
import { ArrowRight, Info } from "lucide-react";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney, formatWholeMoney } from "@/lib/money";
import {
  CREATE_STATUS_LABEL,
  createButtonLabel,
  createOutcome,
  formatPctPl,
  type ContractMoneyFacts,
  type CreateStatus,
} from "@/lib/new-contract-summary";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<CreateStatus, StatusDotTone> = {
  draft: "info",
  active: "success",
  ending: "warning",
  ended: "neutral",
};

export interface NewContractSummaryMoney {
  facts: ContractMoneyFacts;
  clientRate: number | null;
  candidateRate: number | null;
  clientCurrency: string;
  candidateCurrency: string;
  rateUnit: string;
}

export interface NewContractSummaryCardProps {
  candidateName: string | null;
  clientName: string | null;
  recruitmentTitle: string | null;
  contractTypeLabel: string;
  startDate: string;
  /** „za 3 dni”, „dziś” — liczone w kalendarzu Warszawy. */
  startRelative: string | null;
  /** „bezterminowo”, „do 31.12.2026”, „bez daty końca”. */
  endLabel: string;
  status: string;
  /** Kwoty tylko dla osoby, która je wpisuje („Stawki i kwoty: zmiana”). */
  money: NewContractSummaryMoney | null;
  later: string[];
  error: string;
  submitting: boolean;
}

function Row({ label, children, strong }: { label: string; children: React.ReactNode; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-[13px] leading-5">
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
      <dd className={cn("min-w-0 text-right tabular-nums text-foreground", strong && "font-semibold")}>
        {children}
      </dd>
    </div>
  );
}

function MoneyRows({ money }: { money: NewContractSummaryMoney }) {
  const { facts } = money;
  const negative = facts.marginPerUnit != null && facts.marginPerUnit < 0;
  const bothRates = money.clientRate != null && money.candidateRate != null;
  return (
    <>
      <dl className="space-y-0.5 border-t border-border/60 pt-2">
        <Row label="Klient płaci">{formatMoney(money.clientRate, money.clientCurrency, money.rateUnit)}</Row>
        <Row label="Konsultant dostaje">
          {formatMoney(money.candidateRate, money.candidateCurrency, money.rateUnit)}
        </Row>
        <Row label="Marża" strong>
          {facts.marginPerUnit != null ? (
            <span className={negative ? "text-destructive" : "text-success"}>
              {formatMoney(facts.marginPerUnit, money.clientCurrency, money.rateUnit)} ·{" "}
              {formatPctPl(facts.marginPct)}
            </span>
          ) : (
            "—"
          )}
        </Row>
      </dl>
      {bothRates && !facts.sameCurrency ? (
        <p className="text-[12px] leading-4 text-muted-foreground">
          Różne waluty stawek ({money.clientCurrency} / {money.candidateCurrency}) — marży nie liczymy.
        </p>
      ) : null}
      <div className="rounded-lg bg-muted/60 px-3 py-1.5">
        <p className="mb-1 text-[11.5px] font-medium text-muted-foreground">
          {facts.hours != null ? `Miesięcznie (${facts.hours} h)` : "Miesięcznie (ryczałt)"}
        </p>
        <dl className="space-y-0.5">
          <Row label="Przychód">{formatWholeMoney(facts.monthlyRevenue, money.clientCurrency)}</Row>
          <Row label="Koszt">{formatWholeMoney(facts.monthlyCost, money.candidateCurrency)}</Row>
          <Row label="Marża" strong>
            {facts.monthlyMargin != null ? `≈ ${formatWholeMoney(facts.monthlyMargin, money.clientCurrency)}` : "—"}
          </Row>
        </dl>
      </div>
    </>
  );
}

/**
 * Wariant B „Nowego kontraktu”: przyklejona karta obok formularza mówi na
 * bieżąco, co powstanie, i trzyma jedyny przycisk główny ekranu.
 */
export function NewContractSummaryCard({
  candidateName,
  clientName,
  recruitmentTitle,
  contractTypeLabel,
  startDate,
  startRelative,
  endLabel,
  status,
  money,
  later,
  error,
  submitting,
}: NewContractSummaryCardProps) {
  const statusKey = (status in CREATE_STATUS_LABEL ? status : "draft") as CreateStatus;
  const outcome = createOutcome(statusKey);
  return (
    <section
      aria-label="Podsumowanie"
      data-tour="contracts.new.summary"
      className="rounded-xl border border-border bg-card shadow-xs"
    >
      <header className="flex items-center justify-between gap-2 border-b border-border/70 px-4 py-2">
        <h2 className="text-[13.5px] font-semibold text-foreground">Podsumowanie</h2>
        <StatusDot tone={STATUS_TONE[statusKey]}>{CREATE_STATUS_LABEL[statusKey]}</StatusDot>
      </header>
      <div className="space-y-2.5 px-4 py-3">
        <div>
          <p className="text-[15px] font-semibold leading-5 text-foreground">
            {candidateName ?? <span className="font-normal text-muted-foreground">Kandydat nie jest wybrany</span>}
          </p>
          <p className="mt-0.5 flex items-center gap-1.5 text-[13px] leading-5 text-foreground">
            <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
            {clientName ?? <span className="text-muted-foreground">klient nie jest wybrany</span>}
          </p>
          <p
            className="mt-0.5 line-clamp-2 text-[12px] leading-4 text-muted-foreground"
            title={recruitmentTitle ?? undefined}
          >
            {recruitmentTitle ?? "bez rekrutacji"} · {contractTypeLabel}
          </p>
        </div>
        <dl className="border-t border-border/60 pt-2">
          <Row label="Okres">
            {startDate ? (
              <>
                od {formatIsoDatePl(startDate)}
                {startRelative ? <span className="text-muted-foreground"> ({startRelative})</span> : null} ·{" "}
                {endLabel}
              </>
            ) : (
              <span className="text-muted-foreground">brak daty startu</span>
            )}
          </Row>
        </dl>
        {money ? <MoneyRows money={money} /> : null}
        <p className="flex gap-2 text-[12px] leading-[17px] text-muted-foreground">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>
            <span className="font-medium text-foreground">Po utworzeniu: {outcome.status}</span> — {outcome.detail}
            {later.length > 0 ? ` Później uzupełnisz: ${later.join(", ")}.` : ""}
          </span>
        </p>
        {error ? (
          <p
            role="alert"
            className="rounded-lg border border-current/20 bg-destructive/10 px-3 py-2 text-[12.5px] leading-[18px] text-destructive"
          >
            {error}
          </p>
        ) : null}
        <div className="space-y-1.5">
          <Button type="submit" className="w-full" loading={submitting}>
            {createButtonLabel(statusKey)}
          </Button>
          <Button asChild variant="ghost" size="sm" className="w-full">
            <Link href="/contracts">Anuluj</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}
