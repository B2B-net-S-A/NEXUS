"use client";

/**
 * Drobne klocki bloku „Po ludzku”: znacznik pochodzenia tekstu, lista źródeł
 * i plakietka „z internetu”. Wspólne dla Podglądu Championa, ściągi w doku,
 * biblioteki ról, słowniczka i karty klienta.
 */

import type { ReactNode } from "react";

import type { PlainSource } from "@/lib/api/plainKnowledge";
import { cn } from "@/lib/utils";

export type PlainOriginKind = "role" | "glossary" | "client" | "job";

const ORIGIN_LABEL: Record<PlainOriginKind, string> = {
  role: "biblioteka ról",
  glossary: "słowniczek",
  client: "karta klienta",
  job: "ta rekrutacja",
};

const ORIGIN_DOT: Record<PlainOriginKind, string> = {
  role: "bg-primary",
  glossary: "bg-success",
  client: "bg-warning",
  job: "bg-muted-foreground",
};

/** Mały znacznik „skąd ten tekst” (mono 11 px + kolorowy kwadrat). */
export function ProvenanceMark({ kind, className }: { kind: PlainOriginKind; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground",
        className,
      )}
      data-provenance={kind}
    >
      <span className={cn("h-2 w-2 shrink-0 rounded-[2px]", ORIGIN_DOT[kind])} aria-hidden="true" />
      {ORIGIN_LABEL[kind]}
    </span>
  );
}

export function PlainEyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </p>
  );
}

/** Tylko adresy http(s) — źródło z modelu nie może wstawić `javascript:`. */
export function safeSources(sources: readonly PlainSource[] | null | undefined): PlainSource[] {
  return (sources ?? []).filter((s) => /^https?:\/\//i.test(s.url ?? ""));
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Makieta: 1–3 linki; research zapisuje ich więcej. */
export const MAX_SOURCE_LINKS = 3;

export function SourceLinks({
  sources,
  className,
  limit = MAX_SOURCE_LINKS,
}: {
  sources: readonly PlainSource[] | null | undefined;
  className?: string;
  limit?: number;
}) {
  const items = safeSources(sources).slice(0, limit);
  if (items.length === 0) return null;
  return (
    <ul className={cn("flex flex-wrap gap-x-3 gap-y-1 text-xs", className)} aria-label="Źródła">
      {items.map((s) => (
        <li key={s.url} className="min-w-0">
          <a
            href={s.url}
            target="_blank"
            rel="noopener noreferrer"
            className="break-words text-primary hover:underline"
          >
            {s.title?.trim() || hostOf(s.url)}
          </a>
        </li>
      ))}
    </ul>
  );
}

/** Plakietka „z internetu” — tekst ułożyło AI z publicznych źródeł. */
export function WebOriginChip({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-full border border-border px-2 text-[11px] text-muted-foreground",
        className,
      )}
      title="Opis ułożony z publicznych źródeł — sprawdź, zanim powtórzysz kandydatowi"
    >
      z internetu
    </span>
  );
}
