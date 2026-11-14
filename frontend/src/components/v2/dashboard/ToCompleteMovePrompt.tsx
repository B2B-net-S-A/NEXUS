"use client";

/**
 * Linia „Przenieś na pulpit” nad listami do uzupełnienia w „Czeka na Ciebie”
 * (21.10.2026, plansza A4 makiet). Jedno kliknięcie stawia kafelek „Do
 * uzupełnienia” na górze siatki; „Zostaw tutaj” chowa linię, a listy zostają
 * w panelu. Kafelek dodaje i zapisuje pulpit (`CustomDashboard`).
 */

import { LayoutGrid } from "lucide-react";

import { Button } from "@/components/ui/button";

interface ToCompleteMovePromptProps {
  onMove: () => void;
  onKeep: () => void;
  busy?: boolean;
}

export function ToCompleteMovePrompt({ onMove, onKeep, busy = false }: ToCompleteMovePromptProps) {
  return (
    <div
      role="group"
      aria-label="Do uzupełnienia"
      className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-primary/25 bg-primary/5 px-3 py-2 text-sm lg:col-span-3"
    >
      {/* Podstawa 16rem, nie 0 (`flex-1`): przy podstawie 0 wiersz nigdy się nie
          zawijał i w wąskim oknie (390 px) tekst stał po jednym słowie w linii,
          a przyciski na nim. Teraz brak miejsca na tekst + przyciski = przyciski
          spadają pod tekst (14.11.2026). */}
      <p className="min-w-0 flex-[1_1_16rem]" data-testid="to-complete-move-text">
        <strong className="font-semibold">Do uzupełnienia</strong>{" "}
        <span className="text-muted-foreground">
          — umowy do zamknięcia, rekrutacje do dokończenia i wymagania do poprawy możesz trzymać
          w osobnym kafelku i postawić go w dowolnym miejscu pulpitu.
        </span>
      </p>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <Button size="sm" onClick={onMove} disabled={busy}>
          <LayoutGrid className="h-3.5 w-3.5" aria-hidden />
          Przenieś na pulpit
        </Button>
        <Button size="sm" variant="ghost" onClick={onKeep}>
          Zostaw tutaj
        </Button>
      </div>
    </div>
  );
}
