"use client";

import { Loader2 } from "lucide-react";

import { Checkbox } from "@/components/ui/checkbox";
import type { OrderPdfRef } from "@/lib/api/finance";
import {
  doneLabel,
  type BoardCardItem,
  type BoardItem,
} from "@/lib/finance-order-board";
import { formatMoment } from "@/lib/finance-order-changes";
import { cn } from "@/lib/utils";

export function pdfKey(pdf: Pick<OrderPdfRef, "kind" | "id">): string {
  return `${pdf.kind}:${pdf.id}`;
}

/**
 * Jedna pozycja karty: wartość przed (przekreślona) i po (pogrubiona), kto
 * i kiedy ją wprowadził oraz checkbox „Zrobione” z autorem odhaczenia.
 */
export function ChangeRow({
  entry,
  canCheck,
  pending,
  onToggle,
  compact = false,
  tabLabel,
}: {
  entry: BoardCardItem;
  canCheck: boolean;
  pending: boolean;
  onToggle: (item: BoardItem, done: boolean) => void;
  compact?: boolean;
  tabLabel?: string;
}) {
  const { item, earlier } = entry;
  const done = item.done;
  const checkboxId = `chk-${item.key.replace(/[^a-z0-9]/gi, "-")}${compact ? "-p" : ""}`;
  const summary =
    item.before !== null
      ? `${item.title}: ${item.before} → ${item.after}`
      : `${item.title}${item.after ? `: ${item.after}` : ""}`;

  return (
    <li
      className={cn(
        "flex items-start gap-3 rounded-lg border px-3 py-2.5",
        done
          ? "border-success/20 bg-success-muted/60"
          : "border-transparent bg-muted/50",
      )}
    >
      <Checkbox
        id={checkboxId}
        checked={Boolean(done)}
        disabled={!canCheck || pending}
        onCheckedChange={(value) => onToggle(item, value === true)}
        aria-label={`${done ? "Cofnij „Zrobione”" : "Oznacz jako zrobione"}: ${summary}`}
        className={cn(
          "mt-0.5 h-5 w-5",
          done &&
            "data-[state=checked]:border-success data-[state=checked]:bg-success",
        )}
      />
      <div className="min-w-0 flex-1 text-sm">
        <label htmlFor={checkboxId} className="cursor-pointer text-foreground">
          {tabLabel ? (
            <span className="mr-1 text-xs text-muted-foreground">
              [{tabLabel}]
            </span>
          ) : null}
          <span className="font-semibold">{item.title}</span>
          {item.before !== null ? (
            <>
              {": "}
              <s className="text-muted-foreground">{item.before}</s>
              {" → "}
              <strong>{item.after}</strong>
            </>
          ) : item.after ? (
            <>
              {": "}
              <strong>{item.after}</strong>
            </>
          ) : null}
          {item.note ? (
            <span className="text-muted-foreground"> ({item.note})</span>
          ) : null}
        </label>
        {!compact && (item.enteredAt || item.enteredBy) ? (
          <p className="mt-0.5 text-xs text-muted-foreground">
            {[item.enteredAt, item.enteredBy].filter(Boolean).join(" · ")}
          </p>
        ) : null}
        {earlier.map((previous, index) => (
          <p key={index} className="mt-0.5 text-xs text-muted-foreground">
            wcześniejsza zmiana ({previous.summary}) oznaczona jako zrobiona{" "}
            {formatMoment(previous.done.at)} przez {previous.done.by_name}
          </p>
        ))}
        {done ? (
          <p className="mt-0.5 text-xs font-medium text-success-muted-foreground">
            {doneLabel(done)}
          </p>
        ) : null}
        {pending ? (
          <p className="mt-0.5 inline-flex items-center gap-1 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            Zapisywanie…
          </p>
        ) : null}
      </div>
    </li>
  );
}
