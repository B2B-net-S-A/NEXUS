"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCheck, FilePlus2 } from "lucide-react";

import { InlineStats, type InlineStat } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { SETTLEMENT_TONE, amountWithBasis, documentCell, queueStatus } from "@/components/hr/me/settlement-format";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useApproveReady,
  useApproveSettlement,
  usePrepareMonth,
  useSettlementQueue,
  type SettlementQueue,
  type SettlementRow,
} from "@/lib/api/hr-settlements";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDayMonthPl } from "@/lib/date-pl";
import { writeUrlParams } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";

import { SettlementDetailDialog } from "./SettlementDetailDialog";

/** Liczby nad kolejką (M3): osoby, do zapłaty, rozbieżności, brak faktury, zlecenia bez godzin. */
export function queueStats(data: SettlementQueue): InlineStat[] {
  const stats = data.stats;
  const out: InlineStat[] = [
    { id: "people", label: "osób", value: stats.people ?? 0 },
    { id: "to-pay", label: "do zapłaty", value: stats.to_pay ?? 0 },
    { id: "ready", label: "zgodne do zatwierdzenia", value: stats.ready ?? 0 },
  ];
  if (stats.mismatch) out.push({ id: "mismatch", label: "rozbieżność", value: stats.mismatch });
  if (stats.awaiting_document) {
    out.push({ id: "awaiting", label: "czekają na fakturę", value: stats.awaiting_document });
  }
  if (stats.hours_unconfirmed) {
    out.push({
      id: "hours",
      label: "zlecenie bez potwierdzonych godzin",
      value: stats.hours_unconfirmed,
    });
  }
  if (stats.paid) out.push({ id: "paid", label: "opłacone", value: stats.paid });
  return out;
}

function QueueTable({
  rows,
  onOpen,
  onApprove,
  approving,
}: {
  rows: SettlementRow[];
  onOpen: (id: number) => void;
  onApprove: (row: SettlementRow) => void;
  approving: boolean;
}) {
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
      <Table density="compact" className="min-w-[760px]">
        <TableHeader>
          <TableRow>
            <TableHead className={CALM_HEAD}>Osoba</TableHead>
            <TableHead className={CALM_HEAD}>Forma</TableHead>
            <TableHead className={`${CALM_HEAD} text-right`}>Kwota z NEXUSA</TableHead>
            <TableHead className={CALM_HEAD}>Dokument</TableHead>
            <TableHead className={CALM_HEAD}>Stan</TableHead>
            <TableHead className={CALM_HEAD}>Termin</TableHead>
            <TableHead className={CALM_HEAD}>
              <span className="sr-only">Akcje</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id} className={CALM_ROW}>
              <TableCell className="max-w-[220px]">
                <button
                  type="button"
                  className="block truncate text-left font-medium text-foreground hover:underline"
                  onClick={() => onOpen(row.id)}
                >
                  {row.name}
                </button>
                {row.mine ? <span className={CALM_SUBLINE}>Twoje — decyduje ktoś inny</span> : null}
              </TableCell>
              <TableCell className="text-sm text-foreground">{row.form_short}</TableCell>
              <TableCell className={`${CALM_AMOUNT} text-sm text-foreground`}>
                {amountWithBasis(row.expected_amount, row.currency, row.amount_basis)}
              </TableCell>
              <TableCell className="max-w-[220px] text-sm">
                <span className="block truncate text-foreground">{documentCell(row)}</span>
              </TableCell>
              <TableCell>
                <StatusDot tone={SETTLEMENT_TONE[row.status]}>{queueStatus(row)}</StatusDot>
                {row.override && !row.override.confirmed_by_name ? (
                  <span className={CALM_SUBLINE}>uznanie czeka na drugą osobę</span>
                ) : null}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {row.due_on ? formatDayMonthPl(row.due_on) : <span className={CALM_EMPTY}>—</span>}
              </TableCell>
              <TableCell className="text-right">
                {row.can_approve ? (
                  <Button size="sm" onClick={() => onApprove(row)} disabled={approving}>
                    Zatwierdź
                  </Button>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => onOpen(row.id)}>
                    Szczegóły
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/**
 * „Ludzie → Płace → miesiąc → Rozliczenia” (M3): jedna kolejka dla trzech
 * form — B2B z fakturą z KSeF, zlecenie z potwierdzenia godzin, UoP z danymi
 * do listy płac. Rozbieżności i brakujące faktury na górze.
 */
export function SettlementsQueue({ year, month }: { year: number; month: number }) {
  const query = useSettlementQueue(year, month);
  const approve = useApproveSettlement();
  const approveReady = useApproveReady(year, month);
  const prepare = usePrepareMonth(year, month);
  const { showToast } = useToast();
  const params = useSearchParams();
  const fromUrl = Number(params.get("settlement"));
  const [openId, setOpenId] = useState<number | null>(
    Number.isInteger(fromUrl) && fromUrl > 0 ? fromUrl : null,
  );

  const open = (id: number | null) => {
    setOpenId(id);
    writeUrlParams({ settlement: id == null ? null : String(id) });
  };

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (state === "loading") {
    return <p className="text-sm text-muted-foreground">Wczytywanie rozliczeń…</p>;
  }
  if (state !== "ready" || !query.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        description={
          state === "not_found"
            ? "Moduł rozliczeń nie jest jeszcze włączony."
            : state === "forbidden"
              ? "Rozliczenia widzą Płace."
              : "Nie udało się wczytać rozliczeń."
        }
        onRetry={() => query.refetch()}
      />
    );
  }
  const data = query.data;
  if (data.period_status !== "closed") {
    return (
      <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
        Rozliczenia powstają przy zamknięciu miesiąca — z zamrożonych kwot każdej osoby.
      </div>
    );
  }
  const readyCount = data.rows.filter((row) => row.can_approve).length;

  const approveRow = (row: SettlementRow) =>
    approve.mutate(row.id, {
      onSuccess: () => showToast(`${row.name}: zatwierdzone do zapłaty`, "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zatwierdzić."), "error"),
    });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <InlineStats id="settlements-stats" stats={queueStats(data)} />
        <div className="flex flex-wrap items-center gap-2">
          {data.missing > 0 ? (
            <Button
              size="sm"
              variant="outline"
              disabled={prepare.isPending}
              onClick={() =>
                prepare.mutate(undefined, {
                  onSuccess: (result) => showToast(`Założono rozliczenia: ${result.created}`, "success"),
                  onError: (err) =>
                    showToast(apiErrorMessage(err, "Nie udało się założyć rozliczeń."), "error"),
                })
              }
            >
              <FilePlus2 className="h-4 w-4" aria-hidden />
              Załóż rozliczenia ({data.missing})
            </Button>
          ) : null}
          {readyCount > 0 ? (
            <Button
              size="sm"
              disabled={approveReady.isPending}
              onClick={() =>
                approveReady.mutate(undefined, {
                  onSuccess: (result) =>
                    showToast(`Zatwierdzono do zapłaty: ${result.approved}`, "success"),
                  onError: (err) =>
                    showToast(apiErrorMessage(err, "Nie udało się zatwierdzić."), "error"),
                })
              }
            >
              <CheckCheck className="h-4 w-4" aria-hidden />
              Zatwierdź zgodne ({readyCount})
            </Button>
          ) : null}
        </div>
      </div>
      {data.rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          W tym miesiącu nikt nie ma kwoty do rozliczenia.
        </div>
      ) : (
        <QueueTable
          rows={data.rows}
          onOpen={open}
          onApprove={approveRow}
          approving={approve.isPending}
        />
      )}
      <p className="text-xs text-muted-foreground">
        Kwota z NEXUSA to zamrożona linia zamkniętego miesiąca. Na B2B porównujemy netto faktury
        z KSeF, na zleceniu i UoP — brutto. Różnica albo rachunek spoza białej listy wymagają
        drugiej osoby.
      </p>
      {openId != null ? (
        <SettlementDetailDialog settlementId={openId} onClose={() => open(null)} />
      ) : null}
    </div>
  );
}
