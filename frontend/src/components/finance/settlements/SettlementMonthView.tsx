"use client";

// Miesiąc klienta: osoby, RCP, MD i kwoty (roadmapa E1.6). Przyjęcie zbiorcze
// bierze tylko RCP bez uwag; reszta przez kartę osoby.
import { useMemo, useState } from "react";
import { Search } from "lucide-react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useAcceptBatch,
  useSettlementMonth,
  type SettlementFilter,
  type SettlementRow,
} from "@/lib/api/client-settlements";
import { cn } from "@/lib/utils";

import { ClientDocumentsPanel } from "./ClientDocumentsPanel";
import { CLIENT_INVOICE, CONTRACTOR_INVOICE, FILTERS, STATUS, matchesFilter, mdText, monthLabel, pctText, pln } from "./format";

interface SettlementMonthViewProps {
  clientId: number;
  month: string;
  canWrite: boolean;
  onOpen: (contractId: number) => void;
}

export function SettlementMonthView({ clientId, month, canWrite, onOpen }: SettlementMonthViewProps) {
  const query = useSettlementMonth(clientId, month);
  const batch = useAcceptBatch();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showSuccess, showError } = useToast();
  const [filter, setFilter] = useState<SettlementFilter>("todo");
  const [search, setSearch] = useState("");

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return (query.data?.rows ?? []).filter(
      (r) =>
        matchesFilter(filter, r.status, r.contractor_invoice === "differs") &&
        (!needle || r.person.toLowerCase().includes(needle) || (r.order_number ?? "").toLowerCase().includes(needle)),
    );
  }, [query.data, filter, search]);

  if (query.isError) {
    return <QueryStateNotice state="error" description={apiErrorMessage(query.error, "Nie udało się pobrać rozliczeń miesiąca.")} onRetry={() => query.refetch()} />;
  }
  if (!query.isSuccess) {
    return <div className="py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>;
  }
  const data = query.data;

  async function acceptBatch() {
    const ok = await askConfirm({
      title: `Przyjąć ${data.batch_ready} RCP bez uwag?`,
      description: `MD zejdą z zamówień za ${monthLabel(month)}, a konsultanci dostaną informację, że mogą wystawić fakturę.`,
      confirmLabel: "Przyjmij",
    });
    if (!ok) return;
    try {
      const res = await batch.mutateAsync({ clientId, month });
      showSuccess(`Przyjęto ${res.accepted} RCP.`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się przyjąć RCP."));
    }
  }

  return (
    <div className="space-y-2.5">
      {confirmDialog}
      <ClientDocumentsPanel clientId={clientId} month={month} />
      <div className="flex flex-wrap items-center gap-1">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={filter === f.key}
            onClick={() => setFilter(f.key)}
            className={cn(
              "rounded-md border px-2.5 py-1 text-xs font-medium pointer-coarse:min-h-10",
              filter === f.key ? "border-primary bg-primary/10 text-foreground" : "border-border bg-card text-muted-foreground",
            )}
          >
            {f.label} <span className="tabular-nums">{data.counts[f.key] ?? 0}</span>
          </button>
        ))}
        <div className="relative ml-auto w-48">
          <Search aria-hidden className="absolute left-2 top-2 size-3.5 text-muted-foreground" />
          <Input
            aria-label="Szukaj osoby albo zamówienia"
            placeholder="Szukaj osoby"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 pl-7 text-xs"
          />
        </div>
        {canWrite ? (
          <Button size="sm" disabled={data.batch_ready === 0 || batch.isPending} onClick={acceptBatch}>
            Przyjmij RCP bez uwag ({data.batch_ready})
          </Button>
        ) : null}
      </div>
      {data.rows.length === 0 ? (
        <p className="rounded-xl border bg-card px-3 py-6 text-center text-sm text-muted-foreground">
          {data.client_name} nie ma w {monthLabel(month)} aktywnych kontraktów.
        </p>
      ) : (
        <MonthTable rows={rows} showAmounts={data.can_see_amounts} onOpen={onOpen} />
      )}
    </div>
  );
}

interface MonthTableProps {
  rows: SettlementRow[];
  showAmounts: boolean;
  onOpen: (contractId: number) => void;
}

function MonthTable({ rows, showAmounts, onOpen }: MonthTableProps) {
  return (
    <div className="overflow-x-auto rounded-xl border bg-card">
      <table className="w-full min-w-[880px] table-fixed text-[13px]">
        <colgroup>
          <col className="w-[19%]" />
          <col className="w-[12%]" />
          <col className="w-[8%]" />
          <col className="w-[9%]" />
          <col className="w-[17%]" />
          {showAmounts ? <col className="w-[11%]" /> : null}
          {showAmounts ? <col className="w-[10%]" /> : null}
          <col className="w-[14%]" />
        </colgroup>
        <thead className="border-b bg-muted/40 text-left text-[11px] text-muted-foreground">
          <tr>
            <th className="px-3 py-1.5 font-medium">Osoba</th>
            <th className="px-2 py-1.5 font-medium">RCP</th>
            <th className="px-2 py-1.5 text-right font-medium">MD</th>
            <th className="px-2 py-1.5 text-right font-medium">Zostanie MD</th>
            <th className="px-2 py-1.5 font-medium">Faktura kontraktora</th>
            {showAmounts ? <th className="px-2 py-1.5 text-right font-medium">Netto</th> : null}
            {showAmounts ? <th className="px-2 py-1.5 text-right font-medium">Marża</th> : null}
            <th className="px-3 py-1.5 font-medium">Do klienta</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.length === 0 ? (
            <tr>
              <td colSpan={showAmounts ? 8 : 6} className="px-3 py-6 text-center text-muted-foreground">
                Nic w tym filtrze.
              </td>
            </tr>
          ) : (
            rows.map((r) => (
              <tr key={r.contract_id} className="hover:bg-muted/30">
                <td className="truncate px-3 py-1.5">
                  <button type="button" onClick={() => onOpen(r.contract_id)} className="block max-w-full truncate text-left font-medium hover:underline">
                    {r.person}
                  </button>
                  <span className="block truncate text-[11px] tabular-nums text-muted-foreground">
                    {r.order_number ?? <span className="text-warning-muted-foreground">Brak numeru zamówienia</span>}
                  </span>
                </td>
                <td className="px-2 py-1.5">
                  <StatusDot tone={STATUS[r.status].tone} note={r.issues ?? undefined}>
                    {STATUS[r.status].label}
                  </StatusDot>
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  {mdText(r.md_regular)}
                  {r.md_extra && Number(r.md_extra) > 0 ? (
                    <span className="block text-[11px] text-muted-foreground">+{mdText(r.md_extra)} nadg.</span>
                  ) : null}
                </td>
                <td
                  className={cn(
                    "px-2 py-1.5 text-right tabular-nums",
                    r.md_remaining_after != null && Number(r.md_remaining_after) <= 21 && "font-medium text-destructive",
                  )}
                >
                  {mdText(r.md_remaining_after)}
                </td>
                <td className="px-2 py-1.5">
                  <StatusDot tone={CONTRACTOR_INVOICE[r.contractor_invoice].tone}>
                    {CONTRACTOR_INVOICE[r.contractor_invoice].label}
                  </StatusDot>
                </td>
                {showAmounts ? <td className="px-2 py-1.5 text-right tabular-nums">{pln(r.amount_cost)}</td> : null}
                {showAmounts ? (
                  <td className="px-2 py-1.5 text-right tabular-nums">
                    {pln(r.margin)}
                    {pctText(r.margin_pct) ? <span className="block text-[11px] text-muted-foreground">{pctText(r.margin_pct)}</span> : null}
                    {r.integration_cost ? (
                      <span className="block text-[11px] text-muted-foreground">w tym −{pln(r.integration_cost)} integracja</span>
                    ) : null}
                  </td>
                ) : null}
                <td className="px-3 py-1.5">
                  <StatusDot tone={CLIENT_INVOICE[r.client_invoice].tone}>{CLIENT_INVOICE[r.client_invoice].label}</StatusDot>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
