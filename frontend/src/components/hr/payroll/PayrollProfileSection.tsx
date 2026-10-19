"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { useDeleteRate, usePersonPayroll, type RateRow } from "@/lib/api/hr-payroll";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";
import { formatMoney } from "@/lib/money";
import { formatIsoDatePl } from "@/lib/date-pl";

import { BonusDialog } from "./BonusDialog";
import { BonusTable } from "./BonusTable";
import { RateDialog } from "./RateDialog";

const SECTION_TITLE =
  "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";

/** Okres stawki w jednej linii: „od 01.09.2026” albo „01.06.2026 – 31.08.2026”. */
export function rateRange(rate: Pick<RateRow, "effective_from" | "effective_to">): string {
  if (!rate.effective_to) return `od ${formatIsoDatePl(rate.effective_from)}`;
  return `${formatIsoDatePl(rate.effective_from)} – ${formatIsoDatePl(rate.effective_to)}`;
}

function RatesTable({
  rates,
  canEdit,
  onDelete,
}: {
  rates: RateRow[];
  canEdit: boolean;
  onDelete: (rate: RateRow) => void;
}) {
  if (rates.length === 0) {
    return <p className="text-sm text-muted-foreground">Brak stawek w historii.</p>;
  }
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
      <Table density="compact" className="min-w-[520px]">
        <TableHeader>
          <TableRow>
            <TableHead className={CALM_HEAD}>Okres</TableHead>
            <TableHead className={`${CALM_HEAD} text-right`}>Stawka /h</TableHead>
            <TableHead className={CALM_HEAD}>Powód</TableHead>
            {canEdit ? (
              <TableHead className={CALM_HEAD}>
                <span className="sr-only">Akcje</span>
              </TableHead>
            ) : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rates.map((rate) => (
            <TableRow key={rate.id} className={CALM_ROW}>
              <TableCell className="whitespace-nowrap text-sm text-foreground">
                {rateRange(rate)}
              </TableCell>
              <TableCell className={`${CALM_AMOUNT} text-sm font-medium text-foreground`}>
                {formatMoney(rate.hourly_rate, rate.currency)}
              </TableCell>
              <TableCell className="max-w-[260px] truncate text-sm text-muted-foreground">
                {rate.reason ?? "—"}
              </TableCell>
              {canEdit ? (
                <TableCell className="text-right">
                  <Button
                    size="icon-sm"
                    variant="quiet"
                    aria-label={`Usuń stawkę ${rateRange(rate)}`}
                    onClick={() => onDelete(rate)}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </Button>
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/**
 * Kartoteka osoby → Płace: historia stawek („Nowa stawka od…” dla Płac) i premie.
 * Przełożony dostaje z serwera premie bez stawek; osoba spoza zakresu — nic
 * (sekcja się nie pokazuje).
 */
export function PayrollProfileSection({ userId, name }: { userId: number; name: string }) {
  const payroll = usePersonPayroll(userId);
  const remove = useDeleteRate();
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [rateOpen, setRateOpen] = useState(false);
  const [bonusOpen, setBonusOpen] = useState(false);
  const state = resolveViewState({
    isLoading: payroll.isLoading,
    isError: payroll.isError,
    error: payroll.error,
    isSuccess: payroll.isSuccess,
  });

  if (state === "forbidden" || state === "not_found") return null;

  const deleteRate = async (rate: RateRow) => {
    const ok = await askConfirm({
      title: "Usunąć stawkę?",
      description: `${formatMoney(rate.hourly_rate, rate.currency)} · ${rateRange(rate)}. Poprzednia stawka przejmie ten okres.`,
      confirmLabel: "Usuń stawkę",
      cancelLabel: "Zostaw",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(rate.id, {
      onSuccess: () => showToast("Stawka usunięta", "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się usunąć stawki."), "error"),
    });
  };

  const data = payroll.data;
  const visibleBonuses = (data?.bonuses ?? []).filter(
    (bonus) => bonus.status !== "cancelled" || bonus.cancel_reason === "manual",
  );

  return (
    // `#place` — dzwonek Płac „stawka z umowy do przepisania” prowadzi tutaj.
    <Card id="place" className="space-y-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className={SECTION_TITLE}>Płace</h2>
        {data ? (
          <div className="flex flex-wrap gap-2">
            {data.can_edit_rates ? (
              <Button size="sm" variant="secondary" onClick={() => setRateOpen(true)}>
                <Plus className="h-4 w-4" aria-hidden />
                Nowa stawka od…
              </Button>
            ) : null}
            {data.can_add_bonus ? (
              <Button size="sm" variant="secondary" onClick={() => setBonusOpen(true)}>
                <Plus className="h-4 w-4" aria-hidden />
                Nowa premia
              </Button>
            ) : null}
          </div>
        ) : null}
      </div>

      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie płac…</p>
      ) : state === "error" || !data ? (
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          Nie udało się wczytać płac.
          <Button size="sm" variant="ghost" onClick={() => payroll.refetch()}>
            Spróbuj ponownie
          </Button>
        </div>
      ) : (
        <>
          {data.scope === "full" ? (
            <section className="space-y-2">
              <p className="text-sm text-foreground">
                Aktualna stawka:{" "}
                <strong>
                  {data.current_rate
                    ? formatMoney(data.current_rate.hourly_rate, data.current_rate.currency)
                    : "nie ustawiona"}
                </strong>
                {data.current_rate ? (
                  <span className={CALM_SUBLINE}>{rateRange(data.current_rate)}</span>
                ) : null}
              </p>
              <RatesTable
                rates={data.rates ?? []}
                canEdit={data.can_edit_rates}
                onDelete={deleteRate}
              />
            </section>
          ) : null}
          <section className="space-y-2">
            <h3 className={SECTION_TITLE}>Premie</h3>
            {visibleBonuses.length === 0 ? (
              <p className="text-sm text-muted-foreground">Brak premii.</p>
            ) : (
              <BonusTable rows={visibleBonuses} showRecipient={false} minWidth="min-w-[600px]" />
            )}
          </section>
        </>
      )}

      {/* Okna montowane po kliknięciu — świeży stan formularza za każdym razem. */}
      {rateOpen && data ? (
        <RateDialog
          userId={userId}
          name={name}
          open={rateOpen}
          onOpenChange={setRateOpen}
          defaultCurrency={data.current_rate?.currency}
        />
      ) : null}
      {bonusOpen ? (
        <BonusDialog
          open={bonusOpen}
          onOpenChange={setBonusOpen}
          people={[]}
          fixedPerson={{ user_id: userId, name }}
        />
      ) : null}
      {confirmDialog}
    </Card>
  );
}
