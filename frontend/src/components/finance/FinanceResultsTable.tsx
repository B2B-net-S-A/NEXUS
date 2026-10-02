"use client";

import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";

import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_UNIT } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import type {
  FinanceEditableField,
  FinanceResultRow,
} from "@/lib/api/finance";
import { EditableCell } from "@/components/finance/EditableCell";

/** Dokładnie DZIEWIĘĆ kolumn (pkt 4.4 ticketu) — nic więcej nie pokazujemy
 *  nigdzie w interfejsie. Dwa nagłówki są PRZEMIANOWANE względem arkusza:
 *  „Średnia Stawka MD" → „Stawka kosztowa MD" i „Stawka MD" → „Stawka
 *  przychodowa MD"; nazwy w pliku Excel zostają bez zmian.
 *
 *  Ta lista jest JEDYNYM źródłem kolejności: nagłówek i każdy wiersz mapują
 *  ją tak samo (do 02.10.2026 wiersz składał się osobno i „Klient" był
 *  wstawiany przed fakturą — kolejność dało się rozjechać jedną zmianą).
 *  „Klient" stoi zaraz po „Kandydacie": to po nim czyta się wiersz.
 *
 *  `label` to pełna nazwa (nazwy dostępne sortowania i komórek); w nagłówku
 *  stoi `head` i jednostka raz — w komórkach są same liczby. */
const COLUMNS: Array<{
  key: string;
  label: string;
  head?: string;
  unit?: string;
  numeric: boolean;
  editable?: FinanceEditableField;
  money?: boolean;
}> = [
  { key: "consultant_name", label: "Kandydat", numeric: false },
  { key: "client_name", label: "Klient", numeric: false },
  {
    key: "cost_rate_md",
    label: "Stawka kosztowa MD",
    head: "Stawka kosztowa",
    unit: "zł/MD",
    numeric: true,
    editable: "cost_rate_md",
    money: true,
  },
  { key: "md_count", label: "Ilość MD", numeric: true, editable: "md_count" },
  {
    key: "compensation",
    label: "Wynagrodzenie",
    unit: "zł",
    numeric: true,
    editable: "compensation",
    money: true,
  },
  {
    key: "revenue_rate_md",
    label: "Stawka przychodowa MD",
    head: "Stawka przychodowa",
    unit: "zł/MD",
    numeric: true,
    editable: "revenue_rate_md",
    money: true,
  },
  {
    key: "invoice_amount",
    label: "Faktura",
    unit: "zł",
    numeric: true,
    editable: "invoice_amount",
    money: true,
  },
  {
    key: "margin_pln",
    label: "Marża PLN",
    head: "Marża",
    unit: "zł",
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

/** Kwota z „zł" — kafle i zdania; w tabeli jednostka stoi w nagłówku. */
export function formatMoney(value: number | null): string {
  if (value == null) return "—";
  return `${value.toLocaleString("pl-PL", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 3,
  })} zł`;
}

/** Sama kwota, bez jednostki — komórka tabeli (jednostka jest w nagłówku). */
function formatAmount(value: number | null): string {
  if (value == null) return "—";
  return value.toLocaleString("pl-PL", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 3,
  });
}

function formatNumber(value: number | null): string {
  if (value == null) return "—";
  return value.toLocaleString("pl-PL", { maximumFractionDigits: 3 });
}

export function formatPct(value: number | null): string {
  if (value == null) return "—";
  return `${value.toLocaleString("pl-PL", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}%`;
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
    <div className="relative max-h-[60dvh] overflow-auto rounded-[10px] border border-border bg-card">
      <table className="w-full text-[13px]">
        <thead className={cn("sticky top-0 z-10 bg-background", CALM_HEAD)}>
          <tr>
            {COLUMNS.map((col, index) => {
              const active = sort === col.key;
              const heading = (
                <>
                  {col.head ?? col.label}
                  {col.unit ? <span className={CALM_UNIT}>{col.unit}</span> : null}
                </>
              );
              return (
                <th
                  key={col.key}
                  scope="col"
                  className={cn(
                    // Nagłówek liczbowy łamie się („Stawka / kosztowa zł/MD”):
                    // w jednej linii siedem takich kolumn wypychało marżę
                    // poza kadr na laptopie 1280 px.
                    "border-b border-border px-2.5 py-2 align-bottom font-semibold leading-[1.25]",
                    col.numeric ? "text-right" : "whitespace-nowrap text-left",
                    // Narożnik: „Konsultant" przyklejony w obu osiach.
                    index === 0 && "sticky left-0 z-20 bg-background",
                  )}
                >
                  {col.numeric ? (
                    <button
                      type="button"
                      onClick={() => onSort(col.key)}
                      aria-label={`Sortuj po ${col.label}`}
                      className="inline-flex items-end gap-1 text-right uppercase hover:text-foreground"
                    >
                      <span>{heading}</span>
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
                    heading
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.id}
              className={cn(CALM_ROW, "h-10 last:border-b-0 hover:bg-muted/40")}
            >
              {COLUMNS.map((col) => {
                if (col.key === "consultant_name") {
                  return (
                    // Nazwisko zostaje w kadrze przy przewijaniu kwot w poziomie.
                    <td
                      key={col.key}
                      className="sticky left-0 z-[1] whitespace-nowrap bg-card px-2.5 py-1.5 font-semibold"
                    >
                      {row.consultant_name}
                    </td>
                  );
                }
                if (!col.editable) {
                  return (
                    <td key={col.key} className="px-2.5 py-1.5">
                      {row.client_name ? (
                        // Limit na elemencie blokowym — `max-width` na samej
                        // komórce tabela o automatycznym układzie ignoruje.
                        <span className="block max-w-[11rem] truncate" title={row.client_name}>
                          {row.client_name}
                        </span>
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                    </td>
                  );
                }
                const field = col.editable;
                // „Marża %" pokazujemy i edytujemy w punktach procentowych
                // (`margin_percent`), bo surowa komórka bywa ułamkiem z Excela
                // — doklejenie „%" do 0,17 dawało „0,2%" zamiast 16,7%.
                const value =
                  field === "margin_pct" ? row.margin_percent : row[field];
                const isMargin = field === "margin_pln" || field === "margin_pct";
                return (
                  <EditableCell
                    key={col.key}
                    value={value}
                    ariaLabel={`${col.label} — ${row.consultant_name}`}
                    needsCompletion={
                      value == null && !row.edited_fields.includes(field)
                    }
                    display={
                      <span
                        className={cn(
                          value == null && CALM_EMPTY,
                          isMargin &&
                            value != null &&
                            (value >= 0
                              ? "text-success-muted-foreground"
                              : "text-destructive"),
                          isMargin && "font-semibold",
                        )}
                      >
                        {field === "margin_pct"
                          ? formatPct(value)
                          : col.money
                            ? formatAmount(value)
                            : formatNumber(value)}
                      </span>
                    }
                    onSave={(next) => onEdit(row.id, field, next)}
                    onError={onError}
                    readOnly={readOnly}
                  />
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
