"use client";

import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";

/** Stan ładowania sekcji profilu. */
export function SectionLoading({ label }: { label: string }) {
  return (
    <div
      className="flex items-center justify-center gap-2 rounded-lg border border-border bg-muted/30 px-4 py-8 text-sm text-muted-foreground"
      aria-busy="true"
    >
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}
    </div>
  );
}

/** Awaria sekcji — nigdy nie udaje pustki („brak danych”). */
export function SectionError({
  title,
  onRetry,
}: {
  title: string;
  onRetry: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive sm:flex-row sm:items-center"
    >
      <span>{title}</span>
      <Button size="sm" variant="outline" onClick={onRetry}>
        Ponów
      </Button>
    </div>
  );
}

/** Nagłówek sekcji w treści zakładki. */
export function SectionHeading({
  id,
  children,
  action,
}: {
  id?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mb-2 flex items-center justify-between gap-2">
      <h3
        id={id}
        className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground"
      >
        {children}
      </h3>
      {action}
    </div>
  );
}

/** Stawka w zapisie „22 000 PLN/mies.”. */
export function formatRate(
  amount: number | null | undefined,
  currency: string | null | undefined,
  unit: string | null | undefined,
): string {
  if (amount == null) return "—";
  const unitLabel =
    unit === "hourly" ? "/h" : unit === "daily" ? "/d" : "/mies.";
  return `${amount.toLocaleString("pl-PL")} ${currency ?? "PLN"}${unitLabel}`;
}

/**
 * Unwrap Traffit-imported note content. Some notes have nested
 * `{"content":"<html>"}` (Traffit "Notatka" type with HTML body) or
 * `{"content":{"content":"<html>","state":{...}}}` (state-change notes).
 * Plus strips HTML tags for plain-text rendering.
 */
export function unwrapNoteContent(raw: unknown): string {
  if (!raw) return "";
  let s = String(raw);
  for (let i = 0; i < 2; i++) {
    if (!s.startsWith("{")) break;
    try {
      const parsed = JSON.parse(s);
      if (parsed && typeof parsed === "object" && "content" in parsed) {
        const inner = (parsed as { content?: unknown }).content;
        if (typeof inner === "string") {
          s = inner;
          continue;
        }
        if (inner && typeof inner === "object" && "content" in inner) {
          const innerStr = (inner as { content?: unknown }).content;
          if (typeof innerStr === "string") {
            s = innerStr;
            continue;
          }
        }
      }
      break;
    } catch {
      break;
    }
  }
  return s
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n\n")
    .replace(/<\/li>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/\\u([0-9a-fA-F]{4})/g, (_, hex) =>
      String.fromCharCode(parseInt(hex, 16)),
    )
    .replace(/\\\//g, "/")
    .replace(/\\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
