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
import { seedChampionFromJob } from "@/lib/champion-job-seed";
import {
  CHAMPION_SECTIONS,
  CHAMPION_SECTION_STATE_LABEL,
  SEARCH_REQUIREMENTS_ANCHOR,
  championSectionState,
  type ChampionSectionState,
} from "@/lib/champion-section-state";
import { cn } from "@/lib/utils";


const STATE_DOT_CLASS: Record<ChampionSectionState, string> = {
  empty: "bg-muted-foreground/40",
  filled: "bg-success",
};

export interface ChampionSectionNavProps {
  jobId: number;
  /**
   * `horizontal` — przyklejony pasek trybu „Edytuj” (29.09.2026): krótkie
   * nazwy w KOLEJNOŚCI WYŚWIETLANIA sekcji. Numery 1, 3, 4, 2… zostały po
   * wzorze Worda i w pasku tylko myliły. Dochodzi „Wyszukiwanie w bazie”
   * (wymagania do wyszukiwania), którego pionowy spis nie znał.
   */
  orientation?: "vertical" | "horizontal";
}

/** Pasek edycji: kolejność = kolejność kart w `ChampionProfileEditor`. */
const HORIZONTAL_ITEMS: ReadonlyArray<{
  key: string;
  anchor: string;
  label: string;
  sectionId: (typeof CHAMPION_SECTIONS)[number]["id"] | null;
}> = [
  { key: "basics", anchor: "champion-section-basics", label: "Podstawy", sectionId: "basics" },
  { key: "stack", anchor: "champion-section-stack", label: "Stack", sectionId: "stack" },
  { key: "experience", anchor: "champion-section-experience", label: "Poza stackiem", sectionId: "experience" },
  { key: "requirements", anchor: SEARCH_REQUIREMENTS_ANCHOR, label: "Wyszukiwanie w bazie", sectionId: null },
  { key: "search", anchor: "champion-section-search", label: "Frazy i firmy", sectionId: "search" },
  { key: "project", anchor: "champion-section-project", label: "Projekt", sectionId: "project" },
  { key: "screening", anchor: "champion-section-screening", label: "Screening", sectionId: "screening_questions" },
  { key: "client", anchor: "champion-section-client", label: "Klient", sectionId: "client" },
  { key: "insights", anchor: "champion-section-insights", label: "Wiedza z rozmów", sectionId: "insights" },
];

export function ChampionSectionNav({ jobId, orientation = "vertical" }: ChampionSectionNavProps) {
  const { data, isError } = useQuery({
    queryKey: ["champion-profile", jobId],
    queryFn: () => championApi.get(jobId).then((r) => r.data),
  });

  // Ten sam profil, na który patrzy edytor obok: na profilu sprzed 09.2026
  // stack żyje w kolumnach rekrutacji (`job_values`), a sekcja 1 (od PR 5)
  // wczytuje stamtąd puste pola — edytor robi to samo (`seedChampionFromJob`).
  // Liczenie stanu z samego `champion_profile` dawało szarą kropkę „puste"
  // przy sekcji, która 300 px dalej pokazywała „wypełnione" i listę
  // technologii (audyt B48) — ta sama pułapka groziłaby sekcji „Podstawowe
  // informacje", gdyby nawigacja i edytor liczyły seed dwiema kopiami.
  const profile: ChampionProfile | null = data
    ? seedChampionFromJob(
        {
          ...EMPTY_CHAMPION_PROFILE,
          ...(data.champion_profile as Partial<ChampionProfile>),
        },
        data.job_values,
        data.job_title,
      ).profile
    : null;

  if (orientation === "horizontal") {
    return (
      <nav
        aria-label="Sekcje Profilu Championa"
        data-help="job.champion.sections"
        className="relative flex min-w-0 items-center gap-0.5 overflow-x-auto"
      >
        {HORIZONTAL_ITEMS.map((item) => {
          const state: ChampionSectionState | null = !profile
            ? null
            : item.sectionId
              ? championSectionState(item.sectionId, profile)
              : (profile.search?.requirements ?? []).some((row) => row.some((w) => w.trim()))
                ? "filled"
                : "empty";
          return (
            <a
              key={item.key}
              href={`#${item.anchor}`}
              className="inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 text-[13px] text-foreground transition-colors hover:bg-accent"
            >
              <span
                aria-hidden="true"
                className={cn(
                  "h-1.5 w-1.5 shrink-0 rounded-full",
                  state ? STATE_DOT_CLASS[state] : "bg-muted",
                )}
              />
              {item.label}
              {state ? (
                <span className="sr-only">, {CHAMPION_SECTION_STATE_LABEL[state]}</span>
              ) : null}
            </a>
          );
        })}
      </nav>
    );
  }

  return (
    <nav
      aria-label="Sekcje Profilu Championa"
      data-help="job.champion.sections"
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
                {/* Stan przekazany nie tylko kolorem — czytnik ekranu i daltonizm.
                    PO etykiecie, żeby dostępna nazwa linku zaczynała się od niej. */}
                {state ? (
                  <span className="sr-only">, {CHAMPION_SECTION_STATE_LABEL[state]}</span>
                ) : null}
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
