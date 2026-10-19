"use client";

import { cn } from "@/lib/utils";
import { unknownFieldBadges } from "@/lib/candidate-search-semantics";

/**
 * Plakietki „brak lokalizacji / brak stażu / brak stawki" — osoba przeszła
 * aktywny filtr tylko dlatego, że nie mamy o niej danych (`unknown_fields`
 * z backendu, semantyka v2). Bez plakietki taki wiersz czytałby się jak
 * trafienie spełniające kryterium.
 */
export function UnknownFieldBadges({
  fields,
  className,
}: {
  fields: readonly string[] | null | undefined;
  className?: string;
}) {
  const badges = unknownFieldBadges(fields);
  if (badges.length === 0) return null;
  return (
    <span className={cn("inline-flex flex-wrap gap-1", className)}>
      {badges.map((b) => (
        <span
          key={b.field}
          title={b.hint}
          data-testid={`unknown-field-${b.field}`}
          className="inline-flex items-center rounded-full border border-dashed border-border px-1.5 py-0.5 text-[10px] text-muted-foreground"
        >
          {b.label}
        </span>
      ))}
    </span>
  );
}

/** „Ukryj osoby bez danych" — `hide_unknown` w obu silnikach. */
export function HideUnknownToggle({
  checked,
  onChange,
  className,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  className?: string;
}) {
  return (
    <label
      className={cn(
        "inline-flex cursor-pointer select-none items-center gap-1.5 text-xs",
        className,
      )}
      title="Dotyczy filtrów lokalizacji, lat doświadczenia i stawki: bez zaznaczenia osoby bez tych danych zostają na liście z plakietką."
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 rounded border-input text-primary focus:ring-ring"
      />
      <span>Ukryj osoby bez danych</span>
    </label>
  );
}

/**
 * D5 (19.10.2026): „Osoby bez stawki / bez miasta w profilu: pokaż na końcu
 * listy / ukryj” w okienku samego filtru — węższe niż „Ukryj osoby bez
 * danych”, które działa na stawkę, miasto i staż naraz.
 */
export function HideUnknownChoice({
  label,
  hidden,
  onChange,
  className,
}: {
  /** „Osoby bez stawki”, „Osoby bez miasta w profilu”. */
  label: string;
  hidden: boolean;
  onChange: (hidden: boolean) => void;
  className?: string;
}) {
  const choices = [
    { value: false, text: "pokaż na końcu listy" },
    { value: true, text: "ukryj" },
  ] as const;
  return (
    <div className={cn("space-y-1", className)}>
      <span className="block text-[11px] font-medium text-foreground">{label}</span>
      <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1.5">
        {choices.map((choice) => {
          const checked = hidden === choice.value;
          return (
            <button
              key={choice.text}
              type="button"
              role="radio"
              aria-checked={checked}
              onClick={() => onChange(choice.value)}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
                checked
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-foreground hover:bg-accent",
              )}
            >
              {choice.text}
            </button>
          );
        })}
      </div>
    </div>
  );
}
