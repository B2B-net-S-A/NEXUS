"use client";

/**
 * ChampionSectionNav — lewa kolumna kroku 02 „Zlecenie i Champion" (program
 * „flow w języku C2", PR 5/7).
 *
 * Spis sześciu sekcji Profilu Championa z chipem stanu (pusta / wypełniona /
 * z AI — patrz `lib/champion-section-state.ts`); klik przewija do sekcji w
 * `ChampionProfileEditor` (kotwice `#champion-section-*` dzielone przez oba
 * komponenty z JEDNEGO źródła, `CHAMPION_SECTIONS`).
 *
 * Samodzielny (własne zapytanie, klucz `["champion-profile", jobId]") —
 * tak jak inne komponenty doku tego kroku (`JobOwnershipPanel`,
 * `HiringManagerPicker`, `JobPriorityContext`, `JobHandoffButton`). Ten sam
 * klucz co edytor i dok, więc React Query dedupe'uje fetch zamiast go
 * potrajać. Stan sieci jest drugorzędny tu — to nawigacja, nie źródło
 * prawdy — więc awaria nie blokuje listy, tylko chowa kolorowe kropki.
 */

import { useQuery } from "@tanstack/react-query";

import { championApi, EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import {
  CHAMPION_SECTIONS,
  CHAMPION_SECTION_STATE_LABEL,
  championSectionState,
  type ChampionSectionState,
} from "@/lib/champion-section-state";
import { cn } from "@/lib/utils";

const STATE_DOT_CLASS: Record<ChampionSectionState, string> = {
  empty: "bg-muted-foreground/40",
  filled: "bg-success",
  ai: "bg-info",
};

export interface ChampionSectionNavProps {
  jobId: number;
}

export function ChampionSectionNav({ jobId }: ChampionSectionNavProps) {
  const { data, isError } = useQuery({
    queryKey: ["champion-profile", jobId],
    queryFn: () => championApi.get(jobId).then((r) => r.data),
  });

  const profile: ChampionProfile | null = data
    ? {
        ...EMPTY_CHAMPION_PROFILE,
        ...(data.champion_profile as Partial<ChampionProfile>),
      }
    : null;

  return (
    <nav
      aria-label="Sekcje Profilu Championa"
      className="space-y-2 self-start rounded-xl border border-border bg-card p-3"
    >
      <h3 className="px-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        Sekcje
      </h3>
      <ul className="space-y-0.5">
        {CHAMPION_SECTIONS.map((section) => {
          const state = profile ? championSectionState(section.id, profile) : null;
          return (
            <li key={section.id}>
              <a
                href={`#${section.anchor}`}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-foreground transition-colors hover:bg-accent"
              >
                <span
                  aria-hidden="true"
                  title={state ? CHAMPION_SECTION_STATE_LABEL[state] : undefined}
                  className={cn(
                    "h-1.5 w-1.5 shrink-0 rounded-full",
                    state ? STATE_DOT_CLASS[state] : "bg-muted",
                  )}
                />
                <span className="min-w-0 flex-1 truncate">{section.label}</span>
              </a>
            </li>
          );
        })}
      </ul>
      {isError ? (
        <p className="px-1 text-[10px] text-muted-foreground">
          Nie udało się sprawdzić stanu sekcji.
        </p>
      ) : null}
    </nav>
  );
}
