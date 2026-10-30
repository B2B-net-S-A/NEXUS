"use client";

import { useState } from "react";

import { useHrConfig } from "@/lib/api/hr";
import { useContractBonuses, type BonusRow } from "@/lib/api/hr-payroll";
import { formatMoney } from "@/lib/money";

import { BonusDeleteDialog } from "./BonusDeleteDialog";
import { BonusDialog } from "./BonusDialog";

const STATUS_LABEL: Record<BonusRow["status"], string> = {
  proposed: "Do decyzji",
  assigned: "Zatwierdzona",
  cancelled: "Usunięta",
};

/**
 * „Premie z tego kontraktu” — tylko dla Płac (bramka trasy i warunek tutaj).
 * Awaria zapytania to komunikat, nie pusta karta.
 */
export function ContractBonusesCard({ contractId }: { contractId: number }) {
  const config = useHrConfig(true);
  const allowed = Boolean(config.data?.me.payroll && config.data?.open_modules.payroll);
  const query = useContractBonuses(contractId, allowed);
  const [editing, setEditing] = useState<BonusRow | null>(null);
  const [deleting, setDeleting] = useState<BonusRow | null>(null);
  if (!allowed) return null;
  if (query.isError) {
    return (
      <p role="alert" className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-destructive">
        Nie udało się wczytać premii z tego kontraktu.
      </p>
    );
  }
  if (!query.isSuccess || query.data.length === 0) return null;
  return (
    <section aria-label="Premie z tego kontraktu" className="rounded-lg border border-border bg-card px-4 py-3">
      <h2 className="text-sm font-semibold text-foreground">Premie z tego kontraktu</h2>
      <div className="relative mt-2 overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="text-left text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
              <th className="py-1.5 pr-3">Rola</th>
              <th className="py-1.5 pr-3">Osoba</th>
              <th className="py-1.5 pr-3 text-right">Kwota</th>
              <th className="py-1.5 pr-3">Wypłata</th>
              <th className="py-1.5 pr-3">Stan</th>
              <th className="py-1.5">
                <span className="sr-only">Akcje</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {query.data.map((row) => (
              <tr key={row.id} className="border-t border-border">
                <td className="py-2 pr-3 text-foreground">{row.category_label}</td>
                <td className="py-2 pr-3 text-foreground">{row.recipient_name ?? "—"}</td>
                <td className="whitespace-nowrap py-2 pr-3 text-right font-semibold tabular-nums text-foreground">
                  {formatMoney(row.amount, row.currency)}
                </td>
                <td className="whitespace-nowrap py-2 pr-3 text-muted-foreground">
                  {String(row.period_month).padStart(2, "0")}.{row.period_year}
                </td>
                <td className="py-2 pr-3 text-muted-foreground">
                  {STATUS_LABEL[row.status]}
                  {row.flags?.length ? ` · ${row.flags.map((flag) => flag.label).join(", ")}` : ""}
                </td>
                <td className="py-2 text-right">
                  {row.status !== "cancelled" ? (
                    <button type="button" className="font-medium text-primary hover:underline" onClick={() => setEditing(row)}>
                      Zmień
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing ? (
        <BonusDialog
          key={editing.id}
          open
          onOpenChange={(value) => {
            if (!value) setEditing(null);
          }}
          people={[]}
          bonus={editing}
          fullEdit
          onDelete={(row) => {
            setEditing(null);
            setDeleting(row);
          }}
        />
      ) : null}
      {deleting ? <BonusDeleteDialog row={deleting} onClose={() => setDeleting(null)} /> : null}
    </section>
  );
}
