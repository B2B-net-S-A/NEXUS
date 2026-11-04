"use client";

import { useState } from "react";
import { Droppable } from "@hello-pangea/dnd";
import { Check } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { CASE_STATUS_LABELS, type CaseCard } from "@/lib/api/admin-cases";
import type { CareBoardDone } from "@/lib/api/care-board";
import { formatDayMonthPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { doneSummary } from "./work-board-model";

const DONE_PREVIEW = 5;

/**
 * Wąska kolumna „Zrobione” (makieta 19.10.2026): sprawy zrobione z liczbą
 * z miesiąca, „Pokaż zamknięte”. Od 22.10.2026 także upuszczenie karty
 * (sprawa = status „Zrobione”, karta opieki = okno zapisu) i — gdy tablica
 * pokazuje opiekę — zapisane w tym tygodniu rozmowy i opinie. Nagłówek ma
 * jedną liczbę (makieta K1): sprawy z miesiąca + opieka z tygodnia, pod nim
 * „41 spraw w miesiącu · 5 rozmów i opinii w tym tygodniu”. Zamknięta
 * decyzja „Do przepięcia” ma „Otwórz ponownie” (wpis wraca na „W toku”).
 */
export function DoneColumn({
  done,
  closed,
  doneThisMonth,
  showCases,
  careDone,
  showClosed,
  onToggleClosed,
  onOpen,
  onReopenDecision,
  reopening = null,
  dropDisabled,
}: {
  done: CaseCard[];
  closed: CaseCard[];
  doneThisMonth: number;
  showCases: boolean;
  careDone: CareBoardDone | null;
  showClosed: boolean;
  onToggleClosed: () => void;
  onOpen: (card: CaseCard) => void;
  /** „Otwórz ponownie” zamkniętej decyzji „Do przepięcia” (klucz `decision:<id>`). */
  onReopenDecision?: (key: string) => void;
  /** Klucz decyzji, której ponowne otwarcie trwa. */
  reopening?: string | null;
  dropDisabled: boolean;
}) {
  const [all, setAll] = useState(false);
  const visible = all ? done : done.slice(0, DONE_PREVIEW);
  const summary = doneSummary({
    casesMonth: showCases ? doneThisMonth : null,
    careWeek: careDone ? careDone.this_week : null,
  });
  const counted = showCases || careDone;
  const row = (card: CaseCard) => (
    <li key={card.id}>
      <button
        type="button"
        onClick={() => onOpen(card)}
        aria-label={`Sprawa: ${card.title}`}
        className="flex w-full items-start gap-1.5 rounded-md bg-card px-2 py-1.5 text-left text-[12.5px] hover:bg-muted"
      >
        <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
        <span className="line-clamp-2">{card.title}</span>
      </button>
    </li>
  );
  return (
    <Droppable droppableId="done" isDropDisabled={dropDisabled}>
      {(provided, snapshot) => (
        <section
          ref={provided.innerRef}
          {...provided.droppableProps}
          aria-labelledby="cases-col-done"
          className={cn(
            "flex min-w-0 flex-col gap-2 rounded-xl border border-dashed border-border bg-muted/30 p-2.5 transition-colors",
            snapshot.isDraggingOver && "border-primary/40 bg-primary/10",
          )}
        >
          <div className="flex items-center justify-between px-1">
            <h3 id="cases-col-done" className="text-[13.5px] font-semibold">
              {CASE_STATUS_LABELS.done}
            </h3>
            {counted ? (
              <Badge size="sm" variant="success" className="tabular-nums" title={summary.text}>
                {summary.total}
              </Badge>
            ) : null}
          </div>
          {counted ? <p className="px-1 text-xs text-muted-foreground">{summary.text}</p> : null}
          {showCases && visible.length ? (
            <ul className="flex flex-col gap-1">{visible.map(row)}</ul>
          ) : null}
          {showCases && done.length > DONE_PREVIEW ? (
            <button
              type="button"
              className="self-start px-1 text-[12.5px] text-primary hover:underline"
              onClick={() => setAll((value) => !value)}
            >
              {all ? "Zwiń" : `Pokaż wszystkie (${done.length})`}
            </button>
          ) : null}
          {careDone ? (
            <>
              {careDone.recent.length ? (
                <ul className="flex flex-col gap-1">
                  {careDone.recent.slice(0, DONE_PREVIEW).map((item) => (
                    <li
                      key={`${item.key}:${item.done_on}`}
                      className="flex items-start gap-1.5 rounded-md bg-card px-2 py-1.5 text-[12.5px]"
                    >
                      <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
                      <span className="flex min-w-0 flex-1 flex-col items-start">
                        <span className="line-clamp-2">{item.title}</span>
                        {item.kind === "decision" && onReopenDecision ? (
                          // Pomyłkowe „Nie dotyczy” da się cofnąć (decyzja Artura 22.10.2026, F107).
                          <button
                            type="button"
                            disabled={reopening === item.key}
                            aria-label={`Otwórz ponownie: ${item.title}`}
                            className="text-[11.5px] text-primary hover:underline disabled:opacity-50"
                            onClick={() => onReopenDecision(item.key)}
                          >
                            Otwórz ponownie
                          </button>
                        ) : null}
                      </span>
                      <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                        {formatDayMonthPl(item.done_on)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : null}
          {/* Miejsce na kartę w trakcie przeciągania — zaraz po upuszczeniu i tak znika. */}
          <div className="hidden">{provided.placeholder}</div>
          {showCases && showClosed ? (
            <>
              <h3 className="px-1 pt-1 text-[13px] font-semibold">{CASE_STATUS_LABELS.closed}</h3>
              {closed.length ? (
                <ul className="flex flex-col gap-1">{closed.map(row)}</ul>
              ) : (
                <p className="px-1 text-xs text-muted-foreground">Brak zamkniętych.</p>
              )}
            </>
          ) : null}
          {showCases ? (
            <button
              type="button"
              aria-pressed={showClosed}
              className="self-start px-1 text-[12.5px] text-muted-foreground hover:text-foreground hover:underline"
              onClick={onToggleClosed}
            >
              Pokaż zamknięte
            </button>
          ) : null}
        </section>
      )}
    </Droppable>
  );
}
