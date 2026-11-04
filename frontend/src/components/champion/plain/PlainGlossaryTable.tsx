"use client";

/**
 * Słowniczek rekrutacji: technologie z profilu wyjaśnione po ludzku.
 *
 * Pełna szerokość, jedna siatka dla nagłówka i KAŻDEGO wiersza — kolumny
 * muszą się zgadzać w pionie (poprzednia makieta rozjeżdżała się, bo każdy
 * wiersz liczył szerokości sam). Tekst się zawija, nigdy nie jest ucinany.
 * Wąski kontener (telefon, dok) układa komórki jedna pod drugą.
 */

import { ChevronRight } from "lucide-react";

import type { GlossaryTerm } from "@/lib/api/plainKnowledge";
import { cn } from "@/lib/utils";

import { SourceLinks, safeSources } from "./PlainBits";

/** Wspólny szablon kolumn nagłówka i wierszy (zmieniasz tu — zmienia się wszędzie). */
export const GLOSSARY_GRID =
  "@xl:grid @xl:grid-cols-[170px_minmax(0,1.3fr)_minmax(0,1fr)_16px] @xl:gap-x-4";

function statusText(term: GlossaryTerm): string | null {
  if (term.status === "researching") return "Szukam opisu…";
  if (term.status === "missing" || term.status === "failed") return "Brak opisu";
  return null;
}

function hasDetails(term: GlossaryTerm): boolean {
  return Boolean(
    term.in_this_project?.trim() ||
      term.confused_with?.trim() ||
      term.does?.trim() ||
      safeSources(term.sources).length > 0,
  );
}

function GlossaryRow({ term }: { term: GlossaryTerm }) {
  const pending = statusText(term);
  const summary = term.summary?.trim() || null;
  const hints = term.cv_hints.filter((h) => h.trim());
  const expandable = hasDetails(term);
  const cells = (
    <>
      <div className="min-w-0">
        <p className="break-words text-sm font-semibold text-foreground">{term.display_name}</p>
        <p
          className={cn(
            "text-[11px]",
            term.level === "must" ? "font-medium text-primary" : "text-muted-foreground",
          )}
        >
          {term.level_label}
        </p>
      </div>
      <div className="mt-1 min-w-0 @xl:mt-0">
        {summary ? (
          <p className="break-words text-[13px] leading-snug text-foreground">{summary}</p>
        ) : (
          <p className="text-[13px] italic text-muted-foreground" data-testid="glossary-status">
            {pending ?? "Brak opisu"}
          </p>
        )}
      </div>
      <div className="mt-1 min-w-0 @xl:mt-0">
        <span className="text-[11px] text-muted-foreground @xl:hidden">W CV szukaj: </span>
        <span className="break-words text-[13px] text-foreground">
          {hints.length > 0 ? hints.join(", ") : <span className="text-muted-foreground">—</span>}
        </span>
      </div>
      <div className="hidden items-start pt-0.5 @xl:flex" aria-hidden="true">
        {expandable ? (
          <ChevronRight className="h-4 w-4 text-muted-foreground transition-transform group-open:rotate-90" />
        ) : null}
      </div>
    </>
  );

  if (!expandable) {
    return (
      <div
        className={cn("border-t border-border px-3 py-2.5", GLOSSARY_GRID)}
        data-testid="glossary-row"
      >
        {cells}
      </div>
    );
  }

  return (
    <details className="group border-t border-border" data-testid="glossary-row">
      <summary
        className={cn(
          "cursor-pointer list-none px-3 py-2.5 hover:bg-muted/40 [&::-webkit-details-marker]:hidden",
          GLOSSARY_GRID,
        )}
      >
        {cells}
      </summary>
      <div className={cn("px-3 pb-3", GLOSSARY_GRID)}>
        <div className="space-y-2 @xl:col-span-2 @xl:col-start-2">
          {term.does?.trim() ? (
            <p className="text-[13px] text-foreground">{term.does}</p>
          ) : null}
          {term.in_this_project?.trim() ? (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                W tym projekcie
              </p>
              <p className="text-[13px] text-foreground">{term.in_this_project}</p>
            </div>
          ) : null}
          {term.confused_with?.trim() ? (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Nie myl z
              </p>
              <p className="text-[13px] text-foreground">{term.confused_with}</p>
            </div>
          ) : null}
          {safeSources(term.sources).length > 0 ? (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Źródła
              </p>
              <SourceLinks sources={term.sources} />
            </div>
          ) : null}
        </div>
      </div>
    </details>
  );
}

export function PlainGlossaryTable({ terms }: { terms: readonly GlossaryTerm[] }) {
  if (terms.length === 0) return null;
  return (
    <div
      className="@container overflow-hidden rounded-lg border border-border"
      data-testid="plain-glossary"
    >
      <div
        className={cn(
          "hidden bg-muted/50 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground",
          GLOSSARY_GRID,
        )}
        data-testid="glossary-header"
      >
        <span>Technologia</span>
        <span>Po ludzku</span>
        <span>W CV szukaj</span>
        <span aria-hidden="true" />
      </div>
      {terms.map((term) => (
        <GlossaryRow key={term.term_key} term={term} />
      ))}
    </div>
  );
}
