"use client";

import { Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import type { InvoiceLine, OrderPdfRef } from "@/lib/api/finance";
import {
  BOARD_LABEL_TEXT,
  doneLabel,
  type BoardCardItem,
  type BoardItem,
  type BoardLabel,
} from "@/lib/finance-order-board";
import { CALM_SUBLINE } from "@/lib/calm-table";
import { formatMoment } from "@/lib/finance-order-changes";
import { cn } from "@/lib/utils";

import { InvoiceLinesField } from "./InvoiceLinesField";

export function pdfKey(pdf: Pick<OrderPdfRef, "kind" | "id">): string {
  return `${pdf.kind}:${pdf.id}`;
}

/** Kolor plakietki rodzaju zmiany. */
export function labelVariant(
  label: BoardLabel,
): "info" | "success" | "warning" | "danger" | "neutral" | "soft" {
  switch (label) {
    case "new_order":
      return "success";
    case "extension":
    case "period":
      return "info";
    case "rate_revenue":
      return "soft";
    case "rate_cost":
      return "warning";
    case "exit":
    case "gap":
      return "danger";
    default:
      return "neutral";
  }
}

/**
 * Jedna pozycja zamówienia: rodzaj zmiany (plakietka), wartość przed
 * (przekreślona) i po (pogrubiona), kto i kiedy ją wprowadził oraz checkbox
 * „Zrobione” z autorem odhaczenia.
 *
 * `layout="grid"` — pozycja w wierszu zamówienia na liście: checkbox i opis
 * są osobnymi komórkami siatki wiersza (checkbox w pierwszej kolumnie, opis
 * w trzeciej), więc pola „Zrobione” stoją w jednej kolumnie przy lewej
 * krawędzi także wtedy, gdy zamówienie ma kilka zmian.
 */
export function ChangeRow({
  entry,
  canCheck,
  pending,
  onToggle,
  compact = false,
  layout = "stack",
  tabLabel,
  onSaveInvoiceLine,
}: {
  entry: BoardCardItem;
  canCheck: boolean;
  pending: boolean;
  onToggle: (item: BoardItem, done: boolean) => void;
  compact?: boolean;
  layout?: "stack" | "grid";
  tabLabel?: string;
  /** Nordea: zapis ręcznej poprawki pozycji faktury; `true` = zapisano. */
  onSaveInvoiceLine?: (
    item: BoardItem,
    line: InvoiceLine,
    text: string,
  ) => Promise<boolean>;
}) {
  const { item, earlier } = entry;
  const done = item.done;
  const checkboxId = `chk-${item.key.replace(/[^a-z0-9]/gi, "-")}${compact ? "-p" : ""}`;
  const summary =
    item.before !== null
      ? `${item.title}: ${item.before} → ${item.after}`
      : `${item.title}${item.after ? `: ${item.after}` : ""}`;

  // Plakietka mówi, CO to za zmiana; tytuł dopowiada resztę tylko wtedy, gdy
  // mówi coś więcej („Data końca”, „(zmiana klienta)”).
  const kind = BOARD_LABEL_TEXT[item.label];
  const detail =
    item.title === kind
      ? ""
      : item.title.startsWith(kind)
        ? item.title.slice(kind.length).trim()
        : item.title;
  const grid = layout === "grid";

  return (
    <li className={grid ? "contents" : "flex items-start gap-2.5"}>
      <span className={cn("flex pt-0.5", grid && "md:col-start-1")}>
        <Checkbox
          id={checkboxId}
          checked={Boolean(done)}
          disabled={!canCheck || pending}
          onCheckedChange={(value) => onToggle(item, value === true)}
          aria-label={`${done ? "Cofnij „Zrobione”" : "Oznacz jako zrobione"}: ${summary}`}
          className={cn(
            done &&
              "data-[state=checked]:border-success data-[state=checked]:bg-success",
          )}
        />
      </span>
      <div className={cn("min-w-0 flex-1 text-[13px]", grid && "md:col-start-3")}>
        <label htmlFor={checkboxId} className="cursor-pointer text-foreground">
          {tabLabel ? (
            <span className="mr-1 text-xs text-muted-foreground">
              [{tabLabel}]
            </span>
          ) : null}
          <Badge
            size="sm"
            variant={labelVariant(item.label)}
            className="mr-1.5 h-[18px] rounded-md px-1.5 align-middle text-[11px]"
          >
            {kind}
          </Badge>
          {detail ? <span className="font-semibold">{detail}</span> : null}
          {item.before !== null ? (
            <>
              {detail ? ": " : null}
              <s className="text-muted-foreground">{item.before}</s>
              {" → "}
              <strong>{item.after}</strong>
            </>
          ) : item.after ? (
            <>
              {detail ? ": " : null}
              <strong>{item.after}</strong>
            </>
          ) : null}
          {item.note ? (
            <span className="text-muted-foreground"> ({item.note})</span>
          ) : null}
        </label>
        {!compact && (item.enteredAt || item.enteredBy) ? (
          <p className={CALM_SUBLINE}>
            {[item.enteredAt, item.enteredBy].filter(Boolean).join(" · ")}
          </p>
        ) : null}
        {/* Nordea: pozycja faktury pod „Nowe zamówienie” — należy do
            zamówienia, więc zostaje także po „Zrobione” (ticket 8). */}
        {!compact && item.invoiceLines?.length ? (
          <InvoiceLinesField
            lines={item.invoiceLines}
            canSave={canCheck}
            onSave={
              onSaveInvoiceLine
                ? (line, text) => onSaveInvoiceLine(item, line, text)
                : undefined
            }
          />
        ) : null}
        {earlier.map((previous, index) => (
          <p key={index} className={CALM_SUBLINE}>
            wcześniejsza zmiana ({previous.summary}) oznaczona jako zrobiona{" "}
            {formatMoment(previous.done.at)} przez {previous.done.by_name}
          </p>
        ))}
        {done ? (
          <p className="mt-0.5 text-[11.5px] font-medium leading-4 text-success-muted-foreground">
            {doneLabel(done)}
          </p>
        ) : null}
        {pending ? (
          <p className="mt-0.5 flex items-center gap-1 text-[11.5px] leading-4 text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            Zapisywanie…
          </p>
        ) : null}
      </div>
    </li>
  );
}
