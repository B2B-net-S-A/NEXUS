"use client";

import Link from "next/link";
import { useState } from "react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  useMarkPaid,
  useTransfersFile,
  useTransfersPlan,
  type PayrollList,
  type TransferRow,
} from "@/lib/api/payroll-lists";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { datePl, gr } from "../ledger-model";
import { errorDetail, grosze, plural, zl } from "./payroll-model";

const KIND_LABEL: Record<TransferRow["kind"], string> = {
  wage: "wypłata",
  zus: "ZUS",
  pit4: "PIT-4",
  pit8ar: "PIT-8AR",
};

/**
 * Przelewy zatwierdzonej listy: najpierw plan (kto, ile, na jaki rachunek,
 * kto poza plikiem i dlaczego), potem plik do banku i „Bank wykonał”.
 * Plik powstaje tylko przy włączonej paczce przelewów w Ustawieniach → Rozliczenia.
 */
export function TransfersDialog({
  list,
  open,
  onOpenChange,
}: {
  list: PayrollList;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="xl">{open ? <TransfersBody list={list} onClose={() => onOpenChange(false)} /> : null}</DialogContent>
    </Dialog>
  );
}

function TransfersBody({ list, onClose }: { list: PayrollList; onClose: () => void }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const plan = useTransfersPlan(list.id);
  const file = useTransfersFile();
  const paid = useMarkPaid();
  const [disabled, setDisabled] = useState<string | null>(null);

  const download = () =>
    file.mutate(
      { listId: list.id, fallbackName: `przelewy-${list.number.replaceAll("/", "-")}.pli` },
      {
        onSuccess: () => {
          setDisabled(null);
          showToast("Pobrano plik przelewów — zaimportuj go w banku firmy.");
        },
        onError: (error) => {
          const message = apiErrorMessage(error, "Nie udało się przygotować pliku przelewów.");
          if (errorDetail(error).code === "transfer_batch_disabled") setDisabled(message);
          else showToast(message, "error");
        },
      },
    );

  const markPaid = async () => {
    const ok = await askConfirm({
      title: `Bank wykonał przelewy listy ${list.number}?`,
      description:
        "Lista zostanie oznaczona jako wypłacona — anulować się jej już nie da, korektę robi się kolejną listą. Potwierdza osoba z Rozliczeń bez własnej pozycji na liście.",
      confirmLabel: "Bank wykonał",
    });
    if (!ok) return;
    paid.mutate(list.id, {
      onSuccess: () => showToast(`Lista ${list.number} oznaczona jako wypłacona.`),
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się oznaczyć wypłaty."), "error"),
    });
  };

  const rows = plan.data?.rows ?? [];
  const included = rows.filter((row) => row.included);
  const total = included.reduce((sum, row) => sum + (grosze(row.amount) ?? 0), 0);
  const created = plan.data?.transfers_created_at ?? list.transfers_created_at;
  const paidAt = plan.data?.paid_at ?? list.paid_at;

  return (
    <>
      <DialogHeader>
        <DialogTitle className="text-lg">Przelewy — lista {list.number}</DialogTitle>
        <DialogDescription>
          Wypłaty na rachunki osób, ZUS na rachunek składkowy, PIT-4 i PIT-8AR na mikrorachunek podatkowy.
        </DialogDescription>
      </DialogHeader>
      <DialogBody className="space-y-3">
        {disabled ? (
          <p role="alert" className="rounded-md border border-border bg-warning-muted px-3 py-2 text-[13px] text-warning-muted-foreground">
            {disabled}{" "}
            <Link href="/settings/payroll" className="font-medium text-primary hover:underline">
              Ustawienia → Rozliczenia
            </Link>
          </p>
        ) : null}
        {plan.isError ? (
          <QueryStateNotice state="error" onRetry={() => plan.refetch()} />
        ) : !plan.isSuccess ? (
          <p className="text-[13px] text-muted-foreground">Wczytywanie planu przelewów…</p>
        ) : rows.length ? (
          <div className="relative overflow-x-auto rounded-md border border-border">
            <table className="w-full min-w-[560px] table-fixed text-sm">
              <thead>
                <tr className="border-b border-border/70">
                  <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Odbiorca</th>
                  <th className={cn(CALM_HEAD, "w-[16%] px-2 py-2 text-left")}>Rachunek</th>
                  <th className={cn(CALM_HEAD, "w-[18%] px-2 py-2 text-right")}>Kwota, zł</th>
                  <th className={cn(CALM_HEAD, "w-[17%] px-3 py-2 text-left")}>W pliku</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={`${row.kind}-${row.line_id ?? index}`} className={cn(CALM_ROW, "align-top last:border-0")}>
                    <td className="min-w-0 px-3 py-1.5">
                      <span className="block truncate font-medium" title={row.name}>
                        {row.name}
                      </span>
                      <span className={CALM_SUBLINE}>{KIND_LABEL[row.kind] ?? row.kind}</span>
                    </td>
                    <td className="px-2 py-1.5 tabular-nums text-muted-foreground">
                      {row.account_last4 ? `•••• ${row.account_last4}` : "—"}
                    </td>
                    <td className={cn(CALM_AMOUNT, "px-2 py-1.5")}>{zl(row.amount)}</td>
                    <td className="px-3 py-1.5 text-[12.5px]">
                      {row.included ? (
                        <span className="text-success">tak</span>
                      ) : (
                        <>
                          <span className="text-destructive">poza plikiem</span>
                          {row.reason ? <span className={CALM_SUBLINE}>{row.reason}</span> : null}
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-[13px] text-muted-foreground">Na liście nie ma kwot do przelania.</p>
        )}
        {plan.isSuccess && rows.length ? (
          <p className="text-[12.5px] text-muted-foreground">
            W pliku: {plural(included.length, "przelew", "przelewy", "przelewów")}, razem {gr(total)} zł
            {rows.length > included.length ? ` · poza plikiem: ${rows.length - included.length}` : ""}.
            {created ? ` Plik pobrany ${datePl(created)}.` : ""}
            {paidAt ? ` Bank wykonał przelewy ${datePl(paidAt)}.` : ""}
          </p>
        ) : null}
      </DialogBody>
      <DialogFooter>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Zamknij
        </Button>
        {created && !paidAt ? (
          <Button size="sm" variant="outline" loading={paid.isPending} onClick={() => void markPaid()}>
            Bank wykonał przelewy
          </Button>
        ) : null}
        <Button size="sm" disabled={!included.length || Boolean(paidAt)} loading={file.isPending} onClick={download}>
          {created ? "Pobierz plik ponownie" : "Pobierz plik przelewów"}
        </Button>
      </DialogFooter>
      {confirmDialog}
    </>
  );
}
