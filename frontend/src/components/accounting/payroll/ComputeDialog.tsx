"use client";

import { useState } from "react";

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
import { useComputeList, type PayrollMonth } from "@/lib/api/payroll-lists";
import { apiErrorMessage } from "@/lib/api-error";

import { periodLabel, plural } from "./payroll-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";

/** Najpóźniejsza data wypłaty: koniec drugiego miesiąca po miesiącu pracy (jak serwer). */
function latestPayDate(year: number, month: number): string {
  const end = new Date(Date.UTC(year, month + 2, 0));
  return end.toISOString().slice(0, 10);
}

/**
 * „Przelicz”: data wypłaty (z niej parametry płac, terminy ZUS i PIT-4,
 * miesiąc deklaracji) i liczenie listy od nowa z zamkniętego miesiąca.
 * Szkic można przeliczać dowolnie; zatwierdzonej listy nie.
 */
export function ComputeDialog({
  month,
  open,
  onOpenChange,
}: {
  month: PayrollMonth;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        {open ? <ComputeForm month={month} onDone={() => onOpenChange(false)} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function ComputeForm({ month, onDone }: { month: PayrollMonth; onDone: () => void }) {
  const { showToast } = useToast();
  const compute = useComputeList();
  const [payDate, setPayDate] = useState(month.list?.pay_date ?? month.default_pay_date);
  const first = `${month.year}-${String(month.month).padStart(2, "0")}-01`;
  const latest = latestPayDate(month.year, month.month);
  const valid = /^\d{4}-\d{2}-\d{2}$/.test(payDate) && payDate >= first && payDate <= latest;

  const run = () =>
    compute.mutate(
      { year: month.year, month: month.month, payDate },
      {
        onSuccess: (data) => {
          const list = data.list;
          const blocking = list?.problems.filter((problem) => problem.blocking).length ?? 0;
          showToast(
            list
              ? `Policzono listę ${list.number}: ${plural(list.lines.length, "pozycja", "pozycje", "pozycji")}${
                  blocking ? `, do rozwiązania: ${blocking}` : ""
                }.`
              : "Policzono listę.",
          );
          onDone();
        },
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się policzyć listy."), "error"),
      },
    );

  return (
    <>
      <DialogHeader>
        <DialogTitle className="text-lg">Przelicz listę płac {periodLabel(month.year, month.month)}</DialogTitle>
        <DialogDescription>
          Lista liczy się z zamkniętego miesiąca Rozliczeń i danych płacowych osób.
          {month.list ? " Pozycje szkicu policzą się od nowa." : ""}
        </DialogDescription>
      </DialogHeader>
      <DialogBody className="space-y-1.5">
        <label className="grid gap-1 text-[13px]">
          <span className="font-medium">Data wypłaty</span>
          <input
            type="date"
            aria-label="Data wypłaty"
            className={CONTROL}
            value={payDate}
            min={first}
            max={latest}
            onChange={(event) => setPayDate(event.target.value)}
          />
        </label>
        <p className="text-[12px] leading-5 text-muted-foreground">
          Z daty wypłaty biorą się parametry płac, terminy ZUS i PIT-4 oraz miesiąc deklaracji ZUS.
        </p>
        {!valid ? (
          <p className="text-[12px] text-destructive">
            Data wypłaty: od początku miesiąca pracy do końca drugiego miesiąca po nim.
          </p>
        ) : null}
      </DialogBody>
      <DialogFooter>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Anuluj
        </Button>
        <Button size="sm" disabled={!valid} loading={compute.isPending} onClick={run}>
          Przelicz
        </Button>
      </DialogFooter>
    </>
  );
}
