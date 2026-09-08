"use client";

/**
 * Jeden wiersz listy „gotowość zlecenia" doku kroku 01/02 (makieta: `.ready .it`).
 *
 * Osobny moduł, a nie funkcja lokalna w `JobReadinessDock`, bo wiersze tej listy
 * pochodzą z DWÓCH komponentów: cztery rysuje dok (właściciel, budżet,
 * must/nice, hiring manager), a trzy — `ChampionVerificationChecklist`
 * (rozmowa z klientem, rozmowa z konsultantem, briefing), bo tylko on ma
 * mutacje oznaczania weryfikacji i podpinania nagrania. Gdyby każdy z nich
 * miał własną kopię tej powłoki, jedna lista rozjechałaby się wizualnie na
 * granicy trzeciego i czwartego wiersza. Import w drugą stronę (checklista →
 * dok) byłby cyklem: dok montuje checklistę.
 */

import type { ReactNode } from "react";
import { AlertCircle, Check, Minus } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * `done` — warunek spełniony · `todo` — brakuje czegoś, co da się uzupełnić ·
 * `neutral` — nie przypisano/nie dotyczy.
 *
 * `todo` i `neutral` są rozróżnione, bo znaczą co innego: „brak briefingu" to
 * praca do zrobienia, a „hiring manager nie przypisany" bywa stanem trwałym.
 * Jeden kolor na oba kazałby czytać ostrzeżenie tam, gdzie go nie ma.
 */
export type ReadinessRowState = "done" | "todo" | "neutral";

const STATE_ICON_CLASS: Record<ReadinessRowState, string> = {
  done: "bg-success text-success-foreground",
  todo: "bg-warning text-warning-foreground",
  neutral: "bg-muted text-muted-foreground",
};

const STATE_SR_LABEL: Record<ReadinessRowState, string> = {
  done: "spełnione",
  todo: "do uzupełnienia",
  neutral: "nie przypisano",
};

export interface ReadinessRowProps {
  state: ReadinessRowState;
  title: string;
  /** Jedna linia — co konkretnie jest (albo czego brakuje). */
  description: ReactNode;
  /** Akcja po prawej (link/przycisk). Brak = nic do zrobienia z tego miejsca. */
  action?: ReactNode;
  /** Rozwinięcie pod wierszem (np. formularz weryfikacji, odtwarzacz nagrania). */
  children?: ReactNode;
  className?: string;
  "data-testid"?: string;
}

export function ReadinessRow({
  state,
  title,
  description,
  action,
  children,
  className,
  "data-testid": testId,
}: ReadinessRowProps) {
  const Icon = state === "done" ? Check : state === "todo" ? AlertCircle : Minus;
  return (
    <div
      className={cn(
        "rounded-lg border border-border/70 bg-card text-xs",
        className,
      )}
      data-testid={testId}
      data-state={state}
    >
      <div className="flex items-start gap-2 px-2.5 py-2">
        <span
          className={cn(
            "mt-px flex h-4 w-4 shrink-0 items-center justify-center rounded",
            STATE_ICON_CLASS[state],
          )}
        >
          <Icon className="h-2.5 w-2.5" aria-hidden="true" />
          {/* Stan nie tylko kolorem — czytnik ekranu i daltonizm. */}
          <span className="sr-only">{STATE_SR_LABEL[state]}</span>
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-semibold leading-snug text-foreground">{title}</div>
          <div className="text-[11px] leading-snug text-muted-foreground">
            {description}
          </div>
        </div>
        {action ? <div className="shrink-0 pt-px">{action}</div> : null}
      </div>
      {children ? (
        <div className="border-t border-border/70 px-2.5 pb-2.5 pt-2">{children}</div>
      ) : null}
    </div>
  );
}
