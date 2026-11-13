"use client";

import { useMemo, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
  useCreateDrafts,
  useToIssue,
  type ToIssueRow,
} from "@/lib/api/issued-invoices";
import {
  CALM_AMOUNT,
  CALM_HEAD,
  CALM_ROW,
  CALM_SUBLINE,
} from "@/lib/calm-table";
import { monthTitlePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";

import { splitPeriod } from "../invoicing-format";

const KIND_LABELS: Record<ToIssueRow["kind"], string> = {
  md: "MD",
  cost: "kosztowe",
  periodic: "okresowe",
};

export function selectable(row: ToIssueRow): boolean {
  return (
    !row.blocked && row.issued.length === 0 && row.invoiced_in_ksef.length === 0
  );
}

/**
 * „Wystaw za miesiąc” (M4): zamówienia z „Do faktury” za wybrany miesiąc,
 * zaznaczenie → szkice (jedna faktura na zamówienie albo na osobę). Wiersz
 * bez kwoty (brak zużycia MD) i zamówienie z fakturą za ten miesiąc nie dają
 * się zaznaczyć — powód stoi w wierszu.
 */
export function IssueMonthPanel({
  period,
  onCreated,
}: {
  period: string;
  onCreated: (ids: number[]) => void;
}) {
  const { showToast } = useToast();
  const { year, month } = splitPeriod(period);
  const query = useToIssue(year, month);
  const create = useCreateDrafts();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [split, setSplit] = useState<"order" | "person">("order");
  const clients = useMemo(() => query.data?.clients ?? [], [query.data]);

  const toggle = (key: string, on: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });

  const submit = () =>
    create.mutate(
      { year, month, keys: [...selected], split },
      {
        onSuccess: (result) => {
          showToast(
            `Utworzono ${countPl(result.created.length, "szkic", "szkice", "szkiców")}`,
            "success",
          );
          setSelected(new Set());
          onCreated(result.created);
        },
        onError: (err) =>
          showToast(
            apiErrorMessage(err, "Nie udało się utworzyć szkiców."),
            "error",
          ),
      },
    );

  if (query.isLoading) {
    return (
      <p className="py-6 text-sm text-muted-foreground">
        Liczenie zamówień do wystawienia…
      </p>
    );
  }
  if (query.isError)
    return <QueryStateNotice state="error" onRetry={() => query.refetch()} />;
  if (query.isSuccess && clients.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        Za {monthTitlePl(period).toLowerCase()} nie ma zamówień do
        zafakturowania.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2">
        <p className="text-sm text-muted-foreground">
          Zaznacz zamówienia — powstaną szkice. Numer z serii faktura dostaje
          dopiero przy wysyłce do KSeF.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-foreground">
            <span>Podział</span>
            <select
              aria-label="Podział na faktury"
              className="h-8 rounded-md border border-border bg-card px-2 text-sm text-foreground"
              value={split}
              onChange={(event) =>
                setSplit(event.target.value as "order" | "person")
              }
            >
              <option value="order">jedna faktura na zamówienie</option>
              <option value="person">faktura na osobę</option>
            </select>
          </label>
          <Button
            size="sm"
            onClick={submit}
            disabled={selected.size === 0 || create.isPending}
          >
            {create.isPending
              ? "Tworzenie…"
              : `Utwórz szkice${selected.size ? ` (${selected.size})` : ""}`}
          </Button>
        </div>
      </div>
      <div className="rounded-lg border border-border bg-card">
        <Table density="compact" className="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead className={`${CALM_HEAD} w-10`}>
                <span className="sr-only">Zaznacz</span>
              </TableHead>
              <TableHead className={`${CALM_HEAD} w-[34%]`}>
                Zamówienie
              </TableHead>
              <TableHead className={`${CALM_HEAD} w-[10%]`}>Rodzaj</TableHead>
              <TableHead className={`${CALM_HEAD} w-[18%] text-right`}>
                Netto do faktury
              </TableHead>
              <TableHead className={`${CALM_HEAD} w-[34%]`}>Stan</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {clients.map((entry) => [
              <TableRow key={`c${entry.client_id}`} className="bg-muted/40">
                <TableCell
                  colSpan={5}
                  className="py-1.5 text-sm font-semibold text-foreground"
                >
                  {entry.client_name ?? `Klient #${entry.client_id}`}
                </TableCell>
              </TableRow>,
              ...entry.rows.map((row) => (
                <TableRow
                  key={row.key}
                  className={`${CALM_ROW} align-top`}
                  data-testid={`to-issue-${row.key}`}
                >
                  <TableCell>
                    <Checkbox
                      aria-label={`Zaznacz zamówienie ${row.order_number}`}
                      checked={selected.has(row.key)}
                      disabled={!selectable(row)}
                      onCheckedChange={(value) =>
                        toggle(row.key, value === true)
                      }
                    />
                  </TableCell>
                  <TableCell className="min-w-0">
                    <span className="block truncate">{row.order_number}</span>
                    <span className={CALM_SUBLINE}>
                      {countPl(row.people, "osoba", "osoby", "osób")}
                    </span>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {KIND_LABELS[row.kind]}
                  </TableCell>
                  <TableCell className={CALM_AMOUNT}>
                    {row.expected_net
                      ? formatMoney(row.expected_net, row.currency)
                      : "—"}
                  </TableCell>
                  <TableCell className="min-w-0 text-sm">
                    {row.issued.length ? (
                      row.issued.map((issued) => (
                        <a
                          key={issued.id}
                          href={`/finance/faktury/${issued.id}`}
                          className="block truncate text-primary hover:underline"
                        >
                          {issued.invoice_number
                            ? `${issued.invoice_number} · ${issued.status_label}`
                            : issued.status_label}
                        </a>
                      ))
                    ) : row.invoiced_in_ksef.length ? (
                      <StatusDot
                        tone="success"
                        note={row.invoiced_in_ksef.join(", ")}
                      >
                        zafakturowane w KSeF
                      </StatusDot>
                    ) : row.blocked ? (
                      <StatusDot tone="warning" note={row.blocked}>
                        nie da się wystawić
                      </StatusDot>
                    ) : row.needs_amount ? (
                      <StatusDot tone="info">
                        kwotę pozycji wpiszesz w szkicu
                      </StatusDot>
                    ) : (
                      <StatusDot tone="neutral">do wystawienia</StatusDot>
                    )}
                  </TableCell>
                </TableRow>
              )),
            ])}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
