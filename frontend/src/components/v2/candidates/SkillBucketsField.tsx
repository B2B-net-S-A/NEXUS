"use client";

import { useId, useState, type KeyboardEvent } from "react";
import { X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  SKILL_BUCKET_LABELS,
  SKILL_BUCKET_LIMIT,
  parseSkillBucketInput,
  skillEntryLabel,
  type SkillBucket,
  type SkillBucketsValue,
} from "@/lib/candidate-search-semantics";

const BUCKETS: readonly SkillBucket[] = ["required", "preferred", "excluded"];

const BUCKET_HINTS: Record<SkillBucket, string> = {
  required: "tylko osoby, które to mają",
  preferred: "podnosi w kolejności, nikogo nie usuwa",
  excluded: "usuwa osoby, które to mają",
};

const CHIP_TONE: Record<SkillBucket, string> = {
  required: "bg-primary/10 text-primary",
  preferred: "bg-info-muted text-info-muted-foreground",
  excluded: "bg-destructive-muted text-destructive-muted-foreground",
};

interface SkillBucketsFieldProps {
  value: SkillBucketsValue;
  onChange: (next: SkillBucketsValue) => void;
  className?: string;
  /** Etykieta pola wpisywania (dostępna nazwa). */
  inputLabel?: string;
  /**
   * Wąska kolumna (lista kandydatów, ~250 px): wybór kubełka pod polem,
   * puste kubełki bez opisów — opis mówi jedno zdanie pod spodem.
   */
  compact?: boolean;
}

/**
 * Umiejętności w trzech jawnych kubełkach — wspólne dla listy kandydatów
 * i wyszukiwarki (ta sama semantyka w obu silnikach, decyzja 21.09.2026).
 *
 * Jedno pole + wybór kubełka. Pozycja dodana bez zmiany wyboru trafia do
 * „Musi mieć". `Java|Kotlin` (albo `Java OR Kotlin`) = którakolwiek z grupy,
 * wiodący `-` = „Wyklucz". Tekst zatwierdza Enter, przecinek albo wyjście
 * z pola — nic nie ginie po kliknięciu gdzie indziej.
 */
export function SkillBucketsField({
  value,
  onChange,
  className,
  inputLabel = "Dodaj umiejętność",
  compact = false,
}: SkillBucketsFieldProps) {
  const [draft, setDraft] = useState("");
  const [bucket, setBucket] = useState<SkillBucket>("required");
  const [notice, setNotice] = useState<string | null>(null);
  const groupId = useId();

  const commit = (): void => {
    const additions = parseSkillBucketInput(draft, bucket);
    if (additions.length === 0) {
      setDraft("");
      return;
    }
    const next: SkillBucketsValue = {
      required: [...value.required],
      preferred: [...value.preferred],
      excluded: [...value.excluded],
    };
    const refused: string[] = [];
    let duplicate: string | null = null;
    let added = 0;
    for (const { bucket: target, value: entry } of additions) {
      const list = next[target];
      const key = entry.toLowerCase();
      const presentIn = BUCKETS.find((b) =>
        next[b].some((item) => item.toLowerCase() === key),
      );
      if (presentIn) {
        duplicate = `„${skillEntryLabel(entry)}” jest już w „${SKILL_BUCKET_LABELS[presentIn]}”.`;
        continue;
      }
      if (list.length >= SKILL_BUCKET_LIMIT) {
        refused.push(entry);
        continue;
      }
      list.push(entry);
      added += 1;
    }
    if (refused.length > 0) {
      setNotice(
        `Limit ${SKILL_BUCKET_LIMIT} pozycji w kubełku osiągnięty — usuń którąś, żeby dodać „${refused
          .map(skillEntryLabel)
          .join(", ")}”.`,
      );
      setDraft(refused.join(", "));
    } else {
      setNotice(duplicate);
      setDraft("");
    }
    if (added > 0) onChange(next);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      commit();
    }
  };

  const remove = (target: SkillBucket, index: number) => {
    setNotice(null);
    onChange({
      ...value,
      [target]: value[target].filter((_, i) => i !== index),
    });
  };

  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={commit}
          aria-label={inputLabel}
          placeholder="np. Java, Spring lub Java|Kotlin"
          className={cn("h-8 flex-1 text-xs", compact ? "min-w-0 w-full" : "min-w-[12rem]")}
        />
        <div
          role="radiogroup"
          aria-label="Gdzie dodać umiejętność"
          className={cn(
            "rounded-md border border-border p-0.5",
            compact ? "grid w-full grid-cols-3" : "inline-flex",
          )}
        >
          {BUCKETS.map((b) => (
            <button
              key={b}
              type="button"
              role="radio"
              aria-checked={bucket === b}
              // Wybór nie zabiera tekstu z pola: przycisk nie przejmuje fokusu.
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => setBucket(b)}
              className={cn(
                "rounded px-2 py-1 text-xs leading-tight transition-colors",
                compact && "px-1",
                bucket === b
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted",
              )}
            >
              {SKILL_BUCKET_LABELS[b]}
            </button>
          ))}
        </div>
      </div>
      {notice && (
        <p role="status" className="text-[11px] leading-snug text-warning-muted-foreground">
          {notice}
        </p>
      )}
      <dl className="space-y-1" aria-describedby={`${groupId}-hint`}>
        {BUCKETS.filter((b) => !compact || value[b].length > 0).map((b) => (
          <div key={b} className="flex flex-wrap items-baseline gap-1.5">
            <dt
              className={cn(
                "shrink-0 text-xs font-medium text-muted-foreground",
                compact ? "w-full" : "w-28",
              )}
            >
              {SKILL_BUCKET_LABELS[b]}
            </dt>
            <dd className="flex min-w-0 flex-1 flex-wrap items-center gap-1">
              {value[b].length === 0 ? (
                <span className="text-xs text-muted-foreground">
                  — <span className="sr-only">brak;</span>
                  <span className="ml-1 text-[11px]">{BUCKET_HINTS[b]}</span>
                </span>
              ) : (
                value[b].map((entry, i) => (
                  <span
                    key={`${b}-${entry}-${i}`}
                    data-testid={`skill-chip-${b}`}
                    className={cn(
                      "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs",
                      CHIP_TONE[b],
                    )}
                  >
                    {b === "excluded" ? `bez ${skillEntryLabel(entry)}` : skillEntryLabel(entry)}
                    <button
                      type="button"
                      onClick={() => remove(b, i)}
                      aria-label={`Usuń ${skillEntryLabel(entry)} z „${SKILL_BUCKET_LABELS[b]}”`}
                      className="hover:opacity-70"
                    >
                      <X className="h-3 w-3" aria-hidden="true" />
                    </button>
                  </span>
                ))
              )}
            </dd>
          </div>
        ))}
      </dl>
      <p id={`${groupId}-hint`} className="text-[11px] leading-snug text-muted-foreground">
        „Musi mieć” i „Wyklucz” zawężają wyniki, „Mile widziane” tylko podnosi
        pasujące osoby wyżej. „Java|Kotlin” = którakolwiek z nich.
      </p>
    </div>
  );
}
