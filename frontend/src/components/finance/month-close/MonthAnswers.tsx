"use client";

// Cztery odpowiedzi nad tabelą miesiąca (makiety 24.11.2026): co zrobił automat,
// co jest źle, czego brakuje i na jakim etapie są faktury do klientów.
// Każda karta zaczyna się od pytania, a liczba pod nim jest odpowiedzią.

import Link from "next/link";
import type { ReactNode } from "react";

import type { MonthCloseOverview, TeamMonth } from "@/lib/api/client-settlements";
import type { ReminderClient } from "@/lib/api/settlement-reminders";
import { countPl, pluralPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";

import { pln } from "../settlements/format";
import { issueHref } from "./ClientMonthStrip";
import {
  LEVEL_LOOK,
  automatAnswer,
  invoiceAnswer,
  missingAnswer,
  problemLines,
  problemTotal,
  stagesOf,
  type StepTone,
} from "./month-model";

const SQUARE: Record<StepTone, string> = {
  done: "bg-success",
  warn: "bg-warning",
  fail: "bg-destructive",
  todo: "bg-info",
  wait: "bg-muted-foreground/40",
  na: "bg-muted-foreground/20",
};

function Card({ question, children, footer }: { question: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <section className="flex min-w-0 flex-col rounded-xl border bg-card px-3 pb-2 pt-2.5">
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{question}</h3>
      <div className="mt-0.5 flex-1">{children}</div>
      {footer ? <div className="mt-1.5 flex items-center justify-between gap-2 border-t pt-1.5 text-[11px]">{footer}</div> : null}
    </section>
  );
}

function Big({ value, rest }: { value: ReactNode; rest: ReactNode }) {
  return (
    <p className="truncate font-display text-[22px] font-semibold leading-7 tabular-nums">
      {value} <span className="text-[12px] font-normal text-muted-foreground">{rest}</span>
    </p>
  );
}

function Line({
  tone,
  label,
  value,
  muted,
  title,
  fill,
}: {
  tone?: StepTone;
  label: ReactNode;
  value: ReactNode;
  muted?: boolean;
  title?: string;
  /** Udział 0–1: tło linii wypełnione jak pasek (lejek automatu). */
  fill?: number;
}) {
  return (
    <li
      title={title}
      className={cn("relative flex items-center gap-2 rounded-sm px-1 text-[12px] leading-[18px]", muted && "text-muted-foreground")}
    >
      {fill != null ? (
        <span aria-hidden className="absolute inset-y-0 left-0 rounded-sm bg-success/15" style={{ width: `${Math.round(Math.min(1, fill) * 100)}%` }} />
      ) : null}
      {tone ? <span aria-hidden className={cn("relative size-2 shrink-0 rounded-[3px]", SQUARE[tone])} /> : null}
      <span className="relative min-w-0 flex-1 truncate">{label}</span>
      <span className="relative shrink-0 font-medium tabular-nums">{value}</span>
    </li>
  );
}

interface MonthAnswersProps {
  data: MonthCloseOverview;
  month: string;
  team: TeamMonth | null;
  /** Błąd zapytania o biuro — karta mówi o nim zamiast chować linie biura. */
  teamError: string | null;
  /** `null` — przypomnienia jeszcze się ładują albo zapytanie padło (to nie zero). */
  reminders: ReminderClient[] | null;
  onShowIssues: () => void;
}

export function MonthAnswers({ data, month, team, teamError, reminders, onShowIssues }: MonthAnswersProps) {
  const s = stagesOf(data);
  const automat = automatAnswer(data, team);
  const problems = problemLines(s);
  const total = problemTotal(s);
  const top = data.reasons.filter((r) => r.level === "fail" || r.level === "warn").slice(0, 2);
  const missing = missingAnswer(data, team);
  const noRecipient = reminders ? reminders.reduce((acc, r) => acc + (r.without_recipient ?? 0), 0) : null;
  const invoices = invoiceAnswer(data);
  const issuedClients = invoices.counts.issued + invoices.counts.partial;
  const ready = data.can_see_amounts
    ? data.clients.reduce((acc, c) => acc + (c.client_report ? 0 : Number(c.revenue_ready ?? 0)), 0)
    : null;

  return (
    <div data-tour="finance.month-close.answers" className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
      <Card question="Co zrobił automat">
        <Big value={`${automat.clean} z ${automat.people}`} rest={`przeszło samo · ${automat.pct}%`} />
        <ul className="-mx-1 mt-1 space-y-px">
          {automat.steps.map((step) => (
            <Line
              key={step.label}
              label={step.label}
              title={step.note}
              fill={step.of ? step.value / step.of : 0}
              value={
                <>
                  {step.value}
                  <span className="font-normal text-muted-foreground">/{step.of}</span>
                </>
              }
            />
          ))}
        </ul>
      </Card>

      <Card
        question="Co jest źle"
        footer={
          <button type="button" onClick={onShowIssues} className="font-medium text-primary hover:underline">
            Powody i kto rozstrzyga →
          </button>
        }
      >
        <Big value={total} rest={`${pluralPl(total, "osoba", "osoby", "osób")} do decyzji lub poprawki`} />
        <ul className="-mx-1 mt-1 space-y-px">
          {problems.map((p) => (
            <Line key={p.level} tone={LEVEL_LOOK[p.level].tone} label={p.label} title={p.hint} value={p.count} muted={p.count === 0} />
          ))}
        </ul>
        {top.length ? (
          <div className="mt-1 text-[11px] leading-4">
            {top.map((r, i) => (
              <p key={`${r.key}-${r.level}`} className="truncate">
                <span className="text-muted-foreground">{i ? "potem: " : "najczęściej: "}</span>
                {r.title} <span className="tabular-nums text-muted-foreground">×{r.count}</span>
              </p>
            ))}
          </div>
        ) : null}
      </Card>

      <Card question="Czego brakuje">
        <Big value={missing.reports} rest={`${pluralPl(missing.reports, "raport", "raporty", "raportów")} godzin`} />
        <ul className="-mx-1 mt-1 space-y-px">
          <Line tone="wait" label={`Raport godzin · ${countPl(missing.reportClients, "klient", "klientów", "klientów")}`} value={missing.reports} />
          <Line
            tone="fail"
            label="Adres do przypomnienia"
            title={noRecipient == null ? "nie udało się pobrać przypomnień" : "osoby bez adresu, na który automat wyśle przypomnienie"}
            value={noRecipient ?? "—"}
            muted={noRecipient === 0}
          />
          <Line tone="wait" label="Numer zamówienia na osobie" value={missing.orders} muted={missing.orders === 0} />
          {missing.teamTimesheets != null ? (
            <Line tone="wait" label="Biuro: ewidencja czasu" value={missing.teamTimesheets} muted={missing.teamTimesheets === 0} />
          ) : null}
          {missing.teamInvoices != null ? (
            <Line tone="wait" label="Biuro: faktura od osoby" value={missing.teamInvoices} muted={missing.teamInvoices === 0} />
          ) : null}
          {teamError ? <Line tone="fail" label="Biuro: nie udało się pobrać" title={teamError} value="—" /> : null}
          {missing.teamNip ? (
            <Line tone="fail" label="Biuro: NIP do rozliczeń" title="Płace uzupełniają NIP w profilu osoby (Ludzie); bez niego faktury z KSeF nie trafią do biura" value={missing.teamNip} />
          ) : null}
        </ul>
      </Card>

      <Card
        question="Faktury do klientów"
        footer={
          <>
            <Link href={issueHref(month)} className="font-medium text-primary hover:underline">
              Wystaw za miesiąc →
            </Link>
          </>
        }
      >
        <Big value={`${issuedClients} z ${invoices.clients - invoices.counts.report}`} rest="klientów z fakturą" />
        <ul className="-mx-1 mt-1 space-y-px">
          <Line tone={invoices.issuedEarly ? "warn" : "done"} label="Wystawione w KSeF" value={issuedClients} />
          <Line tone="todo" label="Do wystawienia · RCP przyjęte" value={invoices.counts.ready} muted={invoices.counts.ready === 0} />
          <Line tone="wait" label="Czeka na podpis klienta" value={invoices.counts.client} muted={invoices.counts.client === 0} />
          <Line tone="wait" label="Wstrzymane · RCP nieprzyjęte" value={invoices.counts.blocked} />
          {invoices.counts.report ? <Line tone="wait" label="Z raportu klienta (T4T)" value={invoices.counts.report} /> : null}
        </ul>
        {invoices.issuedEarly ? (
          <p
            title="Faktura sprzedaży jest w KSeF, a RCP tych osób nie zostało przyjęte w NEXUS-ie"
            className="mt-1 rounded-md bg-warning-muted px-2 py-0.5 text-[11px] leading-4 text-warning-muted-foreground"
          >
            {invoices.issuedEarly} os. ma fakturę wystawioną przed przyjęciem RCP
          </p>
        ) : null}
        {ready != null && ready > 0 ? (
          <p className="mt-1 truncate text-[11px] text-muted-foreground">
            Bez uwag, do faktur: <span className="font-medium text-foreground tabular-nums">{pln(ready.toFixed(2))}</span>
          </p>
        ) : null}
      </Card>
    </div>
  );
}
