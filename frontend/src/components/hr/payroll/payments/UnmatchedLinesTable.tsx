"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  useAssignStatementLine,
  useIgnoreStatementLine,
  type PayableRow,
  type UnmatchedLine,
} from "@/lib/api/hr-payments";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";

import { periodLabel } from "./payments-format";

export interface AssignOption {
  settlement_id: number;
  label: string;
}

/** Podpowiedzi z wyciągu (te same 4 cyfry rachunku) najpierw, potem zatwierdzone. */
export function assignOptions(line: UnmatchedLine, payable: PayableRow[]): AssignOption[] {
  const options: AssignOption[] = line.hints.map((hint) => ({
    settlement_id: hint.settlement_id,
    label: `${hint.name} · ${hint.period}`,
  }));
  for (const row of payable) {
    if (row.currency !== line.currency) continue;
    if (options.some((option) => option.settlement_id === row.settlement_id)) continue;
    options.push({
      settlement_id: row.settlement_id,
      label: `${row.name} · ${periodLabel(row.year, row.month)}`,
    });
  }
  return options;
}

function IgnoreDialog({ line, onClose }: { line: UnmatchedLine; onClose: () => void }) {
  const ignore = useIgnoreStatementLine();
  const { showToast } = useToast();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = () => {
    if (reason.trim().length < 3) {
      setError("Podaj powód (co najmniej 3 znaki).");
      return;
    }
    ignore.mutate(
      { lineId: line.id, reason: reason.trim() },
      {
        onSuccess: () => {
          showToast("Operacja pominięta", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się pominąć operacji.")),
      },
    );
  };
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Pominąć operację z wyciągu?"
      description={`${formatMoney(line.amount, line.currency)} · ${line.title || "bez tytułu"}. Powód trafi do śladu zmian.`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Wróć
          </Button>
          <Button onClick={submit} disabled={ignore.isPending}>
            {ignore.isPending ? "Zapisywanie…" : "Pomiń"}
          </Button>
        </>
      }
    >
      <FormField label="Powód" error={error ?? undefined}>
        <Input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="np. zwrot kaucji, przelew prywatny"
          maxLength={500}
        />
      </FormField>
    </AppModal>
  );
}

/** Operacje z wyciągu, które dotyczą kogoś z zespołu, ale nie mają pewnego rozliczenia. */
export function UnmatchedLinesTable({
  lines,
  payable,
}: {
  lines: UnmatchedLine[];
  payable: PayableRow[];
}) {
  const assign = useAssignStatementLine();
  const { showToast } = useToast();
  const [chosen, setChosen] = useState<Record<number, string>>({});
  const [ignoring, setIgnoring] = useState<UnmatchedLine | null>(null);

  const assignLine = (line: UnmatchedLine) => {
    const settlementId = Number(chosen[line.id]);
    if (!settlementId) return;
    assign.mutate(
      { lineId: line.id, settlementId },
      {
        onSuccess: (data) =>
          showToast(data.paid ? "Rozliczenie opłacone" : "Przypisane (było już opłacone)", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się przypisać."), "error"),
      },
    );
  };

  return (
    <>
      <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
        <Table density="compact" className="min-w-[880px]">
          <TableHeader>
            <TableRow>
              <TableHead className={CALM_HEAD}>Data</TableHead>
              <TableHead className={`${CALM_HEAD} text-right`}>Kwota</TableHead>
              <TableHead className={CALM_HEAD}>Tytuł</TableHead>
              <TableHead className={CALM_HEAD}>Dlaczego do decyzji</TableHead>
              <TableHead className={`${CALM_HEAD} text-right`}>Rozliczenie</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {lines.map((line) => {
              const options = assignOptions(line, payable);
              return (
                <TableRow key={line.id} className={CALM_ROW}>
                  <TableCell className="whitespace-nowrap text-sm">
                    {formatIsoDatePl(line.booked_on)}
                  </TableCell>
                  <TableCell className={CALM_AMOUNT}>
                    {formatMoney(line.amount, line.currency)}
                    {line.counterparty_last4 ? (
                      <span className={CALM_SUBLINE}>na •• {line.counterparty_last4}</span>
                    ) : null}
                  </TableCell>
                  <TableCell className="max-w-[260px] break-words text-xs">
                    {line.title || "—"}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {line.reason ?? "Brak pewnego dopasowania."}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-2">
                      {options.length > 0 ? (
                        <Select
                          value={chosen[line.id] ?? ""}
                          onValueChange={(value) =>
                            setChosen((current) => ({ ...current, [line.id]: value }))
                          }
                        >
                          <SelectTrigger
                            className="h-8 w-[220px]"
                            aria-label={`Rozliczenie dla operacji ${line.id}`}
                          >
                            <SelectValue placeholder="Wybierz rozliczenie" />
                          </SelectTrigger>
                          <SelectContent>
                            {options.map((option) => (
                              <SelectItem
                                key={option.settlement_id}
                                value={String(option.settlement_id)}
                              >
                                {option.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          brak rozliczeń do zapłaty
                        </span>
                      )}
                      <Button
                        size="sm"
                        onClick={() => assignLine(line)}
                        disabled={!chosen[line.id] || assign.isPending}
                      >
                        Przypisz
                      </Button>
                      <Button size="sm" variant="quiet" onClick={() => setIgnoring(line)}>
                        Pomiń
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      {ignoring ? <IgnoreDialog line={ignoring} onClose={() => setIgnoring(null)} /> : null}
    </>
  );
}
