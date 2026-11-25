"use client";

/**
 * Ostrzeżenie „Nowe CV nie odczytało dat albo firmy” (decyzja Artura 25.11.2026,
 * pętla jakości): CV wgrane z pliku w obcym formacie traci te pola, a takie
 * stanowiska nie trafiają na oś kariery strony 1. Ostrzeżenie, nie blokada —
 * rekruter poprawia w „Stanowiskach” albo zostaje przy Klasycznym.
 */

import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { plural } from "@/lib/cv-new-layout-gaps";
import { cn } from "@/lib/utils";

export interface NewCvRoleGaps {
  without_dates: number;
  without_company: number;
}

export interface NewCvRoleGapsNoteProps {
  gaps: NewCvRoleGaps | null | undefined;
  /** Przejście do zakładki „Stanowiska”; brak = sam tekst (karta „CV do klienta”). */
  onFix?: () => void;
  className?: string;
}

/** „Nowe CV nie odczytało dat w 2 stanowiskach i firmy w 1 stanowisku.” */
export function gapsSentence(gaps: NewCvRoleGaps): string {
  const parts: string[] = [];
  if (gaps.without_dates > 0) parts.push(`dat w ${plural(gaps.without_dates)}`);
  if (gaps.without_company > 0) parts.push(`firmy w ${plural(gaps.without_company)}`);
  return `Nowe CV nie odczytało ${parts.join(" i ")}.`;
}

export function NewCvRoleGapsNote({ gaps, onFix, className }: NewCvRoleGapsNoteProps) {
  if (!gaps || (gaps.without_dates <= 0 && gaps.without_company <= 0)) return null;
  return (
    <div
      role="status"
      data-testid="new-cv-role-gaps"
      className={cn(
        "flex items-start gap-2 rounded-md border border-warning/30 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground",
        className,
      )}
    >
      <AlertTriangle aria-hidden className="mt-0.5 h-3.5 w-3.5 flex-none" />
      <div className="min-w-0 space-y-1">
        <p>
          {gapsSentence(gaps)} Takie stanowiska nie trafią na oś kariery. Uzupełnij je w „Stanowiskach” albo zostań
          przy układzie Klasycznym.
        </p>
        {onFix ? (
          <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={onFix}>
            Popraw w „Stanowiskach”
          </Button>
        ) : null}
      </div>
    </div>
  );
}
