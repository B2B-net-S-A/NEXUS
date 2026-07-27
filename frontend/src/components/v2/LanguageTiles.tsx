"use client";

import type { ReactNode } from "react";
import { CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";

export type CvLanguage = "pl" | "en";

const FLAG_CLASS =
  "h-5 w-7 shrink-0 overflow-hidden rounded-[2px] shadow-xs ring-1 ring-black/10";

/** Polska flaga — biel u góry, czerwień u dołu. */
function FlagPL() {
  return (
    <svg viewBox="0 0 24 16" className={FLAG_CLASS} aria-hidden="true">
      <rect width="24" height="16" fill="#fff" />
      <rect y="8" width="24" height="8" fill="#DC143C" />
    </svg>
  );
}

/** Flaga USA — 13 pasów + niebieski kanton z gwiazdkami (uproszczone). */
function FlagUS() {
  const stripe = 14 / 13;
  return (
    <svg viewBox="0 0 26 14" className={FLAG_CLASS} aria-hidden="true">
      <rect width="26" height="14" fill="#fff" />
      {[0, 2, 4, 6, 8, 10, 12].map((i) => (
        <rect key={i} y={i * stripe} width="26" height={stripe} fill="#B22234" />
      ))}
      <rect width="10.4" height={7 * stripe} fill="#3C3B6E" />
      {[0, 1, 2].map((row) =>
        [0, 1, 2].map((col) => (
          <circle
            key={`${row}-${col}`}
            cx={1.7 + col * 3.4}
            cy={1.4 + row * 2.3}
            r="0.6"
            fill="#fff"
          />
        )),
      )}
    </svg>
  );
}

function LanguageTile({
  selected,
  onSelect,
  flag,
  label,
}: {
  selected: boolean;
  onSelect: () => void;
  flag: ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn(
        "relative flex min-w-0 items-center gap-3 rounded-lg border p-3 text-left transition-colors",
        "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        selected
          ? "border-primary bg-primary/5 ring-1 ring-primary"
          : "border-border bg-card hover:bg-accent",
      )}
    >
      {flag}
      <span className="truncate text-sm font-medium text-foreground">
        {label}
      </span>
      {selected && (
        <CheckCircle2
          className="ml-auto h-4 w-4 shrink-0 text-primary"
          aria-hidden="true"
        />
      )}
    </button>
  );
}

interface LanguageTilesProps {
  value: CvLanguage;
  onChange: (lang: CvLanguage) => void;
  className?: string;
  ariaLabel?: string;
}

/**
 * Selektor języka CV w formie dwóch kafelków z flagami (PL / EN) — wspólny dla
 * standalone'owej strony generatora i modala. Zachowanie radiogroup +
 * aria-checked dla dostępności.
 */
export function LanguageTiles({
  value,
  onChange,
  className,
  ariaLabel = "Język CV",
}: LanguageTilesProps) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cn("grid grid-cols-2 gap-3", className)}
    >
      <LanguageTile
        selected={value === "pl"}
        onSelect={() => onChange("pl")}
        flag={<FlagPL />}
        label="Polski"
      />
      <LanguageTile
        selected={value === "en"}
        onSelect={() => onChange("en")}
        flag={<FlagUS />}
        label="English"
      />
    </div>
  );
}
