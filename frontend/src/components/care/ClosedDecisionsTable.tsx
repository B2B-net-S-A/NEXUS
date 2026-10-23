"use client";

import { ArrowRightLeft } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  REDEPLOY_REASON_LABELS,
  useRedeployQueue,
  useUpdateRedeploy,
  type RedeployRow,
} from "@/lib/api/care";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

/** Jak w oknie zamykania karty „Decyzja” na tablicy. */
const OUTCOME_LABELS: Record<string, string> = {
  done: "Przekazana",
  dismissed: "Nie dotyczy",
};

/**
 * „Decyzje zamknięte” w Opieka → Konsultanci (decyzja Artura 22.10.2026,
 * audyt F107): zamknięte wpisy „Do przepięcia” z wynikiem i notatką,
 * „Otwórz ponownie” wraca wpis na „W toku” (karta „Decyzja” wraca na tablicę).
 * Awaria ≠ pusta lista.
 */
export function ClosedDecisionsTable({ onOpenContract }: { onOpenContract: (contractId: number) => void }) {
  const { showToast } = useToast();
  const query = useRedeployQueue("closed");
  const update = useUpdateRedeploy();
  const rows = query.data?.items ?? [];
  const canEdit = query.data?.can_edit ?? false;
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: rows.length === 0,
  });

  const reopen = (row: RedeployRow) =>
    update.mutate(
      { itemId: row.id, status: "in_progress" },
      {
        onSuccess: () => showToast("Decyzja otwarta ponownie — wraca na tablicę", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się otworzyć decyzji."), "error"),
      },
    );

  if (state === "loading") return <p className="text-sm text-muted-foreground">Wczytywanie zamkniętych decyzji…</p>;
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return (
      <QueryStateNotice
        state={state}
        description={state === "error" ? "Nie udało się wczytać zamkniętych decyzji." : undefined}
        onRetry={() => query.refetch()}
      />
    );
  }
  if (state === "empty") return <EmptyState icon={ArrowRightLeft} title="Brak zamkniętych decyzji" />;
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full text-sm" aria-label="Zamknięte decyzje „Do przepięcia”">
        <thead>
          <tr className={CALM_ROW}>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Konsultant</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Klient</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Powód</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Zamknięta</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Notatka</th>
            {canEdit ? <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Akcja</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const name = row.candidate_name ?? "konsultant";
            return (
              <tr key={row.id} className={CALM_ROW}>
                <td className="px-3 py-1.5 align-top">
                  <button
                    type="button"
                    className="text-left font-medium hover:underline"
                    aria-label={`Karta konsultanta: ${name}`}
                    onClick={() => onOpenContract(row.contract_id)}
                  >
                    {row.candidate_name ?? "Konsultant"}
                  </button>
                  {row.owner ? <span className={CALM_SUBLINE}>opiekun: {row.owner.name}</span> : null}
                </td>
                <td className="px-3 py-1.5 align-top">{row.client_name}</td>
                <td className="px-3 py-1.5 align-top">{REDEPLOY_REASON_LABELS[row.reason]}</td>
                <td className="px-3 py-1.5 align-top">
                  {OUTCOME_LABELS[row.status] ?? row.status}
                  <span className={cn(CALM_SUBLINE, "tabular-nums")}>{formatIsoDatePl(row.resolved_at)}</span>
                </td>
                <td className="max-w-56 px-3 py-1.5 align-top">
                  {row.note ? (
                    <span className="line-clamp-2 text-muted-foreground">{row.note}</span>
                  ) : (
                    <span className={CALM_EMPTY}>—</span>
                  )}
                </td>
                {canEdit ? (
                  <td className="px-3 py-1.5 align-top">
                    <Button
                      size="sm"
                      variant="outline"
                      aria-label={`Otwórz ponownie: ${name}`}
                      loading={update.isPending && update.variables?.itemId === row.id}
                      onClick={() => reopen(row)}
                    >
                      Otwórz ponownie
                    </Button>
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
