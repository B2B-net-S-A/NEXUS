"use client";

import { ArrowRightLeft } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import { WORK_COLUMNS, WORK_COLUMN_LABELS, type WorkColumn } from "./work-board-model";

/**
 * „Przenieś do…” — ruch karty bez myszy (klawiatura, czytnik ekranu, dotyk).
 * Ta sama ścieżka co przeciągnięcie (`moveAction`).
 */
export function MoveMenu({
  title,
  current,
  onMove,
}: {
  title: string;
  current: WorkColumn | "closed";
  onMove: (target: WorkColumn) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={`Przenieś do…: ${title}`}
          title="Przenieś do…"
          className="hit-area grid size-6 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <ArrowRightLeft className="h-3.5 w-3.5" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel className="text-xs text-muted-foreground">Przenieś do…</DropdownMenuLabel>
        {WORK_COLUMNS.filter((column) => column !== current).map((column) => (
          <DropdownMenuItem key={column} onSelect={() => onMove(column)}>
            {WORK_COLUMN_LABELS[column]}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
