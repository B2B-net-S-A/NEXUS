"use client";

import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";

import { cn } from "@/lib/utils";
import type {
  FinanceEditableField,
  FinanceResultRow,
} from "@/lib/api/finance";
import { EditableCell } from "@/components/finance/EditableCell";

/** Dokładnie DZIEWIĘĆ kolumn (pkt 4.4 ticketu) — nic więcej nie pokazujemy
 *  nigdzie w interfejsie. Dwa nagłówki są PRZEMIANOWANE względem arkusza:
 *  „Średnia Stawka MD" → „Stawka kosztowa MD" i „Stawka MD" → „Stawka
 *  przychodowa MD"; nazwy w pliku Excel zostają bez zmian. */
const COLUMNS: Array<{
  key: string;
  label: string;
  numeric: boolean;
  editable?: FinanceEditableField;
  money?: boolean;
}> = [
  { key: "consultant_name", label: "Kandydat", numeric: false },
  {
    key: "cost_rate_md",
    label: "Stawka kosztowa MD",
    numeric: true,
    editable: "cost_rate_md",
    money: true,
  },
  { key: "md_count", label: "Ilość MD", numeric: true, editable: "md_count" },
  {
    key: "compensation",
    label: "Wynagrodzenie",
    numeric: true,
    editable: "compensation",
    money: true,
  },
  {
    key: "revenue_rate_md",
    label: "Stawka przychodowa MD",
    numeric: true,
    editable: "revenue_rate_md",
    money: true,
  },
  { key: "client_name", label: "Klient", numeric: false },
  {
    key: "invoice_amount",
    label: "Faktura",
    numeric: true,
    editable: "invoice_amount",
    money: true,
  },
  {
    key: "margin_pln",
    label: "Marża PLN",
    numeric: true,
    editable: "margin_pln",
    money: true,
  },
  {
    key: "margin_pct",
    label: "Marża %",
    numeric: true,
    editable: "margin_pct",
  },
];

export function formatMoney(value: number | null): string {
  if (value == null) return "—";
  return `${value.toLocaleString("pl-PL", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 3,
  })} zł`;
}

function formatNumber(value: number | null): string {
  if (value == null) return "—";
  return value.toLocaleString("pl-PL", { maximumFractionDigits: 3 });
}

function formatPct(value: number | null): string {
  if (value == null) return "—";
  return `${value.toLocaleString("pl-PL", { maximumFractionDigits: 1 })}%`;
}

interface Props {
  rows: FinanceResultRow[];
  sort: string;
  direction: "asc" | "desc";
  onSort: (key: string) => void;
  onEdit: (
    rowId: number,
    field: FinanceEditableField,
    value: number | null,
  ) => Promise<void>;
  onError: (msg: string) => void;
  searching: boolean;
  readOnly?: boolean;
}

export function FinanceResultsTable({
  rows,
  sort,
  direction,
  onSort,
  onEdit,
  onError,
  searching,
  readOnly = false,
}: Props) {
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        {/* Pustka po wyszukaniu ≠ brak danych za miesiąc — to samo
            rozróżnienie co w rejestrze zamówień. */}
        {searching
          ? "Brak wyników pasujących do wyszukiwania."
          : "Ten miesiąc nie ma jeszcze żadnych wierszy."}
      </div>
    );
  }

  return (
    // Ciało tabeli przewija się WEWNĄTRZ tego kontenera, a nie przez
    // przewijanie strony — nagłówek zostaje widoczny (pkt 4.4 ticketu).
    <div className="max-h-[60vh] overflow-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="sticky top-0 z-10 bg-muted text-xs uppercase text-muted-foreground">
          <tr>
            {COLUMNS.map((col) => {
              const active = sort === col.key;
              return (
                <th
                  key={col.key}
                  scope="col"
                  className={cn(
                    "whitespace-nowrap px-3 py-2 font-medium",
                    col.numeric ? "text-right" : "text-left",
                  )}
                >
                  {col.numeric ? (
                    <button
                      type="button"
                      onClick={() => onSort(col.key)}
                      aria-label={`Sortuj po ${col.label}`}
                      className="inline-flex items-center gap-1 hover:text-foreground"
                    >
                      {col.label}
                      {active ? (
                        direction === "desc" ? (
                          <ArrowDown className="h-3 w-3" />
                        ) : (
                          <ArrowUp className="h-3 w-3" />
                        )
                      ) : (
                        <ChevronsUpDown className="h-3 w-3 opacity-40" />
                      )}
                    </button>
                  ) : (
                    col.label
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-t border-border hover:bg-muted/40">
              <td className="whitespace-nowrap px-3 py-1.5 font-medium">
                {row.consultant_name}
              </td>
              {COLUMNS.filter((c) => c.editable).map((col) => {
                const field = col.editable!;
                const value = row[field];
                const isMargin = field === "margin_pln" || field === "margin_pct";
                return (
                  <ClientNameSlot key={col.key} col={col.key} row={row}>
                    <EditableCell
                      value={value}
                      ariaLabel={`${col.label} — ${row.consultant_name}`}
                      needsCompletion={
                        value == null && !row.edited_fields.includes(field)
                      }
                      display={
                        <span
                          className={cn(
                            isMargin &&
                              value != null &&
                              (value >= 0 ? "text-emerald-600" : "text-destructive"),
                            isMargin && "font-medium",
                          )}
                        >
                          {field === "margin_pct"
                            ? formatPct(value)
                            : col.money
                              ? formatMoney(value)
                              : formatNumber(value)}
                        </span>
                      }
                      onSave={(next) => onEdit(row.id, field, next)}
                      onError={onError}
                      readOnly={readOnly}
                    />
                  </ClientNameSlot>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * „Klient" siedzi w środku bloku kolumn liczbowych (między stawką przychodową
 * a fakturą — kolejność z ticketu), a nie jest edytowalny. Ten slot wstawia go
 * w odpowiednim miejscu bez rozbijania mapowania kolumn edytowalnych.
 */
function ClientNameSlot({
  col,
  row,
  children,
}: {
  col: string;
  row: FinanceResultRow;
  children: React.ReactNode;
}) {
  if (col !== "invoice_amount") return <>{children}</>;
  return (
    <>
      <td className="whitespace-nowrap px-3 py-1.5 text-muted-foreground">
        {row.client_name ?? ""}
      </td>
      {children}
    </>
  );
}
