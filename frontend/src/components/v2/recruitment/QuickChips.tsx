"use client";

/**
 * Pasek szybkich filtrów nad tabelą osób: tekst, chipy z licznikami, rekruter,
 * grupowanie i sortowanie. W pełni kontrolowany — stan trzyma
 * `RecruitmentWorkspace`, bo te same wartości zasilają buildery z
 * `person-rows.ts`.
 *
 * Chipy to przełączniki (`aria-pressed`), nie zakładki: można włączyć kilka
 * naraz i wtedy zawężają łącznie (AND).
 */

import { Rows3, Search } from "lucide-react";

import { cn } from "@/lib/utils";

import {
  PERSON_SORT_LABEL,
  QUICK_CHIP_LABEL,
  QUICK_CHIP_ORDER,
  type PersonSortKey,
  type QuickChipKey,
  type RecruiterOption,
} from "./person-rows";

export interface QuickChipsProps {
  chips: ReadonlySet<QuickChipKey>;
  counts: Record<QuickChipKey, number>;
  onToggleChip: (chip: QuickChipKey) => void;

  text: string;
  onTextChange: (value: string) => void;

  recruiters: RecruiterOption[];
  recruiterId: number | null;
  onRecruiterChange: (id: number | null) => void;

  grouped: boolean;
  onGroupedChange: (grouped: boolean) => void;

  sortKey: PersonSortKey;
  onSortKeyChange: (key: PersonSortKey) => void;

  /** Prawa strona paska (np. „+ Dodaj kandydatów"). */
  actions?: React.ReactNode;
  className?: string;
}

const SORT_KEYS: readonly PersonSortKey[] = ["action", "days", "fit", "name"];

const selectClass =
  "h-8 rounded-md border border-border bg-card px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function QuickChips({
  chips,
  counts,
  onToggleChip,
  text,
  onTextChange,
  recruiters,
  recruiterId,
  onRecruiterChange,
  grouped,
  onGroupedChange,
  sortKey,
  onSortKeyChange,
  actions,
  className,
}: QuickChipsProps) {
  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      <label className="relative">
        <span className="sr-only">Filtruj listę osób</span>
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <input
          type="search"
          value={text}
          onChange={(event) => onTextChange(event.target.value)}
          placeholder="Filtruj po nazwisku, etapie…"
          className="h-8 w-60 rounded-md border border-border bg-card pl-8 pr-2 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      </label>

      <div role="group" aria-label="Szybkie filtry" className="flex flex-wrap items-center gap-1.5">
        {QUICK_CHIP_ORDER.map((chip) => {
          const pressed = chips.has(chip);
          const count = counts[chip] ?? 0;
          return (
            <button
              key={chip}
              type="button"
              aria-pressed={pressed}
              onClick={() => onToggleChip(chip)}
              className={cn(
                "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                pressed
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-border bg-card text-foreground hover:bg-muted",
                // „Po terminie" z niezerowym licznikiem ma być widoczne bez klikania.
                !pressed && chip === "overdue" && count > 0 && "border-destructive/40 text-destructive-muted-foreground",
                !pressed && count === 0 && "text-muted-foreground",
              )}
            >
              {QUICK_CHIP_LABEL[chip]}
              <span className="tabular-nums opacity-80">{count}</span>
            </button>
          );
        })}
      </div>

      <span className="flex-1" />

      {recruiters.length > 1 ? (
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span className="sr-only">Rekruter</span>
          <select
            aria-label="Rekruter"
            value={recruiterId == null ? "" : String(recruiterId)}
            onChange={(event) =>
              onRecruiterChange(event.target.value === "" ? null : Number(event.target.value))
            }
            className={selectClass}
          >
            <option value="">Wszyscy rekruterzy</option>
            {recruiters.map((recruiter) => (
              <option key={recruiter.id} value={recruiter.id}>
                {recruiter.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <button
        type="button"
        aria-pressed={grouped}
        onClick={() => onGroupedChange(!grouped)}
        title="Grupuj wiersze według tego, po czyjej stronie jest ruch"
        className={cn(
          "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          grouped
            ? "border-primary bg-primary/10 text-primary"
            : "border-border bg-card text-foreground hover:bg-muted",
        )}
      >
        <Rows3 className="size-3.5" aria-hidden />
        Grupuj: kto ma ruch
      </button>

      <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
        Sortuj
        <select
          aria-label="Sortowanie"
          value={sortKey}
          onChange={(event) => onSortKeyChange(event.target.value as PersonSortKey)}
          className={selectClass}
        >
          {SORT_KEYS.map((key) => (
            <option key={key} value={key}>
              {PERSON_SORT_LABEL[key]}
            </option>
          ))}
        </select>
      </label>

      {actions}
    </div>
  );
}
