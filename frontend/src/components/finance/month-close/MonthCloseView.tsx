"use client";

// Finanse → Przychody → „Przebieg miesiąca” (makiety Artura z 23.11.2026):
// wszyscy klienci rozliczeń w jednym miesiącu, kolejka decyzji po powodzie
// i przejście do wystawienia faktur. Dane: GET /api/finance/settlements/overview,
// liczone tym samym `month_view` co ekran jednego klienta.

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useMonthCloseOverview,
  type MonthCloseClient,
  type MonthCloseOverview,
  type MonthCloseReason,
} from "@/lib/api/client-settlements";
import { warsawToday } from "@/lib/warsaw-date";
import { cn } from "@/lib/utils";

import { defaultMonth, monthLabel, pln, recentMonths } from "../settlements/format";
import { reasonPlan } from "./reason-plan";

/** Parametry adresu tego widoku (czyści je zmiana widoku /finance). */
export const MONTH_CLOSE_URL_KEYS = ["mcMonth", "mcTab"] as const;

type Tab = "clients" | "reasons";

function readParam(key: (typeof MONTH_CLOSE_URL_KEYS)[number]): string | null {
  return new URLSearchParams(window.location.search).get(key);
}

function writeParam(key: (typeof MONTH_CLOSE_URL_KEYS)[number], value: string | null) {
  const params = new URLSearchParams(window.location.search);
  if (value == null) params.delete(key);
  else params.set(key, value);
  window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
}

export function settlementsHref(clientId: number, month: string, extra: Record<string, string> = {}): string {
  const params = new URLSearchParams({ view: "settlements", stClient: String(clientId), stMonth: month, ...extra });
  return `/finance?${params.toString()}`;
}

export function issueHref(month: string): string {
  return `/finance?view=sales-invoices&siPeriod=${month}&siView=issue`;
}

export function MonthCloseView() {
  const today = warsawToday();
  const months = useMemo(() => recentMonths(today, 6), [today]);
  const [month, setMonth] = useState(defaultMonth(today));
  const [tab, setTab] = useState<Tab>("clients");

  useEffect(() => {
    const m = readParam("mcMonth");
    if (m && /^\d{4}-\d{2}$/.test(m)) setMonth(m);
    if (readParam("mcTab") === "reasons") setTab("reasons");
  }, []);

  const query = useMonthCloseOverview(month);

  function pickMonth(m: string) {
    setMonth(m);
    writeParam("mcMonth", m);
  }
  function pickTab(t: Tab) {
    setTab(t);
    writeParam("mcTab", t === "clients" ? null : t);
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Miesiąc rozliczeń"
          value={month}
          onChange={(e) => pickMonth(e.target.value)}
          className="h-8 rounded-md border bg-card px-2 text-sm"
        >
          {(months.includes(month) ? months : [month, ...months]).map((m) => (
            <option key={m} value={m}>
              {monthLabel(m)}
            </option>
          ))}
        </select>
        {query.isSuccess ? (
          <div className="flex items-center gap-1">
            {/* Kotwica lekcji nowości: data-tour="finance.month-close.reasons" (przycisk „Do decyzji wg powodu”). */}
            {(
              [
                ["clients", "Klienci", query.data.clients.length],
                ["reasons", "Do decyzji wg powodu", query.data.reasons.reduce((a, r) => a + r.count, 0)],
              ] as const
            ).map(([key, label, n]) => (
              <button
                key={key}
                type="button"
                aria-pressed={tab === key}
                data-tour={key === "reasons" ? "finance.month-close.reasons" : undefined}
                onClick={() => pickTab(key)}
                className={cn(
                  "shrink-0 whitespace-nowrap rounded-md border px-2.5 py-1 text-xs font-medium pointer-coarse:min-h-10",
                  tab === key ? "border-primary bg-primary/10 text-foreground" : "border-border bg-card text-muted-foreground",
                )}
              >
                {label} <span className="tabular-nums">{n}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {query.isError ? (
        <QueryStateNotice
          state="error"
          description={apiErrorMessage(query.error, "Nie udało się pobrać przebiegu miesiąca.")}
          onRetry={() => query.refetch()}
        />
      ) : !query.isSuccess ? (
        <div className="py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>
      ) : query.data.clients.length === 0 ? (
        <p className="rounded-xl border bg-card px-3 py-6 text-center text-sm text-muted-foreground">
          W {monthLabel(month)} żaden klient nie ma kontraktów do rozliczenia.
        </p>
      ) : (
        <>
          <Summary data={query.data} month={month} />
          {tab === "clients" ? (
            <ClientsTable data={query.data} month={month} />
          ) : (
            <ReasonsList reasons={query.data.reasons} month={month} />
          )}
        </>
      )}
    </div>
  );
}

function Summary({ data, month }: { data: MonthCloseOverview; month: string }) {
  const t = data.totals;
  const done = t.clean + t.accepted;
  const pct = t.people ? Math.round((done / t.people) * 100) : 0;
  const ready = data.can_see_amounts
    ? data.clients.reduce((acc, c) => acc + (c.client_report ? 0 : Number(c.revenue_ready ?? 0)), 0)
    : null;
  const steps: { label: string; value: string; tone: StatusDotTone; note: string; href?: string }[] = [
    {
      label: "Raporty",
      value: `${t.people - t.missing} z ${t.people}`,
      tone: t.missing ? "warning" : "success",
      note: t.missing ? `${t.missing} bez raportu w poczcie` : "komplet",
    },
    {
      label: "RCP",
      value: `${done} bez uwag`,
      tone: t.decide + t.unread ? "warning" : "success",
      note: `${t.decide} do decyzji · ${t.unread} bez MD · ${t.accepted} przyjęte`,
    },
    {
      label: "Faktury kontraktorów",
      value: `${t.contractor_in_ksef} w KSeF`,
      tone: t.contractor_in_ksef >= done && done > 0 ? "success" : "neutral",
      note: "po przyjęciu RCP",
    },
    {
      label: "Faktury do klientów",
      value: `${t.client_invoice_issued} osób wystawione`,
      tone: t.client_invoice_issued ? "info" : "neutral",
      note: "Wystaw za miesiąc",
      href: issueHref(month),
    },
  ];
  return (
    <section className="rounded-xl border bg-card px-4 py-3">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
        <div className="min-w-[200px]">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{monthLabel(month)} · zamknięcie miesiąca</p>
          <p className="font-display text-lg font-semibold leading-6">
            {done} z {t.people} bez uwag <span className="text-sm font-normal text-muted-foreground">({pct}%, osoby z RCP)</span>
          </p>
        </div>
        <InlineStats
          stats={[
            { id: "people", label: "osób z RCP", value: t.people },
            { id: "decide", label: "do decyzji", value: t.decide },
            { id: "unread", label: "plik bez MD", value: t.unread },
            { id: "missing", label: "brak raportu", value: t.missing },
            ...(ready != null
              ? [{ id: "ready", label: "bez uwag, do faktur klientom", value: pln(ready.toFixed(2)) }]
              : []),
          ]}
        />
      </div>
      <ol className="mt-2.5 grid grid-cols-4 gap-2 border-t pt-2.5">
        {steps.map((s, i) => (
          <li key={s.label} className="flex min-w-0 items-start gap-2">
            <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-semibold tabular-nums">
              {i + 1}
            </span>
            <span className="min-w-0">
              <span className="block truncate text-xs font-medium">{s.label}</span>
              <StatusDot
                tone={s.tone}
                className="max-w-full"
                note={
                  s.href ? (
                    <Link href={s.href} className="text-primary hover:underline">
                      {s.note}
                    </Link>
                  ) : (
                    <span className="block truncate">{s.note}</span>
                  )
                }
              >
                {s.value}
              </StatusDot>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function ProgressBar({ c }: { c: MonthCloseClient }) {
  const seg = (n: number, cls: string, title: string) =>
    n > 0 ? <span title={`${title}: ${n}`} className={cls} style={{ width: `${(n / c.people) * 100}%` }} /> : null;
  return (
    <div className="flex items-center gap-2">
      <div className="flex h-2 w-24 overflow-hidden rounded-full bg-muted" aria-hidden>
        {seg(c.accepted, "bg-success", "przyjęte")}
        {seg(c.clean, "bg-success/60", "bez uwag")}
        {seg(c.decide, "bg-warning", "do decyzji")}
        {seg(c.unread, "bg-info", "plik bez MD")}
      </div>
      <span className="text-[11px] tabular-nums text-muted-foreground">
        {c.clean + c.accepted} z {c.people}
      </span>
    </div>
  );
}

export function clientInvoiceState(c: MonthCloseClient, amounts: boolean): { tone: StatusDotTone; label: string; note?: string } {
  const open = c.decide + c.unread + c.missing;
  if (c.client_invoice_issued > 0 && c.client_invoice_issued >= c.people)
    return { tone: "success", label: "Wystawiona", note: `${c.client_invoice_issued} osób` };
  if (c.client_invoice_issued > 0)
    return { tone: "info", label: "Wystawiona częściowo", note: `${c.client_invoice_issued} z ${c.people} osób` };
  if (c.client_invoice_ready > 0)
    return { tone: "info", label: "Do wystawienia", note: `${c.client_invoice_ready} osób przyjętych` };
  if (open === 0 && c.clean > 0)
    return { tone: "neutral", label: "Po przyjęciu RCP", note: amounts && c.revenue_ready ? pln(c.revenue_ready) : `${c.clean} bez uwag` };
  return { tone: "neutral", label: "Czeka", note: `na ${open} os.` };
}

function ClientsTable({ data, month }: { data: MonthCloseOverview; month: string }) {
  return (
    <div className="relative overflow-x-auto rounded-xl border bg-card">
      <table className="w-full min-w-[880px] table-fixed text-[13px]">
        <colgroup>
          <col className="w-[18%]" />
          <col className="w-[17%]" />
          <col className="w-[27%]" />
          <col className="w-[9%]" />
          <col className="w-[16%]" />
          <col className="w-[13%]" />
        </colgroup>
        <thead className="border-b bg-muted/40 text-left text-[11px] text-muted-foreground">
          <tr>
            <th className="px-3 py-1.5 font-medium">Klient</th>
            <th className="px-2 py-1.5 font-medium">RCP bez uwag</th>
            <th className="px-2 py-1.5 font-medium">Do decyzji</th>
            <th className="px-2 py-1.5 font-medium">Brak raportu</th>
            <th className="px-2 py-1.5 font-medium">Faktura do klienta</th>
            <th className="px-3 py-1.5 font-medium">
              <span className="sr-only">Akcje</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {data.clients.map((c) => {
            const report = c.client_report;
            const inv = clientInvoiceState(c, data.can_see_amounts);
            return (
              <tr key={c.client_id} className="hover:bg-muted/30">
                <td className="truncate px-3 py-1.5">
                  <span className="block truncate font-medium">{c.name}</span>
                  <span className="block truncate text-[11px] text-muted-foreground">
                    {report ? "raport klienta (T4T)" : `${c.people} osób`}
                  </span>
                </td>
                <td className="px-2 py-1.5">
                  {report ? (
                    <StatusDot tone={report.all ? "success" : "warning"} note={`${report.all - report.unmatched} z ${report.all} osób rozpoznanych`}>
                      {report.all ? "Raport wczytany" : "Brak raportu klienta"}
                    </StatusDot>
                  ) : (
                    <ProgressBar c={c} />
                  )}
                </td>
                <td className="truncate px-2 py-1.5">
                  {report ? (
                    report.differs ? (
                      <StatusDot tone="warning" note="godziny w raporcie ≠ faktura">
                        {report.differs} różnic
                      </StatusDot>
                    ) : (
                      <span className="text-[11px] text-muted-foreground">—</span>
                    )
                  ) : c.decide + c.unread > 0 ? (
                    <StatusDot tone={c.decide > 0 ? "warning" : "info"} note={c.top_reason ?? undefined}>
                      {c.decide + c.unread}
                      {c.unread ? ` (w tym ${c.unread} bez MD)` : ""}
                    </StatusDot>
                  ) : (
                    <span className="text-[11px] text-muted-foreground">—</span>
                  )}
                </td>
                <td className="px-2 py-1.5 tabular-nums">
                  {!report && c.missing > 0 ? (
                    <StatusDot tone="neutral">{c.missing}</StatusDot>
                  ) : (
                    <span className="text-[11px] text-muted-foreground">—</span>
                  )}
                </td>
                <td className="px-2 py-1.5">
                  {report ? (
                    <span className="text-[11px] text-muted-foreground">z raportu klienta</span>
                  ) : (
                    <StatusDot tone={inv.tone} note={inv.note}>
                      {inv.label}
                    </StatusDot>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-1.5 text-right">
                  {!report && c.client_invoice_ready > 0 ? (
                    <Link href={issueHref(month)} className="mr-3 text-xs font-medium text-primary hover:underline">
                      Wystaw
                    </Link>
                  ) : null}
                  <Link
                    href={settlementsHref(c.client_id, month, report ? { stSub: "t4t" } : {})}
                    className="inline-flex items-center text-xs font-medium text-primary hover:underline"
                  >
                    Otwórz <ChevronRight aria-hidden className="size-3.5" />
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ReasonsList({ reasons, month }: { reasons: MonthCloseReason[]; month: string }) {
  if (reasons.length === 0) {
    return (
      <p className="rounded-xl border bg-card px-3 py-6 text-center text-sm text-muted-foreground">
        W {monthLabel(month)} nic nie czeka na decyzję.
      </p>
    );
  }
  return (
    <div className="grid gap-2 md:grid-cols-2">
      {reasons.map((r) => {
        const plan = reasonPlan(r.key);
        const top = r.clients[0];
        return (
          <article key={r.key} className="flex min-w-0 flex-col gap-1.5 rounded-xl border bg-card px-3 py-2.5">
            <header className="flex items-start gap-2">
              <span className="font-display text-lg font-semibold leading-6 tabular-nums">{r.count}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium">{r.title}</span>
                <StatusDot tone={plan.tone} note={plan.hint}>
                  {plan.who}
                </StatusDot>
              </span>
            </header>
            <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px]">
              {r.clients.slice(0, 6).map((c) => (
                <Link
                  key={c.client_id}
                  href={settlementsHref(c.client_id, month, plan.sub ? { stSub: plan.sub } : {})}
                  className="text-muted-foreground hover:text-foreground hover:underline"
                >
                  {c.name} <span className="tabular-nums">{c.count}</span>
                </Link>
              ))}
              {r.clients.length > 6 ? <span className="text-muted-foreground">+{r.clients.length - 6}</span> : null}
            </p>
            <p className="truncate text-[11px] text-muted-foreground">
              {r.people.slice(0, 4).map((p, i) => (
                <span key={p.contract_id}>
                  {i ? ", " : ""}
                  <Link href={settlementsHref(p.client_id, month, { stContract: String(p.contract_id) })} className="hover:text-foreground hover:underline">
                    {p.person}
                  </Link>
                </span>
              ))}
              {r.count > 4 ? ` i ${r.count - 4} innych` : ""}
            </p>
            {top ? (
              <div className="mt-auto pt-1">
                <Link
                  href={settlementsHref(top.client_id, month, plan.sub ? { stSub: plan.sub } : {})}
                  className="inline-flex h-8 items-center rounded-md border px-3 text-xs font-medium hover:bg-muted pointer-coarse:min-h-10"
                >
                  {plan.action}: {top.name}
                </Link>
              </div>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}
