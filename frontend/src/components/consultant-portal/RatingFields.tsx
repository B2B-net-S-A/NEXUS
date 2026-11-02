"use client";

import { useState } from "react";
import { Clock, Star } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Textarea } from "@/components/ui/textarea";
import type { PortalRatingInput } from "@/lib/api/consultant-portal";
import { cn } from "@/lib/utils";

/** Ocena rozmowy: gwiazdki, „czy załatwione”, komentarz. Link i portal używają tego samego. */
export function RatingFields({
  busy,
  error,
  footnote,
  onSubmit,
}: {
  busy: boolean;
  error: string | null;
  footnote?: string;
  onSubmit: (input: PortalRatingInput) => void;
}) {
  const [score, setScore] = useState(0);
  const [resolved, setResolved] = useState<boolean | null>(null);
  const [comment, setComment] = useState("");
  return (
    <div className="space-y-4">
      <div className="flex justify-center gap-2" role="radiogroup" aria-label="Ocena od 1 do 5">
        {[1, 2, 3, 4, 5].map((value) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={score === value}
            aria-label={`${value} z 5`}
            onClick={() => setScore(value)}
            className={cn(
              "inline-flex size-12 items-center justify-center rounded-xl border",
              value <= score ? "border-warning bg-warning-muted" : "bg-card",
            )}
          >
            <Star aria-hidden className={cn("size-6", value <= score ? "fill-warning text-warning" : "text-border")} />
          </button>
        ))}
      </div>
      <div>
        <p className="text-sm font-medium">Czy sprawa jest załatwiona?</p>
        <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
          {(
            [
              [true, "Tak"],
              [false, "Jeszcze nie"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={label}
              type="button"
              aria-pressed={resolved === value}
              onClick={() => setResolved(value)}
              className={cn(
                "rounded-lg border px-3 py-2 text-center",
                resolved === value
                  ? "border-primary bg-primary/10 font-medium text-primary"
                  : "text-muted-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <FormField label="Komentarz (opcjonalnie)" htmlFor="rating-comment">
        <Textarea
          id="rating-comment"
          rows={3}
          maxLength={2000}
          value={comment}
          onChange={(event) => setComment(event.target.value)}
        />
      </FormField>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <Button
        className="w-full"
        disabled={busy || score === 0}
        onClick={() => onSubmit({ score, resolved, comment: comment.trim() || null })}
      >
        Wyślij ocenę
      </Button>
      <p className="flex items-center justify-center gap-1 text-center text-xs text-muted-foreground">
        <Clock aria-hidden className="size-3 shrink-0" />
        {footnote ?? "Ocena idzie do kierownika back office, a nie wprost do osoby prowadzącej."}
      </p>
    </div>
  );
}
