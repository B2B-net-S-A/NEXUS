"use client";
// „Dodaj aneks ▾” zakładki „Aneksy” (wariant A, 19.11.2026) — jedno menu
// zamiast pięciu kolorowych przycisków. Bramki pozycji przychodzą z zakładki
// (te same co dawniej przy przyciskach); menu tylko je pokazuje.
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/** Aneksy zapisywane formularzem zakładki. */
export type ManualAmendmentType = "extension" | "rate_change" | "scope_change";

export interface AddAnnexMenuProps {
  /** Uprawnienie „Stawki i kwoty: zmiana” u klienta kontraktu. */
  canAmendRates: boolean;
  /** Umowa B2B bez ręcznego zakończenia — backend odrzuca przedłużenie. */
  extensionLocked: boolean;
  /** Dlaczego przedłużenia nie ma (pod wyłączoną pozycją). */
  extensionHint: string;
  onPick: (type: ManualAmendmentType) => void;
  /** Okno „Zakończ współpracę” ze strony; bez niego pozycji nie ma. */
  onRequestTermination?: () => void;
  /** Generator aneksów z umową bazową tego kontraktu. */
  documentHref: string;
  /**
   * Kotwica nowości na przycisku. Nagłówek strony ma to samo menu bez niej,
   * żeby przeklikanie wskazało przycisk w zakładce „Aneksy”, do której prowadzi.
   */
  tourAnchor?: boolean;
}

export function AddAnnexMenu({
  canAmendRates,
  extensionLocked,
  extensionHint,
  onPick,
  onRequestTermination,
  documentHref,
  tourAnchor = true,
}: AddAnnexMenuProps) {
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        {/* Kotwica nowości „Aneks stawki klienta zmienia też zamówienie” —
            „Zmiana stawki” jest w tym menu. */}
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-tour={tourAnchor && canAmendRates ? "contract.amendments.rate-change" : undefined}
        >
          Dodaj aneks
          <ChevronDown className="size-3.5" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        {canAmendRates ? (
          <DropdownMenuItem onSelect={() => onPick("rate_change")}>Zmiana stawki</DropdownMenuItem>
        ) : null}
        <DropdownMenuItem onSelect={() => onPick("scope_change")}>Zmiana zakresu</DropdownMenuItem>
        <DropdownMenuItem disabled={extensionLocked} onSelect={() => onPick("extension")}>
          Przedłużenie
        </DropdownMenuItem>
        {extensionLocked ? (
          <p className="px-2 pb-1.5 text-[11.5px] leading-4 text-muted-foreground">{extensionHint}</p>
        ) : null}
        {onRequestTermination ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={onRequestTermination}
              className="text-muted-foreground focus:bg-destructive/10 focus:text-destructive"
            >
              Zakończenie wcześniej…
            </DropdownMenuItem>
          </>
        ) : null}
        <DropdownMenuSeparator />
        {/* Dokument aneksu do podpisu (DOCX) — zakładka „Generator aneksów”
            w Generatorze umów B2B, umowa bazowa po tym kontrakcie. */}
        <DropdownMenuItem asChild className="flex-col items-start gap-0">
          <Link href={documentHref}>
            Wygeneruj dokument aneksu
            <span className="text-[11.5px] leading-4 text-muted-foreground">
              Generator aneksów — zmiana po podpisie
            </span>
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
