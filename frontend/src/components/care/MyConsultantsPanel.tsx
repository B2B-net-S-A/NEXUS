"use client";

import { useState } from "react";
import Link from "next/link";
import { Users } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { REDEPLOY_REASON_LABELS, useMyConsultants } from "@/lib/api/care";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { formatIsoDatePl } from "@/lib/date-pl";

/** „Moi konsultanci” — kontrakty, przy których jestem opiekunem (albo wszystkie w zakresie). */
export function MyConsultantsPanel() {
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const query = useMyConsultants(scope);
  const rows = query.data?.items ?? [];
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: rows.length === 0,
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1" role="group" aria-label="Zakres listy">
        {(
          [
            ["mine", "Moi"],
            ["all", "Wszyscy w moim zakresie"],
          ] as const
        ).map(([value, label]) => (
          <Button
            key={value}
            size="sm"
            variant={scope === value ? "secondary" : "ghost"}
            aria-pressed={scope === value}
            onClick={() => setScope(value)}
          >
            {label}
          </Button>
        ))}
      </div>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          onRetry={() => query.refetch()}
        />
      ) : state === "empty" ? (
        <EmptyState
          icon={Users}
          title={scope === "mine" ? "Nie opiekujesz się żadnym konsultantem" : "Brak aktywnych kontraktów"}
          description={
            scope === "mine"
              ? "Opiekuna ustawia się na kontrakcie (zakładka „Opieka”) albo domyślnie dla klienta."
              : undefined
          }
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className={CALM_ROW}>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Konsultant</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Klient</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Następny kontakt</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Ostatnia rozmowa</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Sygnały</th>
                {scope === "all" ? (
                  <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Opiekun</th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.contract_id} className={CALM_ROW}>
                  <td className="px-3 py-1.5">
                    <Link
                      href={`/contracts/${row.contract_id}?tab=care`}
                      className="font-medium hover:underline"
                    >
                      {row.candidate_name ?? "Konsultant"}
                    </Link>
                    {row.job_title ? <span className={CALM_SUBLINE}>{row.job_title}</span> : null}
                  </td>
                  <td className="px-3 py-1.5">{row.client_name}</td>
                  <td className="px-3 py-1.5">
                    {row.next_contact ? (
                      <>
                        <span className={cn("tabular-nums", row.next_contact.overdue && "text-destructive")}>
                          {formatIsoDatePl(row.next_contact.due_on)}
                        </span>
                        <span className={CALM_SUBLINE}>
                          {row.next_contact.label}
                          {row.overdue_count > 1 ? ` · zaległe: ${row.overdue_count}` : ""}
                        </span>
                      </>
                    ) : (
                      <span className={CALM_EMPTY}>—</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 tabular-nums">
                    {row.last_conversation_on ? (
                      <>
                        {formatIsoDatePl(row.last_conversation_on)}
                        {row.last_satisfaction ? (
                          <span className={CALM_SUBLINE}>zadowolenie {row.last_satisfaction}/5</span>
                        ) : null}
                      </>
                    ) : (
                      <span className={CALM_EMPTY}>—</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5">
                    {row.redeploy_reasons.length ? (
                      row.redeploy_reasons.map((reason) => REDEPLOY_REASON_LABELS[reason]).join(", ")
                    ) : (
                      <span className={CALM_EMPTY}>—</span>
                    )}
                  </td>
                  {scope === "all" ? (
                    <td className="px-3 py-1.5">
                      {row.owner?.name ?? <span className={CALM_EMPTY}>—</span>}
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
