"use client";

/**
 * Wspólna powłoka okien wysuwanych rekrutacji (widok „jedna tabela", 09.2026).
 *
 * Dawne zakładki (Zlecenie, Baza pytań, Historia, Czat, Szukaj ręcznie)
 * otwierają się teraz OBOK tabeli, żeby ta nie traciła miejsca. Powłoka jest
 * jedna, bo cztery okna muszą zachowywać się identycznie: prawa krawędź, Esc
 * zamyka, fokus uwięziony w oknie, tytuł podpięty przez `aria-labelledby` —
 * wszystko to daje Radix Dialog pod `components/ui/sheet`.
 *
 * Treść (`children`) montuje się WYŁĄCZNIE przy otwartym oknie: Radix nie
 * renderuje `Dialog.Content` po zamknięciu, więc zapytania czatu, banku pytań
 * czy wyszukiwarki nie lecą na samo wejście na stronę rekrutacji.
 */

import type { ReactNode } from "react";

import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

export type RecruitmentSheetWidth = "standard" | "wide";

// Pełne literały klas (Tailwind skanuje źródła, nie składa fragmentów).
// `standard` = 540 px z makiety; `wide` = wyszukiwarka z filtrami i tabelą,
// której 540 px nie pomieści.
const WIDTH_CLASS: Record<RecruitmentSheetWidth, string> = {
  standard: "sm:max-w-[540px]",
  wide: "sm:max-w-[min(1100px,92vw)]",
};

export interface RecruitmentSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /**
   * Jedno zdanie pod tytułem. Wymagane, bo Radix ostrzega o dialogu bez
   * opisu, a czytnik ekranu dostaje dzięki niemu kontekst okna.
   */
  description: string;
  /** Opis tylko dla czytników (gdy wizualnie powtarzałby tytuł). */
  descriptionHidden?: boolean;
  width?: RecruitmentSheetWidth;
  /** Pasek pod nagłówkiem, poza przewijaną treścią (np. zakładki). */
  toolbar?: ReactNode;
  /** Stopka przyklejona do dołu (np. akcja niszcząca oddzielona od treści). */
  footer?: ReactNode;
  bodyClassName?: string;
  children: ReactNode;
  "data-testid"?: string;
}

export function RecruitmentSheet({
  open,
  onOpenChange,
  title,
  description,
  descriptionHidden = false,
  width = "standard",
  toolbar,
  footer,
  bodyClassName,
  children,
  "data-testid": testId,
}: RecruitmentSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className={WIDTH_CLASS[width]}
        data-testid={testId}
      >
        <SheetHeader className={cn("pr-12", toolbar ? "pb-0" : undefined)}>
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription className={descriptionHidden ? "sr-only" : undefined}>
            {description}
          </SheetDescription>
          {toolbar ? <div className="pt-2">{toolbar}</div> : null}
        </SheetHeader>
        <SheetBody className={bodyClassName}>{children}</SheetBody>
        {footer ? (
          <div className="border-t border-border bg-background/40 px-6 py-3">
            {footer}
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
