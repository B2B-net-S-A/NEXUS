"use client";

import Link from "next/link";
import { useState } from "react";

import { InlineStats, QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useSetVatAccounts,
  useVatRegisters,
  type VatIssue,
  type VatRegisters,
  type VatRow,
} from "@/lib/api/accounting-vat";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard, useAccounting } from "./AccountingShell";
import { datePl, gr } from "./ledger-model";
import { dueLabel, fieldsLabel, issueLink, rowGroups, taxIdLabel } from "./vat-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const EMPTY = "px-3.5 py-4 text-[13px] text-muted-foreground";
/** Rejestr pokazuje najpierw tyle wierszy — miesiąc ma ich setki. */
export const ROWS_SHOWN = 50;

/**
 * Księgowość → VAT (K5a): rejestry sprzedaży i zakupu miesiąca z nagłówka —
 * z zatwierdzonych FVS i FVZ, z sumami grup (pola JPK_V7M) i listą „do
 * sprawdzenia” (faktura z KSeF bez dokumentu, bufor, kolejka kosztów, zapisy na
 * kontach VAT spoza rejestru). JPK_V7M i rozliczenie VAT — etap K5b.
 */
export function VatView() {
  const { config, period } = useAccounting();
  const open = config.modules.find((module) => module.key === "vat")?.open ?? false;
  const registers = useVatRegisters(period.year, period.month, open);
  if (!open) {
    return (
      <p className="rounded-md border border-border bg-muted/40 px-3.5 py-2 text-[13px] text-muted-foreground">
        Rejestry VAT są w module „VAT i JPK” — włącza go administrator w Ustawieniach.
      </p>
    );
  }
  if (registers.isError) return <QueryStateNotice state="error" onRetry={() => registers.refetch()} />;
  if (!registers.isSuccess) return <p className="text-sm text-muted-foreground">Wczytywanie rejestrów VAT…</p>;
  const data = registers.data;
  const due = dueLabel(data.summary.due);
  return (
    <div className="space-y-3.5">
      <InlineStats
        stats={[
          { id: "output", label: "VAT należny", value: `${gr(data.summary.output_vat)} zł` },
          { id: "input", label: "VAT naliczony", value: `${gr(data.summary.input_vat)} zł` },
          { id: "due", label: due.label, value: due.value },
          { id: "rows", label: "Faktury w rejestrach", value: `${data.sales.length} / ${data.purchases.length}` },
        ]}
      />
      {data.payroll_hidden ? (
        <p className="rounded-md border border-border bg-muted/40 px-3.5 py-2 text-[13px] text-muted-foreground">
          Bez faktur osób zespołu — pełny rejestr zakupu i saldo widzi osoba z Płacami.
        </p>
      ) : null}
      <div className="grid gap-3.5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <SummaryCard data={data} />
        <div className="space-y-3.5">
          <IssuesCard issues={data.issues} year={data.year} month={data.month} />
          <AccountsCard data={data} />
        </div>
      </div>
      <RegisterCard
        title="Rejestr sprzedaży"
        aside="FVS zatwierdzone · data sprzedaży (korekta — wystawienia)"
        rows={data.sales}
        party="Nabywca"
        empty="W tym miesiącu nie ma zatwierdzonych faktur sprzedaży."
      />
      <RegisterCard
        title="Rejestr zakupu"
        aside="FVZ z VAT do odliczenia · data wpływu do KSeF"
        rows={data.purchases}
        party="Dostawca"
        empty="W tym miesiącu nie ma zatwierdzonych faktur zakupu z VAT do odliczenia."
      />
    </div>
  );
}

function SummaryCard({ data }: { data: VatRegisters }) {
  const due = dueLabel(data.summary.due);
  return (
    <SectionCard title="Do deklaracji" aside="pola JPK_V7M · bez nadwyżki z poprzedniego okresu">
      {data.summary.groups.length ? (
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-border/70">
              <th className={cn(CALM_HEAD, "px-3.5 py-2 text-left")}>Grupa</th>
              <th className={cn(CALM_HEAD, "w-[24%] px-2 py-2 text-left")}>Pola</th>
              <th className={cn(CALM_HEAD, "w-[18%] px-2 py-2 text-right")}>Netto</th>
              <th className={cn(CALM_HEAD, "w-[16%] py-2 pl-2 pr-3.5 text-right")}>VAT</th>
            </tr>
          </thead>
          <tbody>
            {data.summary.groups.map((group) => (
              <tr key={`${group.register}:${group.key}`} className={cn(CALM_ROW, "last:border-0")}>
                <td className="min-w-0 px-3.5 py-1.5">
                  <span className="block truncate">{group.label}</span>
                  <span className={CALM_SUBLINE}>{group.register === "sales" ? "sprzedaż" : "zakup"}</span>
                </td>
                <td className="px-2 py-1.5 text-[12px] tabular-nums text-muted-foreground">{fieldsLabel(group)}</td>
                <td className={cn(CALM_AMOUNT, "px-2 py-1.5 text-right")}>{gr(group.net)}</td>
                <td className={cn(CALM_AMOUNT, "py-1.5 pl-2 pr-3.5 text-right")}>{group.vat_field ? gr(group.vat) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className={EMPTY}>W tym miesiącu nie ma zatwierdzonych faktur w rejestrach.</p>
      )}
      <div className="flex flex-wrap gap-x-5 gap-y-1 border-t border-border/70 px-3.5 py-2.5 text-[13px] tabular-nums">
        <span>
          VAT należny <b className="font-semibold">{gr(data.summary.output_vat)} zł</b>
        </span>
        <span>
          VAT naliczony <b className="font-semibold">{gr(data.summary.input_vat)} zł</b>
        </span>
        <span>
          {due.label} <b className="font-semibold">{due.value}</b>
        </span>
      </div>
    </SectionCard>
  );
}

function IssuesCard({ issues, year, month }: { issues: readonly VatIssue[]; year: number; month: number }) {
  return (
    <SectionCard title="Do sprawdzenia" aside={issues.length ? `${issues.length} ${issues.length === 1 ? "lista" : "listy"}` : undefined}>
      {issues.length ? (
        <div className="divide-y divide-border/70">
          {issues.map((issue) => (
            <details key={issue.kind} className="px-3.5 py-2 text-[13px]">
              <summary
                className={cn(
                  "cursor-pointer font-medium",
                  issue.kind === "rates" || issue.kind === "missing_sales" ? "text-destructive-text" : "text-warning-muted-foreground",
                )}
              >
                {issue.label}: {issue.count}
              </summary>
              <ul className="mt-1 space-y-0.5 text-[12px]">
                {issue.items.map((item, index) => (
                  <li key={`${item.number}:${index}`} className="min-w-0">
                    <span className="font-medium">{item.number}</span>
                    {item.detail ? <span className="text-muted-foreground"> — {item.detail}</span> : null}
                    {item.amount != null ? <span className="tabular-nums text-muted-foreground"> · {gr(item.amount)} zł</span> : null}
                  </li>
                ))}
                {issue.count > issue.items.length ? (
                  <li className="text-muted-foreground">i {issue.count - issue.items.length} więcej</li>
                ) : null}
              </ul>
              <Link className="mt-1 inline-block text-[12px] text-primary hover:underline" href={issueLink(issue.kind, year, month).href}>
                {issueLink(issue.kind, year, month).label} →
              </Link>
            </details>
          ))}
        </div>
      ) : (
        <p className="px-3.5 py-3 text-[13px] text-muted-foreground">
          Rejestry są pełne: każda faktura z KSeF tego miesiąca ma zatwierdzony dokument.
        </p>
      )}
    </SectionCard>
  );
}

function AccountsCard({ data }: { data: VatRegisters }) {
  const { showToast } = useToast();
  const save = useSetVatAccounts();
  const [input, setInput] = useState(data.accounts.input_account);
  const changed = input.trim() !== data.accounts.input_account;
  return (
    <SectionCard title="Konta VAT">
      <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 px-3.5 py-2.5 text-[13px]">
        <dt className="text-muted-foreground">VAT należny</dt>
        <dd className="tabular-nums">{data.accounts.output_account} · z Ustawień (sprzedaż)</dd>
        <dt className="text-muted-foreground">Środki trwałe (K_40/K_41)</dt>
        <dd className="tabular-nums">Wn {data.accounts.intake_account}</dd>
        <dt className="self-center text-muted-foreground">VAT naliczony</dt>
        <dd>
          {data.can_edit_accounts ? (
            <form
              className="flex items-center gap-1.5"
              onSubmit={(event) => {
                event.preventDefault();
                save.mutate(
                  { input_account: input.trim() },
                  {
                    onSuccess: () => showToast("Zapisano konto VAT naliczonego."),
                    onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać konta."), "error"),
                  },
                );
              }}
            >
              <input
                className={cn(CONTROL, "w-24 tabular-nums")}
                aria-label="Konto VAT naliczonego"
                value={input}
                onChange={(event) => setInput(event.target.value)}
              />
              <Button size="sm" type="submit" variant="outline" disabled={!changed} loading={save.isPending}>
                Zapisz
              </Button>
            </form>
          ) : (
            <span className="tabular-nums">{data.accounts.input_account}</span>
          )}
        </dd>
      </dl>
    </SectionCard>
  );
}

function RegisterCard({
  title,
  aside,
  rows,
  party,
  empty,
}: {
  title: string;
  aside: string;
  rows: readonly VatRow[];
  party: string;
  empty: string;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, ROWS_SHOWN);
  return (
    <SectionCard title={`${title} · ${rows.length}`} aside={aside}>
      {rows.length ? (
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b border-border/70">
              <th className={cn(CALM_HEAD, "w-[24%] px-3.5 py-2 text-left")}>Faktura</th>
              <th className={cn(CALM_HEAD, "w-[11%] px-2 py-2 text-left")}>Data</th>
              <th className={cn(CALM_HEAD, "px-2 py-2 text-left")}>{party}</th>
              <th className={cn(CALM_HEAD, "w-[12%] px-2 py-2 text-left")}>Grupa</th>
              <th className={cn(CALM_HEAD, "w-[13%] px-2 py-2 text-right")}>Netto</th>
              <th className={cn(CALM_HEAD, "w-[12%] py-2 pl-2 pr-3.5 text-right")}>VAT</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr key={row.document_id} className={cn(CALM_ROW, "last:border-0")}>
                <td className="min-w-0 px-3.5 py-1.5">
                  <span className="block truncate font-medium">{row.number}</span>
                  <span className={cn(CALM_SUBLINE, "block truncate")} title={row.ksef_number ?? undefined}>
                    {row.ksef_number ?? "bez numeru KSeF"}
                  </span>
                </td>
                <td className="px-2 py-1.5 text-[13px] tabular-nums">
                  {datePl(row.date)}
                  {row.correction ? <span className={CALM_SUBLINE}>korekta</span> : null}
                </td>
                <td className="min-w-0 px-2 py-1.5">
                  <span className="block truncate">{row.counterparty}</span>
                  <span className={CALM_SUBLINE}>{taxIdLabel(row)}</span>
                </td>
                <td className={cn("px-2 py-1.5 text-[13px]", row.problem ? "text-destructive-text" : "")} title={row.problem ?? undefined}>
                  {rowGroups(row)}
                </td>
                <td className={cn(CALM_AMOUNT, "px-2 py-1.5 text-right")}>{gr(row.net)}</td>
                <td className={cn(CALM_AMOUNT, "py-1.5 pl-2 pr-3.5 text-right")}>{gr(row.vat)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className={EMPTY}>{empty}</p>
      )}
      {rows.length > shown.length ? (
        <div className="border-t border-border/70 px-3.5 py-2">
          <Button size="sm" variant="outline" onClick={() => setAll(true)}>
            Pokaż wszystkie ({rows.length})
          </Button>
        </div>
      ) : null}
    </SectionCard>
  );
}
