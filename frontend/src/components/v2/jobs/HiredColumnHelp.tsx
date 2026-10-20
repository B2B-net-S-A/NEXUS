"use client";

/**
 * „?” w nagłówku kolumny „Zatrudniony” na Tablicy (20.10.2026).
 *
 * Zespół pytał, czy na „Zatrudniony” przesuwa tylko Delivery Lead i czy bez
 * zamówienia się da. Serwer wpuszcza każdą rolę wewnętrzną
 * (`RECRUITMENT_TERMINAL_ROLES`), a zamówienie zakłada jako szkic po ruchu.
 * Prawdziwe warunki to debrief po rozmowie u klienta (409 `DEBRIEF_REQUIRED`)
 * i „Jak podpisano umowę?” (422 `HIRED_SIGNED_VIA_REQUIRED`). Przy zmianie
 * tych reguł zmień też ten tekst.
 */

import { HelpCircle } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export function HiredColumnHelp() {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Kto przesuwa na „Zatrudniony” i co jest potrzebne"
          data-testid="hired-column-help"
          className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <HelpCircle className="h-3.5 w-3.5" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 space-y-2 text-xs">
        <p className="text-sm font-semibold text-foreground">Kto przesuwa na „Zatrudniony”?</p>
        <p className="text-muted-foreground">Każdy z zespołu rekrutacji — rekruter też.</p>
        <div className="space-y-0.5">
          <p className="font-medium text-foreground">Potrzebne</p>
          <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
            <li>debrief po rozmowie u klienta,</li>
            <li>informacja, jak podpisano umowę.</li>
          </ul>
        </div>
        <div className="space-y-0.5">
          <p className="font-medium text-foreground">Niepotrzebne</p>
          <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
            <li>zamówienie od klienta — szkic powstaje sam, uzupełnia go Delivery Lead i Finanse.</li>
          </ul>
        </div>
        <p className="text-muted-foreground">
          Umowę z Generatora potwierdza osoba z uprawnieniem „Podpis B2B”; pozostali wysyłają
          prośbę do Delivery Leada klienta.
        </p>
      </PopoverContent>
    </Popover>
  );
}
