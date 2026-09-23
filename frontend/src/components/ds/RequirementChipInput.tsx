"use client";

/**
 * Pole listy wymagań z chipami: wpisujesz, Enter/przecinek dodaje, Backspace
 * na pustym polu usuwa ostatni. Każdy chip ma przełącznik **Musi / Mile**,
 * a przy dziedzinie — opcjonalne „min. lat”.
 *
 * Używa go sekcja 4 Profilu Championa (edytor i `/jobs/new`). Poziom jest na
 * chipie, a nie w dwóch osobnych polach, bo dziedzina/certyfikat zwykle ma
 * jedną-dwie pozycje — dwa pola na dwie pozycje to więcej ekranu niż treści.
 */

import { useId, useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";

import type { ExperienceItem, ExperienceLevel } from "@/lib/api";
import { addExperienceItems, EXPERIENCE_LEVEL_LABEL } from "@/lib/champion-experience";
import { cn } from "@/lib/utils";

export interface RequirementChipInputProps {
  label: string;
  hint?: string;
  items: readonly ExperienceItem[];
  onChange: (items: ExperienceItem[]) => void;
  /** Pole „min. lat” na chipie — tylko dziedzina. */
  withYears?: boolean;
  suggestions?: readonly string[];
  disabled?: boolean;
  placeholder?: string;
  testId?: string;
}

export function RequirementChipInput({
  label,
  hint,
  items,
  onChange,
  withYears = false,
  suggestions = [],
  disabled = false,
  placeholder = "wpisz i naciśnij Enter",
  testId,
}: RequirementChipInputProps) {
  const inputId = useId();
  const listId = useId();
  const hintId = useId();
  const [draft, setDraft] = useState("");

  const commit = () => {
    if (!draft.trim()) return;
    onChange(addExperienceItems(items, draft));
    setDraft("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit();
    } else if (e.key === "Backspace" && !draft && items.length > 0) {
      onChange(items.slice(0, -1));
    }
  };

  const patch = (index: number, change: Partial<ExperienceItem>) =>
    onChange(items.map((item, i) => (i === index ? { ...item, ...change } : item)));

  const toggleLevel = (index: number) => {
    const next: ExperienceLevel = items[index].level === "must" ? "nice" : "must";
    patch(index, { level: next });
  };

  return (
    <div className="flex flex-col gap-1.5" data-testid={testId}>
      <label
        htmlFor={inputId}
        className="text-[10px] uppercase tracking-wide text-muted-foreground"
      >
        {label}
      </label>
      <div
        className={cn(
          "flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border border-border bg-card px-1.5 py-1",
          disabled && "opacity-60",
        )}
      >
        {items.map((item, index) => (
          <span
            key={`${item.name}-${index}`}
            className={cn(
              "inline-flex h-7 items-center gap-1 rounded-md border pl-2 pr-1 text-xs font-medium",
              item.level === "must"
                ? "border-primary/30 bg-primary/10 text-primary"
                : "border-border bg-transparent text-foreground",
            )}
            data-testid={testId ? `${testId}-chip` : undefined}
          >
            <span>{item.name}</span>
            {withYears ? (
              <span className="inline-flex items-center gap-0.5 text-[11px] font-normal text-muted-foreground">
                <span aria-hidden="true">min.</span>
                <input
                  type="number"
                  aria-label={`Minimalna liczba lat w dziedzinie ${item.name}`}
                  min={0}
                  max={40}
                  disabled={disabled}
                  value={item.min_years ?? ""}
                  onChange={(e) =>
                    patch(index, {
                      min_years: e.target.value === "" ? null : Number(e.target.value),
                    })
                  }
                  className="h-5 w-9 rounded border border-border bg-card px-1 text-[11px] text-foreground"
                />
                <span aria-hidden="true">l.</span>
              </span>
            ) : null}
            <button
              type="button"
              disabled={disabled}
              onClick={() => toggleLevel(index)}
              aria-label={`${item.name}: ${item.level === "must" ? "wymagane" : "mile widziane"} — zmień`}
              title="Przełącz: musi mieć / mile widziane"
              className={cn(
                "rounded px-1 text-[10px] uppercase tracking-wide",
                item.level === "must"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground",
              )}
            >
              {EXPERIENCE_LEVEL_LABEL[item.level]}
            </button>
            <button
              type="button"
              disabled={disabled}
              aria-label={`Usuń ${item.name}`}
              className="rounded p-0.5 opacity-70 hover:opacity-100"
              onClick={() => onChange(items.filter((_, i) => i !== index))}
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          </span>
        ))}
        <input
          id={inputId}
          value={draft}
          disabled={disabled}
          list={suggestions.length ? listId : undefined}
          aria-describedby={hint ? hintId : undefined}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={commit}
          placeholder={items.length === 0 ? placeholder : "dodaj…"}
          className="h-7 min-w-[8rem] flex-1 bg-transparent px-1 text-xs text-foreground outline-hidden placeholder:text-muted-foreground"
        />
        {suggestions.length ? (
          <datalist id={listId}>
            {suggestions.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
        ) : null}
      </div>
      {hint ? (
        <p id={hintId} className="text-[11px] text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
