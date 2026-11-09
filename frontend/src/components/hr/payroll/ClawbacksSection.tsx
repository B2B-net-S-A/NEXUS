"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useBonusClawbacks, useBonusMode, type BonusClawback } from "@/lib/api/hr-payroll";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_SUBLINE } from "@/lib/calm-table";

import { totalsLabel } from "../me/overview-format";
import { ClawbackDialog } from "./ClawbackDialog";
import { clawbackActive, clawbackProgress, clawbackReason, clawbackRemaining } from "./clawback-format";

/**
 * Płace → miesiąc: zwroty z gwarancji premii DL, które jeszcze coś zmieniają
 * w wypłatach (05.11.2026). Potrącenie liczy raport miesiąca sam; tu jest
 * „za co” i „Zdejmij”. Pusta lista = sekcji nie ma.
 */
export function ClawbacksSection({ meId }: { meId?: number }) {
  const list = useBonusClawbacks();
  const manualAllowed = useBonusMode().data?.manual_allowed ?? true;
  const [cancelling, setCancelling] = useState<BonusClawback | null>(null);
  if (list.isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {apiErrorMessage(list.error, "Nie udało się wczytać zwrotów z gwarancji.")}
      </p>
    );
  }
  if (!list.isSuccess) return null;
  const shown = list.data.filter(clawbackActive);
  if (shown.length === 0) return null;
  return (
    <section className="space-y-2" aria-labelledby="payroll-clawbacks">
      <h2
        id="payroll-clawbacks"
        className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground"
      >
        Zwroty z gwarancji · do potrącenia {totalsLabel(clawbackRemaining(shown))}
      </h2>
      <ul className="divide-y divide-border rounded-lg border border-border bg-card">
        {shown.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2">
            <div className="min-w-0">
              <span className="block truncate text-sm font-medium text-foreground">
                {item.recipient_name ?? "Osoba"} · {item.description ?? "Premia DL"}
              </span>
              <span className={CALM_SUBLINE}>
                {clawbackReason(item)} · {clawbackProgress(item)}
              </span>
            </div>
            {manualAllowed && item.status !== "cancelled" && item.recipient_user_id !== meId ? (
              <Button size="sm" variant="quiet" onClick={() => setCancelling(item)}>
                Zdejmij
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
      {cancelling ? (
        <ClawbackDialog mode="cancel" clawback={cancelling} onClose={() => setCancelling(null)} />
      ) : null}
    </section>
  );
}
