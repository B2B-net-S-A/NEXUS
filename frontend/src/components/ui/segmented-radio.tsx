"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

export interface SegmentedRadioOption<T extends string = string> {
  value: T;
  label: React.ReactNode;
  disabled?: boolean;
  /** Podpowiedź przy opcji, np. powód, dla którego jest wyłączona. */
  title?: string;
  /** `id` elementu opisującego opcję (`aria-describedby`). */
  describedBy?: string;
}

interface SegmentedRadioBaseProps<T extends string> {
  /** Wybrana wartość; `null` / `undefined` = nic nie wybrano. */
  value: T | null | undefined;
  onChange: (value: T) => void;
  /** Od dwóch do czterech opcji — więcej to już lista wyboru. */
  options: readonly SegmentedRadioOption<T>[];
  size?: "sm" | "md";
  /** Wyłącza całą grupę. */
  disabled?: boolean;
  className?: string;
}

/** Grupa musi mieć nazwę dla czytników ekranu: tekst albo `id` widocznej etykiety. */
type SegmentedRadioName =
  | {
      /** Nazwa grupy (`aria-label`). */
      label: string;
      labelledBy?: undefined;
    }
  | {
      /** `id` widocznej etykiety grupy (`aria-labelledby`). */
      labelledBy: string;
      label?: undefined;
    };

export type SegmentedRadioProps<T extends string = string> =
  SegmentedRadioBaseProps<T> & SegmentedRadioName;

const SIZE_CLASS: Record<NonNullable<SegmentedRadioBaseProps<string>["size"]>, string> = {
  sm: "min-h-7 px-2.5 py-1 text-xs",
  md: "min-h-8 px-3 py-1.5 text-sm",
};

/**
 * Przełącznik segmentowy „jedno z kilku” (priorytet rekrutacji, rola osoby).
 *
 * Grupa radiowa według wzorca WAI-ARIA: `role="radiogroup"` z opcjami
 * `role="radio"` i `aria-checked`, jeden przystanek Tab na całą grupę, a
 * strzałki przenoszą fokus na sąsiednią opcję i od razu ją wybierają (jak
 * w natywnych polach radio). Opcje wyłączone są pomijane; z ostatniej strzałka
 * wraca na pierwszą. W wąskim kontenerze opcje zawijają się do nowej linii.
 */
export function SegmentedRadio<T extends string = string>({
  value,
  onChange,
  options,
  label,
  labelledBy,
  size = "md",
  disabled = false,
  className,
}: SegmentedRadioProps<T>) {
  const buttons = React.useRef<Array<HTMLButtonElement | null>>([]);

  const enabled = options
    .map((option, index) => (disabled || option.disabled ? -1 : index))
    .filter((index) => index >= 0);
  const checkedIndex = options.findIndex((option) => option.value === value);
  // Tab zatrzymuje się na wybranej opcji, a gdy nic nie jest wybrane (albo
  // wybrana jest wyłączona) — na pierwszej dostępnej.
  const tabStop = enabled.includes(checkedIndex) ? checkedIndex : enabled[0];

  const select = (index: number) => {
    const option = options[index];
    if (option.value !== value) onChange(option.value);
  };

  const move = (from: number, step: 1 | -1) => {
    const position = enabled.indexOf(from);
    if (position < 0 || enabled.length < 2) return;
    const next = enabled[(position + step + enabled.length) % enabled.length];
    buttons.current[next]?.focus();
    select(next);
  };

  const onKeyDown = (
    event: React.KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) => {
    // Strzałka z modyfikatorem to skrót przeglądarki albo systemu
    // (Alt+← = „wstecz”) — nie zmienia wyboru.
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      move(index, 1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      move(index, -1);
    }
  };

  return (
    <div
      role="radiogroup"
      aria-label={label}
      aria-labelledby={labelledBy}
      aria-disabled={disabled || undefined}
      className={cn(
        "inline-flex max-w-full flex-wrap gap-0.5 rounded-lg border border-border bg-card p-0.5",
        className,
      )}
    >
      {options.map((option, index) => {
        const checked = index === checkedIndex;
        return (
          <button
            key={option.value}
            ref={(node) => {
              buttons.current[index] = node;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-describedby={option.describedBy}
            title={option.title}
            disabled={disabled || option.disabled}
            tabIndex={index === tabStop ? 0 : -1}
            onClick={() => select(index)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cn(
              // `relative` + `z-10` przy fokusie: obwódka fokusu nie chowa się
              // pod sąsiednią, wypełnioną opcją.
              "relative inline-flex items-center justify-center whitespace-nowrap rounded-md transition-colors focus-visible:z-10",
              "disabled:cursor-not-allowed disabled:opacity-50 pointer-coarse:min-h-10",
              SIZE_CLASS[size],
              checked
                ? "bg-primary text-primary-foreground"
                : "text-foreground hover:bg-accent disabled:hover:bg-transparent",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
