"use client";

// „Rozbieżności” w „Przebiegu miesiąca” (kontrola miesiąca, 0784, decyzja
// Artura 25.11.2026): faktura do klienta a faktura konsultanta z KSeF per osoba
// i miesiąc — inne godziny, brak faktury po jednej ze stron, więcej godzin niż
// dni roboczych. Sprawy liczy nocny przebieg; Finanse zaznaczają „Wyjaśnione”
// (z powodem) albo „Do korekty”. Dane: GET /api/finance/settlements/month-check.

import Link from "next/link";
import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useMonthCheck,
  useMonthCheckDecision,
  type MonthCheckCase,
  type MonthCheckState,
  type MonthCheckView,
} from "@/lib/api/client-settlements";
import { cn } from "@/lib/utils";

import { money, monthLabel, pln, shortDay } from "../settlements/format";

type Filter = "open" | "explained" | "closed" | "all";

const STATE_LOOK: Record<MonthCheckState, { tone: StatusDotTone; label: string }> = {
  new: { tone: "warning", label: "Nowa" },
  to_correct: { tone: "danger", label: "Do korekty" },
  explained: { tone: "success", label: "Wyjaśniona" },
  closed: { tone: "neutral", label: "Zamknięta sama" },
};

/** Pominięcia przebiegu — ludzkie nazwy kluczy z `rules.py`. */
const SKIP_LABELS: Record<string, string> = {
  client_without_names: "klient bez nazwisk na fakturze",
  sale_waits_for_buyer: "faktura czeka na nabywcę",
  parallel_contracts: "dwa kontrakty w miesiącu",
  no_ksef_invoices: "osoba bez faktur w KSeF",
  not_comparable: "bez stawki godzinowej",
  outside_contracts: "poza kontraktami",
  waiting_for_deadline: "czeka do 15. dnia",
};

function hours(value: string | null | undefined): string {
  if (value == null) return "–";
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toLocaleString("pl-PL", { maximumFractionDigits: 2 })} h` : "–";
}

export function caseDetail(c: MonthCheckCase): string {
  const d = c.details;
  switch (c.kind) {
    case "hours_mismatch":
      return `klient ${hours(d.client_hours)} · konsultant ok. ${hours(d.contractor_hours)}`;
    case "cost_without_sale":
      return "faktura konsultanta jest, u klienta tej osoby nie ma";
    case "sale_without_cost":
      return `klient ${hours(d.client_hours)}, faktury konsultanta brak`;
    case "over_working_days":
      return `klient ${hours(d.client_hours)} przy ${d.working_days ?? "?"} dniach roboczych (${hours(d.limit_hours)})`;
  }
}

export function matchesState(filter: Filter, state: MonthCheckState): boolean {
  if (filter === "all") return true;
  if (filter === "open") return state === "new" || state === "to_correct";
  return state === filter;
}

function settlementHref(c: MonthCheckCase): string | null {
  if (!c.client_id) return null;
  const params = new URLSearchParams({ view: "settlements", stClient: String(c.client_id), stMonth: c.month });
  if (c.contract_id) params.set("stContract", String(c.contract_id));
  return `/finance?${params.toString()}`;
}

function Summary({ view }: { view: MonthCheckView }) {
  const s = view.summary;
  const skipped = Object.entries(s.skipped ?? {}).filter(([, n]) => n > 0);
  return (
    <section data-tour="finance.month-close.diff-summary" className="rounded-xl border bg-card px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
        {monthLabel(view.month)} · faktura do klienta a faktura konsultanta
      </p>
      {view.checked_at == null ? (
        <p className="mt-1.5 text-sm text-muted-foreground">
          Tego miesiąca automat jeszcze nie sprawdzał (sprawdza trzy ostatnie zakończone miesiące, co noc).
        </p>
      ) : (
        <>
          <InlineStats
            className="mt-1.5"
            stats={[
              {
                id: "matched",
                label: "osobo-miesięcy się zgadza",
                value: s.person_months != null ? `${s.matched ?? 0} z ${s.person_months}` : "–",
              },
              { id: "cases", label: "rozbieżności", value: view.amounts && s.cases_amount ? `${s.cases} · ${pln(s.cases_amount)}` : s.cases },
              { id: "open", label: "otwartych", value: view.amounts && s.open_amount ? `${s.open} · ${pln(s.open_amount)}` : s.open },
              { id: "explained", label: "wyjaśnionych", value: s.by_state?.explained ?? 0 },
            ]}
          />
          <p className="mt-1.5 text-[11px] text-muted-foreground">
            Sprawdzone {shortDay(view.checked_at)}
            {view.waits_until ? ` · brak faktury po jednej stronie liczy się od ${shortDay(view.waits_until)}` : ""}
            {skipped.length ? ` · bez porównania: ${skipped.map(([k, n]) => `${SKIP_LABELS[k] ?? k} ${n}`).join(", ")}` : ""}
            {s.overtime_confirmed ? ` · nadgodziny potwierdzone fakturą konsultanta: ${s.overtime_confirmed}` : ""}
            {s.foreign_currency ? ` · kwoty w złotych; ${s.foreign_currency} spraw w innej walucie poza sumą` : ""}
          </p>
        </>
      )}
    </section>
  );
}

function ExplainDialog({
  row,
  onClose,
  onSave,
  pending,
  error,
}: {
  row: MonthCheckCase | null;
  onClose: () => void;
  onSave: (reason: string) => void;
  pending: boolean;
  error: string | null;
}) {
  const [reason, setReason] = useState("");
  const tooShort = reason.trim().length < 3;
  return (
    <AppModal
      open={row != null}
      onOpenChange={(open) => {
        if (!open) {
          setReason("");
          onClose();
        }
      }}
      title="Wyjaśnione — dlaczego to się zgadza?"
      description={row ? `${row.person} · ${row.client} · ${monthLabel(row.month)}` : undefined}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={pending}>
            Anuluj
          </Button>
          <Button onClick={() => onSave(reason.trim())} disabled={tooShort || pending}>
            Zapisz
          </Button>
        </>
      }
    >
      <Textarea
        aria-label="Powód"
        value={reason}
        maxLength={1000}
        rows={3}
        placeholder="np. klient zaakceptował 15 MD, różnicę rozliczamy w listopadzie"
        onChange={(e) => setReason(e.target.value)}
      />
      {error ? <p className="mt-1.5 text-xs text-destructive">{error}</p> : null}
    </AppModal>
  );
}

export function MonthCheckPanel({ month }: { month: string }) {
  const query = useMonthCheck(month);
  const decision = useMonthCheckDecision(month);
  const [filter, setFilter] = useState<Filter>("open");
  const [explaining, setExplaining] = useState<MonthCheckCase | null>(null);

  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(query.error, "Nie udało się pobrać rozbieżności.")}
        onRetry={() => query.refetch()}
      />
    );
  }
  if (!query.isSuccess) return <div className="py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>;

  const view = query.data;
  const rows = view.cases.filter((c) => matchesState(filter, c.state));
  const count = (f: Filter) => view.cases.filter((c) => matchesState(f, c.state)).length;
  const decisionError = decision.isError ? apiErrorMessage(decision.error, "Nie udało się zapisać.") : null;

  return (
    <div className="space-y-2">
      <Summary view={view} />
      <div className="flex flex-wrap items-center gap-1">
        {(
          [
            ["open", "Otwarte"],
            ["explained", "Wyjaśnione"],
            ["closed", "Zamknięte same"],
            ["all", "Wszystkie"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            aria-pressed={filter === key}
            onClick={() => setFilter(key)}
            className={cn(
              "shrink-0 whitespace-nowrap rounded-md border px-2.5 py-1 text-xs font-medium pointer-coarse:min-h-10",
              filter === key ? "border-primary bg-primary/10 text-foreground" : "border-border bg-card text-muted-foreground",
            )}
          >
            {label} <span className="tabular-nums">{count(key)}</span>
          </button>
        ))}
        {decisionError && !explaining ? <span className="ml-2 text-xs text-destructive">{decisionError}</span> : null}
      </div>
      <section className="relative overflow-x-auto rounded-xl border bg-card">
        <table className="w-full min-w-[880px] table-fixed text-[13px]">
          <colgroup>
            <col className="w-[20%]" />
            <col className="w-[27%]" />
            <col className="w-[21%]" />
            <col className="w-[11%]" />
            <col className="w-[9%]" />
            <col className="w-[12%]" />
          </colgroup>
          <thead className="border-b bg-muted/40 text-left text-[11px] text-muted-foreground">
            <tr>
              <th className="px-3 py-1.5 font-medium">Osoba · klient</th>
              <th className="px-2 py-1.5 font-medium">Co się nie zgadza</th>
              <th className="px-2 py-1.5 font-medium">Faktury</th>
              <th className="px-2 py-1.5 text-right font-medium">Kwota</th>
              <th className="px-2 py-1.5 font-medium">Stan</th>
              <th className="px-3 py-1.5 text-right font-medium">Akcje</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-5 text-center text-muted-foreground">
                  {view.cases.length === 0 ? "Bez rozbieżności w tym miesiącu." : "Nic w tym filtrze."}
                </td>
              </tr>
            ) : (
              rows.map((c) => {
                const href = settlementHref(c);
                const look = STATE_LOOK[c.state];
                const sales = c.details.sales_invoices ?? [];
                const costs = c.details.contractor_invoices ?? [];
                return (
                  <tr key={c.id} className="align-top">
                    <td className="px-3 py-1.5">
                      <div className="truncate font-medium">
                        {href ? (
                          <Link href={href} className="hover:underline">
                            {c.person}
                          </Link>
                        ) : (
                          c.person
                        )}
                      </div>
                      <div className="truncate text-[11px] text-muted-foreground">{c.client || "—"}</div>
                    </td>
                    <td className="px-2 py-1.5">
                      <div>{c.kind_label}</div>
                      <div className="text-[11px] text-muted-foreground">
                        {caseDetail(c)}
                        {c.data_issue_label ? <span className="text-warning-muted-foreground"> · {c.data_issue_label}</span> : null}
                      </div>
                    </td>
                    <td className="px-2 py-1.5 text-[11px] leading-4">
                      <div className="truncate" title={sales.join(", ")}>
                        <span className="text-muted-foreground">klient:</span> {sales.join(", ") || "brak"}
                      </div>
                      <div className="truncate" title={costs.map((d) => d.number).join(", ")}>
                        <span className="text-muted-foreground">konsultant:</span> {costs.map((d) => d.number).join(", ") || "brak"}
                      </div>
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{c.amount != null ? money(c.amount, c.currency) : "–"}</td>
                    <td className="px-2 py-1.5">
                      <StatusDot tone={look.tone} note={c.reason ?? undefined}>
                        {look.label}
                      </StatusDot>
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      {c.state === "new" || c.state === "to_correct" ? (
                        <div className="flex flex-col items-end gap-1">
                          <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={() => setExplaining(c)}>
                            Wyjaśnione
                          </Button>
                          {c.state === "new" ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2 text-xs"
                              disabled={decision.isPending}
                              onClick={() => decision.mutate({ id: c.id, action: "to_correct" })}
                            >
                              Do korekty
                            </Button>
                          ) : null}
                        </div>
                      ) : c.state === "explained" ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2 text-xs"
                          disabled={decision.isPending}
                          onClick={() => decision.mutate({ id: c.id, action: "new" })}
                        >
                          Cofnij
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </section>
      <ExplainDialog
        row={explaining}
        pending={decision.isPending}
        error={explaining ? decisionError : null}
        onClose={() => {
          decision.reset();
          setExplaining(null);
        }}
        onSave={(reason) => {
          if (!explaining) return;
          decision.mutate(
            { id: explaining.id, action: "explained", reason },
            { onSuccess: () => setExplaining(null) },
          );
        }}
      />
    </div>
  );
}
