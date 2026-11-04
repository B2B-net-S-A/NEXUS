"use client";

/**
 * Propozycja przy polu formularza `/jobs/new` (D3, 10.10.2026): odczyt maila,
 * pliku albo szablonu ma inną wartość niż ta, którą wpisał Delivery Lead.
 * Odczyt nie nadpisuje niczego sam — „Użyj” bierze wartość z odczytu, „Zostaw”
 * zostawia wpisaną. Ten sam wzór co „Z notatki: …” w formularzu screeningu.
 */

import type { Ref } from "react";

import { Button } from "@/components/ui/button";
import { INTAKE_SOURCE_PREFIX, type IntakeOffer } from "@/lib/job-intake-fill";

interface IntakeOfferChipProps {
  offer: IntakeOffer;
  onUse: () => void;
  onDismiss: () => void;
  /** Kontener propozycji — pole formularza szuka od niego kontrolki do fokusu. */
  ref?: Ref<HTMLDivElement>;
}

export function IntakeOfferChip({ offer, onUse, onDismiss, ref }: IntakeOfferChipProps) {
  // Wymagania i pytania dochodzą do listy — „Dodaj”, nie „Użyj”.
  const verb = offer.unit === "rows" || offer.unit === "questions" ? "Dodaj" : "Użyj";
  return (
    <div
      ref={ref}
      data-testid="intake-offer"
      data-unit={offer.unit}
      className="flex flex-wrap items-center gap-2 rounded-md border border-primary/30 bg-primary/5 px-2.5 py-1.5 text-xs text-muted-foreground"
    >
      <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
        {INTAKE_SOURCE_PREFIX[offer.source]}:{" "}
        <span className="font-medium text-foreground">{offer.text}</span>
      </span>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={onUse}
        aria-label={`${verb} — ${offer.label}`}
      >
        {verb}
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        onClick={onDismiss}
        aria-label={`Zostaw — ${offer.label}`}
      >
        Zostaw
      </Button>
    </div>
  );
}
