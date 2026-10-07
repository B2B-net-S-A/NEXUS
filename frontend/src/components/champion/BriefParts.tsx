"use client";

/**
 * Wspólne klocki Briefu Championa (wydzielone 07.10.2026): wiersz faktu,
 * chipy technologii z dymkiem słowniczka „po ludzku” i nazwy ze stacku.
 *
 * Czytają je „Profil Championa → Brief” i zakładka „Wymagania” w podglądzie
 * obok formularza screeningu — jeden wygląd w obu miejscach.
 */

import type { ReactNode } from "react";
import { Star } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { ChampionProfile } from "@/lib/api";
import type { GlossaryTerm } from "@/lib/api/plainKnowledge";
import { includesLabel } from "@/lib/critical-skills";
import { glossaryKey } from "@/lib/plain-glossary-lookup";

export function Fact({ label, value, muted = false }: { label: string; value: ReactNode; muted?: boolean }) {
  return (
    <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-2 py-1">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={muted ? "text-[13px] text-muted-foreground" : "text-[13px] font-medium text-foreground"}>
        {value}
      </dd>
    </div>
  );
}

/** Dymek ze słowniczka „po ludzku” — tylko hasła z opisem. */
export function GlossaryTip({ term }: { term: GlossaryTerm }) {
  return (
    <div className="max-w-[18rem] space-y-1 text-left text-xs leading-snug">
      <p className="font-semibold">{term.display_name}</p>
      <p>{term.summary}</p>
      {term.cv_hints.length > 0 ? <p>W CV szukaj też: {term.cv_hints.join(", ")}</p> : null}
      {term.confused_with ? <p>Nie myl z: {term.confused_with}</p> : null}
    </div>
  );
}

export function Chips({
  items,
  tone,
  critical = [],
  glossary,
  onPick,
}: {
  items: string[];
  tone: "must" | "nice";
  /** Pozycje, na których działa bramka (gwiazdka „krytyczna”). */
  critical?: readonly string[];
  glossary: Map<string, GlossaryTerm>;
  /** Klik w chip (np. „szukaj w CV”). Chip ze słowniczkiem zostaje dymkiem. */
  onPick?: (name: string) => void;
}) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((name) => {
        const isCritical = includesLabel(critical, name);
        const term = glossary.get(glossaryKey(name));
        const className =
          tone === "must"
            ? `inline-flex h-[26px] items-center gap-1 rounded-full bg-primary/10 px-2.5 text-xs font-medium text-primary${isCritical ? " ring-1 ring-primary" : ""}`
            : "inline-flex h-[26px] items-center rounded-full bg-muted px-2.5 text-xs font-medium text-muted-foreground";
        const content = (
          <>
            {isCritical ? <Star className="h-3 w-3 fill-current" aria-hidden /> : null}
            {name}
            {isCritical ? <span className="sr-only"> — krytyczna</span> : null}
          </>
        );
        return (
          <li key={`${tone}:${name}`} data-critical={isCritical || undefined} className="flex">
            {term ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className={`${className} cursor-help decoration-dotted underline-offset-2 hover:underline`}
                    data-glossary={term.term_key}
                    onClick={onPick ? () => onPick(name) : undefined}
                  >
                    {content}
                  </button>
                </TooltipTrigger>
                <TooltipContent side="bottom">
                  <GlossaryTip term={term} />
                </TooltipContent>
              </Tooltip>
            ) : onPick ? (
              <button
                type="button"
                className={`${className} hover:underline`}
                onClick={() => onPick(name)}
                title={`Szukaj „${name}” w CV`}
              >
                {content}
              </button>
            ) : (
              <span className={className}>{content}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function stackNames(items: ChampionProfile["stack"]["must"] | undefined): string[] {
  return (items ?? []).map((item) => item?.name?.trim() ?? "").filter(Boolean);
}
