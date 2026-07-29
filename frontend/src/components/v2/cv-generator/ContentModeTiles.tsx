"use client";

import { AlertTriangle } from "lucide-react";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { CV_CONTENT_MODES, type CvContentMode } from "@/lib/cv-generator";
import { cn } from "@/lib/utils";

interface ContentModeTilesProps {
  value: CvContentMode;
  onChange: (mode: CvContentMode) => void;
  className?: string;
  ariaLabel?: string;
}

/**
 * Wybór trybu obróbki treści CV — wspólny dla modala (CVGeneratorV2) i strony
 * standalone. Opcje pochodzą z `CV_CONTENT_MODES`, żeby obie powierzchnie nie
 * rozjechały się na kopiach tej samej tablicy.
 *
 * Świadomie NIE jest drabinką jakości: kafelki mają identyczną wagę wizualną,
 * bez numeracji i bez „lepszej" opcji na końcu. Każdy wariant niesie własny
 * opis, bo rekruter ma rozumieć wybór bez zaglądania do dokumentacji.
 */
export function ContentModeTiles({
  value,
  onChange,
  className,
  ariaLabel = "Obróbka treści",
}: ContentModeTilesProps) {
  return (
    <RadioGroup
      value={value}
      onValueChange={(next) => onChange(next as CvContentMode)}
      aria-label={ariaLabel}
      className={cn("grid grid-cols-1 gap-3", className)}
    >
      {CV_CONTENT_MODES.map((option) => (
        <label
          key={option.value}
          className={cn(
            "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors",
            option.value === value
              ? "border-primary bg-primary/5"
              : "border-border hover:bg-muted/30",
          )}
        >
          <RadioGroupItem value={option.value} className="mt-1 shrink-0" />
          <div className="min-w-0 space-y-1">
            <div className="text-sm font-medium text-foreground">
              {option.label}
            </div>
            <p className="text-xs text-muted-foreground">{option.description}</p>
            {option.caution && (
              // Wprost w kafelku, nie w tooltipie: to ograniczenie zastosowania,
              // które musi być widoczne w momencie wyboru.
              <p className="flex items-start gap-1.5 rounded-md bg-warning-muted px-2 py-1 text-xs text-warning-muted-foreground">
                <AlertTriangle
                  className="mt-0.5 h-3 w-3 shrink-0"
                  aria-hidden="true"
                />
                <span>{option.caution}</span>
              </p>
            )}
          </div>
        </label>
      ))}
    </RadioGroup>
  );
}
