"use client";

import { useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface AdvancedSearchValue {
  all: string[];
  any: string[];
  none: string[];
}

interface AdvancedSearchPopoverProps {
  value: AdvancedSearchValue;
  onChange: (next: AdvancedSearchValue) => void;
  className?: string;
}

const MAX_PER_BUCKET = 20;
const MIN_PHRASE_LEN = 2;

type Bucket = keyof AdvancedSearchValue;

const BUCKET_META: Record<
  Bucket,
  { label: string; placeholder: string; tone: "emerald" | "sky" | "rose" }
> = {
  all: {
    label: "Wszystkie z wymienionych fraz",
    placeholder: "np. React, TypeScript…",
    tone: "emerald",
  },
  any: {
    label: "Którakolwiek z wymienionych fraz",
    placeholder: "np. Next.js, Remix…",
    tone: "sky",
  },
  none: {
    label: "Żadna z wymienionych fraz",
    placeholder: "np. junior, stażysta…",
    tone: "rose",
  },
};

const TONE_CLASSES: Record<"emerald" | "sky" | "rose", string> = {
  emerald:
    "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-200 dark:border-emerald-800",
  sky: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-900/30 dark:text-sky-200 dark:border-sky-800",
  rose: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-900/30 dark:text-rose-200 dark:border-rose-800",
};

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

export function AdvancedSearchPopover({
  value,
  onChange,
  className,
}: AdvancedSearchPopoverProps) {
  const [drafts, setDrafts] = useState<Record<Bucket, string>>({
    all: "",
    any: "",
    none: "",
  });

  const setBucket = (bucket: Bucket, next: string[]) => {
    onChange({ ...value, [bucket]: dedupeCaseInsensitive(next) });
  };

  const commitDraft = (bucket: Bucket) => {
    const raw = drafts[bucket];
    if (!raw.trim()) return;
    const fresh = raw
      .split(",")
      .map((x) => x.trim())
      .filter((x) => x.length >= MIN_PHRASE_LEN);
    if (fresh.length === 0) {
      setDrafts((d) => ({ ...d, [bucket]: "" }));
      return;
    }
    setBucket(bucket, [...value[bucket], ...fresh]);
    setDrafts((d) => ({ ...d, [bucket]: "" }));
  };

  const removeAt = (bucket: Bucket, index: number) => {
    const next = value[bucket].filter((_, i) => i !== index);
    setBucket(bucket, next);
  };

  const clearBucket = (bucket: Bucket) => {
    setBucket(bucket, []);
    setDrafts((d) => ({ ...d, [bucket]: "" }));
  };

  const clearAll = () => {
    onChange({ all: [], any: [], none: [] });
    setDrafts({ all: "", any: "", none: "" });
  };

  const handleKeyDown = (bucket: Bucket) => (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commitDraft(bucket);
    } else if (
      e.key === "Backspace" &&
      drafts[bucket].length === 0 &&
      value[bucket].length > 0
    ) {
      e.preventDefault();
      removeAt(bucket, value[bucket].length - 1);
    }
  };

  const totalCount = value.all.length + value.any.length + value.none.length;

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

      {(Object.keys(BUCKET_META) as Bucket[]).map((bucket) => {
        const meta = BUCKET_META[bucket];
        const chips = value[bucket];
        const limitReached = chips.length >= MAX_PER_BUCKET;
        return (
          <section key={bucket} className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-foreground dark:text-muted-foreground">
                {meta.label}
                {chips.length > 0 && (
                  <span className="ml-1.5 text-muted-foreground dark:text-muted-foreground font-normal">
                    ({chips.length}/{MAX_PER_BUCKET})
                  </span>
                )}
              </label>
              {chips.length > 0 && (
                <button
                  type="button"
                  onClick={() => clearBucket(bucket)}
                  className="text-xs text-muted-foreground hover:text-muted-foreground dark:hover:text-muted-foreground"
                >
                  Wyczyść
                </button>
              )}
            </div>

            {chips.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {chips.map((phrase, i) => (
                  <Badge
                    key={`${phrase}-${i}`}
                    variant="outline"
                    className={cn(
                      "gap-1 pl-2 pr-1 py-0.5 font-normal",
                      TONE_CLASSES[meta.tone],
                    )}
                  >
                    <span className="max-w-[180px] truncate">{phrase}</span>
                    <button
                      type="button"
                      onClick={() => removeAt(bucket, i)}
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
              value={drafts[bucket]}
              onChange={(e) =>
                setDrafts((d) => ({ ...d, [bucket]: e.target.value }))
              }
              onKeyDown={handleKeyDown(bucket)}
              onBlur={() => commitDraft(bucket)}
              placeholder={limitReached ? `Limit ${MAX_PER_BUCKET} fraz osiągnięty` : meta.placeholder}
              disabled={limitReached}
              className="h-8 text-sm"
            />
          </section>
        );
      })}
    </div>
  );
}
