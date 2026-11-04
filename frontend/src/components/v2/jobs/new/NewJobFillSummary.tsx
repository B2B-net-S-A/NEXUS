"use client";

/**
 * Pasek pod „Wypełnij z…” na `/jobs/new` (D3, 10.10.2026): ile pól wypełnił
 * ostatni odczyt, ile propozycji czeka przy polach i „Cofnij wypełnienie”.
 * Cofnięcie zdejmuje tylko to, co wpisał odczyt i czego nikt potem nie ruszył.
 */

import { Undo2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { IntakeSource } from "@/lib/job-intake-fill";
import { countPl } from "@/lib/plural-pl";

/** Ostatnie wypełnienie — to, które da się cofnąć. */
export interface NewJobFillInfo {
  source: IntakeSource;
  /** Nazwa pliku albo tytuł rekrutacji-szablonu. */
  sourceName: string | null;
  /** Ile pól wypełnił odczyt. */
  filled: number;
  /** Plik był wypełnionym wzorem Profilu Championa — przepisany bez AI. */
  championForm?: boolean;
  /**
   * Sekcje wzoru bez pola w formularzu: `taken` — formularz je wziął, `kept` —
   * zostały te z wcześniejszego pliku, `none` — plik ich nie miał.
   */
  championSections?: "taken" | "kept" | "none";
}

const CHAMPION_SECTIONS_NOTE: Record<NonNullable<NewJobFillInfo["championSections"]>, string> = {
  taken:
    " Sekcje, których tu nie ma (frazy do searchu, wiedza z rozmów), trafią do profilu rekrutacji.",
  kept: " Sekcje, których tu nie ma, zostają z pierwszego pliku.",
  none: "",
};

interface NewJobFillSummaryProps {
  fill: NewJobFillInfo | null;
  /** Ile propozycji czeka teraz przy polach (także z zapisanego formularza). */
  offers: number;
  onUndo: () => void;
  disabled?: boolean;
}

function sourcePhrase(fill: NewJobFillInfo): string {
  if (fill.source === "file")
    return fill.sourceName ? `Z pliku ${fill.sourceName}` : "Z pliku";
  if (fill.source === "template")
    return fill.sourceName ? `Z rekrutacji „${fill.sourceName}”` : "Z innej rekrutacji";
  return "Z wklejonej treści";
}

export function NewJobFillSummary({ fill, offers, onUndo, disabled = false }: NewJobFillSummaryProps) {
  if (!fill && offers === 0) return null;
  const waiting =
    offers > 0
      ? `${countPl(offers, "propozycja czeka", "propozycje czekają", "propozycji czeka")} na „Użyj”`
      : null;
  return (
    <div
      role="status"
      data-testid="new-job-fill-summary"
      className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-foreground"
    >
      <p className="min-w-0 flex-1">
        {fill ? (
          <>
            {sourcePhrase(fill)}:{" "}
            {fill.filled > 0
              ? `wypełniono ${countPl(fill.filled, "pole", "pola", "pól")}`
              : "nie było pustych pól do wypełnienia"}
            {waiting ? ` · ${waiting}` : ""}.
            {fill.championForm ? (
              <span className="block text-muted-foreground" data-testid="champion-form-note">
                To formularz Profilu Championa — przepisany bez AI.
                {CHAMPION_SECTIONS_NOTE[fill.championSections ?? "none"]}
              </span>
            ) : null}
          </>
        ) : (
          <>{waiting} — przy polach, w których odczyt miał inną wartość.</>
        )}
      </p>
      {fill ? (
        <Button type="button" size="sm" variant="ghost" onClick={onUndo} disabled={disabled}>
          <Undo2 className="h-3.5 w-3.5" aria-hidden /> Cofnij wypełnienie
        </Button>
      ) : null}
    </div>
  );
}
