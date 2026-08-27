"use client";

import type { OrderType } from "@/lib/api/dlPortal";

const OPTIONS: Array<{ value: OrderType; label: string }> = [
  { value: "periodic", label: "Okresowe" },
  { value: "cost", label: "Kosztowe" },
  { value: "md", label: "MD" },
];

interface OrderTypeSwitchProps {
  value: OrderType;
  onChange: (value: OrderType) => void;
  disabled?: boolean;
}

export function OrderTypeSwitch({
  value,
  onChange,
  disabled = false,
}: OrderTypeSwitchProps) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-sm font-medium text-foreground">
        Typ zamówienia
      </legend>
      <div
        className="grid grid-cols-3 rounded-lg border border-border bg-muted/40 p-1"
        role="radiogroup"
        aria-label="Typ zamówienia"
      >
        {OPTIONS.map((option) => {
          const selected = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              onClick={() => onChange(option.value)}
              className={`rounded-md px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                selected
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
      {disabled ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Typu nie można zmienić po utworzeniu zamówienia.
        </p>
      ) : null}
    </fieldset>
  );
}
