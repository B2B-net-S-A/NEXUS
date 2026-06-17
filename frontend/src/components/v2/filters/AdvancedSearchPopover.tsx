"use client";

import { useState, type KeyboardEvent, type ReactNode } from "react";
import { Plus, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/**
 * Advanced (Traffit-style) boolean search value.
 *
 * - `all`  — every phrase must appear (AND).
 * - `any`  — MULTIPLE OR-groups that AND together. Each inner array is one
 *   OR-group (phrases combined with OR); the groups combine with AND. So
 *   `[["React","TypeScript"],["Java","Node.js"]]` means
 *   `(React OR TypeScript) AND (Java OR Node.js)`. A single group keeps the
 *   classic "any of these" behaviour and is backward compatible.
 * - `none` — no phrase may appear (NOT).
 */
export interface AdvancedSearchValue {
  all: string[];
  any: string[][];
  none: string[];
}

interface AdvancedSearchPopoverProps {
  value: AdvancedSearchValue;
  onChange: (next: AdvancedSearchValue) => void;
  className?: string;
}

const MAX_PER_BUCKET = 20;
const MAX_ANY_GROUPS = 5;
const MIN_PHRASE_LEN = 2;

type Tone = "emerald" | "sky" | "rose";

const TONE_CLASSES: Record<Tone, string> = {
  emerald:
    "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-200 dark:border-emerald-800",
  sky: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-900/30 dark:text-sky-200 dark:border-sky-800",
  rose: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-900/30 dark:text-rose-200 dark:border-rose-800",
};

const LABEL_TONE_CLASSES: Record<Tone, string> = {
  emerald: "text-emerald-700 dark:text-emerald-300",
  sky: "text-sky-700 dark:text-sky-300",
  rose: "text-rose-700 dark:text-rose-300",
};

const DOT_TONE_CLASSES: Record<Tone, string> = {
  emerald: "bg-emerald-500",
  sky: "bg-sky-500",
  rose: "bg-rose-500",
};

/** Section heading with a tone-colored dot + colored text to set each bucket apart. */
function ToneLabel({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs font-semibold",
        LABEL_TONE_CLASSES[tone],
      )}
    >
      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT_TONE_CLASSES[tone])} />
      {children}
    </span>
  );
}

function dedupeCaseInsensitive(xs: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of xs) {
    const trimmed = raw.trim();
    const key = trimmed.toLowerCase();
    if (trimmed.length >= MIN_PHRASE_LEN && !seen.has(key)) {
      seen.add(key);
      out.push(trimmed);
    }
    if (out.length >= MAX_PER_BUCKET) break;
  }
  return out;
}

/**
 * A single chip input: owns its draft text, commits on Enter/comma/blur,
 * removes the last chip on Backspace-when-empty. Emits the full new chip list
 * to `onChange` (already deduped + capped).
 */
function ChipField({
  chips,
  onChange,
  placeholder,
  tone,
}: {
  chips: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
  tone: Tone;
}) {
  const [draft, setDraft] = useState("");
  const limitReached = chips.length >= MAX_PER_BUCKET;

  const commit = () => {
    if (!draft.trim()) return;
    const fresh = draft
      .split(",")
      .map((x) => x.trim())
      .filter((x) => x.length >= MIN_PHRASE_LEN);
    if (fresh.length > 0) onChange(dedupeCaseInsensitive([...chips, ...fresh]));
    setDraft("");
  };

  const removeAt = (index: number) => {
    onChange(chips.filter((_, i) => i !== index));
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit();
    } else if (e.key === "Backspace" && draft.length === 0 && chips.length > 0) {
      e.preventDefault();
      removeAt(chips.length - 1);
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      {chips.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {chips.map((phrase, i) => (
            <Badge
              key={`${phrase}-${i}`}
              variant="outline"
              className={cn("gap-1 pl-2 pr-1 py-0.5 font-normal", TONE_CLASSES[tone])}
            >
              <span className="max-w-[180px] truncate">{phrase}</span>
              <button
                type="button"
                onClick={() => removeAt(i)}
                title="Usuń frazę"
                className="inline-flex items-center justify-center rounded hover:bg-black/10 dark:hover:bg-card/10"
              >
                <X className="w-3 h-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
      <Input
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={commit}
        placeholder={limitReached ? `Limit ${MAX_PER_BUCKET} fraz osiągnięty` : placeholder}
        disabled={limitReached}
        className="h-8 text-sm"
      />
    </div>
  );
}

export function AdvancedSearchPopover({
  value,
  onChange,
  className,
}: AdvancedSearchPopoverProps) {
  // Always render at least one ANY group row so there's somewhere to type.
  // Empty groups live in state transiently and are filtered out at the URL /
  // API serialization boundary, so they never leak into a query.
  const anyGroups = value.any.length > 0 ? value.any : [[]];

  const setAll = (next: string[]) =>
    onChange({ ...value, all: dedupeCaseInsensitive(next) });
  const setNone = (next: string[]) =>
    onChange({ ...value, none: dedupeCaseInsensitive(next) });

  const setGroup = (gi: number, next: string[]) => {
    onChange({
      ...value,
      any: anyGroups.map((g, i) => (i === gi ? dedupeCaseInsensitive(next) : g)),
    });
  };
  const addGroup = () => {
    if (anyGroups.length >= MAX_ANY_GROUPS) return;
    onChange({ ...value, any: [...anyGroups, []] });
  };
  const removeGroup = (gi: number) => {
    onChange({ ...value, any: anyGroups.filter((_, i) => i !== gi) });
  };
  const clearAny = () => onChange({ ...value, any: [] });

  const clearAll = () => onChange({ all: [], any: [], none: [] });

  const anyPhraseCount = value.any.reduce((n, g) => n + g.length, 0);
  const totalCount = value.all.length + anyPhraseCount + value.none.length;
  const canAddGroup = anyGroups.length < MAX_ANY_GROUPS;

  return (
    <div className={cn("flex flex-col gap-4 p-1", className)}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-foreground dark:text-foreground">
            Zaawansowane wyszukiwanie
          </h3>
          <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-0.5">
            Enter lub przecinek dodaje frazę. Spacje dozwolone. Zawęża wyniki wyszukiwania prostego.
          </p>
        </div>
        {totalCount > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={clearAll}
            className="shrink-0 h-7 px-2 text-xs"
          >
            Wyczyść wszystko
          </Button>
        )}
      </div>

      {/* ALL — every phrase must appear (AND) */}
      <section className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <label>
            <ToneLabel tone="emerald">
              Wszystkie z wymienionych fraz
              {value.all.length > 0 && (
                <span className="text-muted-foreground dark:text-muted-foreground font-normal">
                  ({value.all.length}/{MAX_PER_BUCKET})
                </span>
              )}
            </ToneLabel>
          </label>
          {value.all.length > 0 && (
            <button
              type="button"
              onClick={() => setAll([])}
              className="text-xs text-muted-foreground hover:text-muted-foreground dark:hover:text-muted-foreground"
            >
              Wyczyść
            </button>
          )}
        </div>
        <ChipField
          chips={value.all}
          onChange={setAll}
          placeholder="np. React, TypeScript…"
          tone="emerald"
        />
      </section>

      {/* ANY — multiple OR-groups that AND together */}
      <section className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <label>
            <ToneLabel tone="sky">
              Którakolwiek z wymienionych fraz
              {anyPhraseCount > 0 && (
                <span className="text-muted-foreground dark:text-muted-foreground font-normal">
                  ({anyPhraseCount})
                </span>
              )}
            </ToneLabel>
          </label>
          {anyPhraseCount > 0 && (
            <button
              type="button"
              onClick={clearAny}
              className="text-xs text-muted-foreground hover:text-muted-foreground dark:hover:text-muted-foreground"
            >
              Wyczyść
            </button>
          )}
        </div>
        <p className="-mt-1 text-[11px] leading-snug text-muted-foreground">
          Frazy w jednej grupie łączą się przez <strong>LUB</strong>; grupy między sobą przez{" "}
          <strong>ORAZ</strong>. Np. (React LUB TypeScript) ORAZ (Java LUB Node.js).
        </p>

        {anyGroups.map((group, gi) => (
          <div key={gi} className="flex flex-col gap-2">
            {gi > 0 && (
              <div className="flex items-center gap-2 py-0.5">
                <div className="h-px flex-1 bg-border" />
                <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  oraz
                </span>
                <div className="h-px flex-1 bg-border" />
              </div>
            )}
            <div className="flex items-start gap-1.5">
              <div className="flex-1">
                <ChipField
                  chips={group}
                  onChange={(next) => setGroup(gi, next)}
                  placeholder={gi === 0 ? "np. React, TypeScript…" : "np. Java, Node.js…"}
                  tone="sky"
                />
              </div>
              {anyGroups.length > 1 && (
                <button
                  type="button"
                  onClick={() => removeGroup(gi)}
                  title="Usuń grupę"
                  aria-label={`Usuń grupę ${gi + 1}`}
                  className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-900/30"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>
        ))}

        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addGroup}
          disabled={!canAddGroup}
          className="h-7 w-fit gap-1 px-2 text-xs"
        >
          <Plus className="h-3.5 w-3.5" />
          {canAddGroup ? "Dodaj grupę (ORAZ)" : `Limit ${MAX_ANY_GROUPS} grup`}
        </Button>
      </section>

      {/* NONE — no phrase may appear (NOT) */}
      <section className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <label>
            <ToneLabel tone="rose">
              Żadna z wymienionych fraz
              {value.none.length > 0 && (
                <span className="text-muted-foreground dark:text-muted-foreground font-normal">
                  ({value.none.length}/{MAX_PER_BUCKET})
                </span>
              )}
            </ToneLabel>
          </label>
          {value.none.length > 0 && (
            <button
              type="button"
              onClick={() => setNone([])}
              className="text-xs text-muted-foreground hover:text-muted-foreground dark:hover:text-muted-foreground"
            >
              Wyczyść
            </button>
          )}
        </div>
        <ChipField
          chips={value.none}
          onChange={setNone}
          placeholder="np. junior, stażysta…"
          tone="rose"
        />
      </section>
    </div>
  );
}
