"use client";

import { cn } from "@/lib/utils";

export interface ToggleOption<T> {
  value: T;
  label: string;
}

interface ToggleGroupProps<T> {
  /** Id etykiety grupy (`aria-labelledby`). */
  labelledBy: string;
  options: ReadonlyArray<ToggleOption<T>>;
  isPressed: (value: T) => boolean;
  onToggle: (value: T) => void;
  disabled?: boolean;
  className?: string;
}

/**
 * Rząd przycisków `aria-pressed` z formularza rozmowy. Prawdziwe przyciski
 * (Tab, Spacja, czytnik ekranu), ≥ 44 px na dotyku, wybór zaznaczony też
 * kształtem obramowania i grubością — nie samym kolorem.
 */
export function ToggleGroup<T>({
  labelledBy,
  options,
  isPressed,
  onToggle,
  disabled,
  className,
}: ToggleGroupProps<T>) {
  return (
    <div role="group" aria-labelledby={labelledBy} className={cn("flex flex-wrap gap-2", className)}>
      {options.map((option) => {
        const pressed = isPressed(option.value);
        return (
          <button
            key={String(option.value)}
            type="button"
            aria-pressed={pressed}
            disabled={disabled}
            onClick={() => onToggle(option.value)}
            className={cn(
              "min-h-10 rounded-lg border px-3 text-sm transition-colors pointer-coarse:min-h-11",
              "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              "disabled:cursor-not-allowed disabled:opacity-50",
              pressed
                ? "border-primary bg-primary/10 font-semibold text-primary ring-1 ring-inset ring-primary"
                : "border-border bg-card font-medium text-foreground hover:bg-muted",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
