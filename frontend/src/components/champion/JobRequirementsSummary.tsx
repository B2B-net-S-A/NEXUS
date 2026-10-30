"use client";

/**
 * Wymagania rekrutacji — zakładka „Wymagania” podglądu w panelu osoby
 * (0424, 07.10.2026; lista ze zdaniem „po ludzku” od 09.10.2026, D5).
 *
 * Te same dane co „Czego szukamy” i „Warunki” w Briefie Championa
 * (`ChampionBriefView`): profil spod klucza edytora
 * (`["champion-profile", jobId]`), budżet „od–do” z rekrutacji w cache strony
 * (`["job", id]`, bez własnego zapytania). Tylko odczyt — rekruter ma je przed
 * oczami w trakcie rozmowy.
 *
 * Każde wymaganie to wiersz: nazwa, pod nią jedno zdanie ze słowniczka
 * (`usePlainBrief().glossary`, tylko gotowe hasła) i „Szukaj w CV”. Wymaganie
 * bez gotowego hasła pokazuje samą nazwę. W szerokiej strefie warunki
 * rekrutacji stoją obok listy, w wąskiej — pod nią. Liczenie wymagań
 * i warunków jest wspólne z paskiem nad CV (`use-job-requirements.ts`).
 */

import type { ReactNode } from "react";
import { Search, Star } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { usePlainBrief, type GlossaryTerm } from "@/lib/api/plainKnowledge";
import { buildGlossaryLookup, glossaryKey } from "@/lib/plain-glossary-lookup";

import { ExperienceChips } from "./ChampionBriefForRecruiters";
import { requirementFindWords, useJobRequirements } from "./use-job-requirements";

function Eyebrow({ children }: { children: string }) {
  return <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</p>;
}

function RequirementRow({
  name,
  fullLabel,
  term,
  critical,
  onPick,
}: {
  name: string;
  fullLabel: string;
  term: GlossaryTerm | undefined;
  critical: boolean;
  onPick?: (name: string) => void;
}) {
  return (
    <li
      className="flex items-start gap-3 rounded-lg border border-border bg-card px-3 py-2.5"
      data-critical={critical || undefined}
      data-glossary={term?.term_key}
    >
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-1.5 text-[15px] font-semibold leading-snug text-foreground">
          {critical ? <Star className="h-3.5 w-3.5 shrink-0 fill-primary text-primary" aria-hidden /> : null}
          <span className="min-w-0 break-words">{fullLabel}</span>
          {critical ? <span className="sr-only"> — krytyczna</span> : null}
        </p>
        {term ? <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{term.summary}</p> : null}
      </div>
      {onPick ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="shrink-0"
          aria-label={`Szukaj „${fullLabel}” w CV`}
          onClick={() => onPick(name)}
        >
          <Search className="h-3.5 w-3.5" aria-hidden /> Szukaj w CV
        </Button>
      ) : null}
    </li>
  );
}

function RequirementGroup({
  title,
  hint,
  items,
  critical,
  glossary,
  fullLabels,
  onPick,
}: {
  title: string;
  hint?: string | null;
  items: string[];
  critical: boolean;
  glossary: Map<string, GlossaryTerm>;
  fullLabels: Readonly<Record<string, string>>;
  onPick?: (name: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Eyebrow>{title}</Eyebrow>
      {items.length > 0 ? (
        <ul className="space-y-1.5">
          {items.map((name) => (
            <RequirementRow
              key={name}
              name={name}
              fullLabel={fullLabels[name] ?? name}
              term={glossary.get(glossaryKey(name))}
              critical={critical}
              onPick={onPick}
            />
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted-foreground">— brak</p>
      )}
      {hint ? <p className="text-[12px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function Condition({ label, value, muted = false }: { label: string; value: ReactNode; muted?: boolean }) {
  return (
    <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-2 py-1.5">
      <dt className="text-[13px] text-muted-foreground">{label}</dt>
      <dd className={muted ? "text-sm text-muted-foreground" : "text-sm font-medium text-foreground"}>{value}</dd>
    </div>
  );
}

function ConditionOrMissing({ label, value }: { label: string; value: string | null }) {
  return <Condition label={label} value={value ?? "nie podano"} muted={!value} />;
}

export interface JobRequirementsSummaryProps {
  jobId: number;
  /** Budżet PLN/h z Tablicy — gdy rekrutacji nie ma w cache strony. */
  budgetHourly?: number | null;
  /** „Szukaj w CV”: nazwa wymagania i słowa lupy z serwera (pusta lista = sama nazwa). */
  onPickRequirement?: (name: string, words: readonly string[]) => void;
}

export function JobRequirementsSummary({ jobId, budgetHourly = null, onPickRequirement }: JobRequirementsSummaryProps) {
  const { state, refetch, requirements } = useJobRequirements(jobId, budgetHourly);
  const plainQuery = usePlainBrief(jobId);
  const glossary = buildGlossaryLookup(plainQuery.data?.glossary);
  const pick = onPickRequirement
    ? (name: string) => onPickRequirement(name, requirementFindWords(requirements.findWords, name))
    : undefined;

  if (state === "loading") {
    return (
      <div className="space-y-2" aria-busy="true">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-32 w-full rounded-xl" />
      </div>
    );
  }
  if (state !== "ready" && state !== "empty") {
    return <QueryStateNotice state={state} onRetry={refetch} />;
  }

  const { mustCritical, mustOther, nice, critical, criticalLine, experience, notes, conditions, fullLabels } = requirements;

  return (
    <div className="@container" data-testid="job-requirements-summary">
      <div className="grid gap-5 @2xl:grid-cols-[minmax(0,1fr)_17rem]">
        <section aria-label="Czego szukamy" className="space-y-4">
          {mustCritical.length > 0 ? (
            <RequirementGroup
              title="Krytyczne"
              // Wybór Delivery Leada widać na liście; zdanie zostaje tylko dla
              // podpowiedzi z historii („Nie zdecydowano…”).
              hint={critical?.decided ? null : criticalLine}
              items={mustCritical}
              critical
              glossary={glossary}
              fullLabels={fullLabels}
              onPick={pick}
            />
          ) : null}
          {/* Gdy wszystkie „musi mieć” są krytyczne, pusta grupa „— brak”
              mówiłaby coś odwrotnego. */}
          {mustOther.length > 0 || mustCritical.length === 0 ? (
            <RequirementGroup
              title="Musi mieć"
              hint={mustCritical.length === 0 ? criticalLine : null}
              items={mustOther}
              critical={false}
              glossary={glossary}
              fullLabels={fullLabels}
              onPick={pick}
            />
          ) : null}
          <RequirementGroup
            title="Mile widziane"
            items={nice}
            critical={false}
            glossary={glossary}
            fullLabels={fullLabels}
            onPick={pick}
          />
          <ExperienceChips experience={experience} />
          {notes ? <p className="text-sm text-muted-foreground">Niuanse: {notes}</p> : null}
        </section>
        <section aria-label="Warunki rekrutacji" className="space-y-1.5">
          <Eyebrow>Warunki rekrutacji</Eyebrow>
          <dl className="divide-y divide-border/60 rounded-lg border border-border bg-card px-3">
            <ConditionOrMissing label="Budżet" value={conditions.budget} />
            <ConditionOrMissing label="Lokalizacja" value={conditions.location} />
            <ConditionOrMissing label="Tryb pracy" value={conditions.workMode} />
            <ConditionOrMissing label="Dni w biurze" value={conditions.office} />
            <ConditionOrMissing label="Start" value={conditions.start} />
            <ConditionOrMissing label="Długość" value={conditions.length} />
            <ConditionOrMissing label="Doświadczenie" value={conditions.seniority} />
            <ConditionOrMissing label="Język pracy" value={conditions.language} />
          </dl>
        </section>
      </div>
    </div>
  );
}
