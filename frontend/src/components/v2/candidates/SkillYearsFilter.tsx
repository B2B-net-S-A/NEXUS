"use client";

import { useState } from "react";
import { Plus, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { FieldLabel } from "@/components/v2/filters/FilterBarPill";
import { HideUnknownChoice } from "@/components/v2/candidates/UnknownFieldBadges";
import type { CandidateFilters } from "@/lib/url-filters";
import { cn } from "@/lib/utils";
import {
  SKILL_YEARS_MAX,
  SKILL_YEARS_MAX_ROWS,
  SKILL_YEARS_MIN,
  knownSkillYears,
  parseSkillYearsEntries,
  skillYearsEntries,
  yearsUnit,
  type CandidateSkillYears,
  type SkillYearsRow,
} from "@/lib/candidate-skill-years";

/**
 * Okienko pigułki „Lata z technologią” (08.11.2026, wariant B z makiet
 * https://claude.ai/artifact/CmAoKVLNtc9GAU8w8Yh5Yn): wiersze „technologia
 * · co najmniej N lat” i wybór dla osób z technologią bez dat w CV — ten sam
 * układ co „Osoby bez stawki” w okienku Stawki.
 *
 * Wiersze żyją w stanie okienka (montuje się przy otwarciu), więc
 * niedokończony wiersz nie znika w trakcie pisania; do filtrów idą tylko
 * wiersze z nazwą technologii.
 */

type SkillYearsPatch = Partial<Pick<CandidateFilters, "skillYears" | "hideUnknownSkillYears">>;

interface SkillYearsFilterFieldsProps {
  filters: Pick<CandidateFilters, "skillYears" | "hideUnknownSkillYears">;
  onPatch: (patch: SkillYearsPatch) => void;
  onSubmit?: () => void;
}

const EMPTY_ROW: SkillYearsRow = { skill: "", years: 3 };

export function SkillYearsFilterFields({ filters, onPatch, onSubmit }: SkillYearsFilterFieldsProps) {
  const [rows, setRows] = useState<SkillYearsRow[]>(() => {
    const parsed = parseSkillYearsEntries(filters.skillYears);
    return parsed.length ? parsed : [EMPTY_ROW];
  });

  const commit = (next: SkillYearsRow[]) => {
    setRows(next);
    onPatch({ skillYears: skillYearsEntries(next) });
  };
  const update = (index: number, patch: Partial<SkillYearsRow>) =>
    commit(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  const remove = (index: number) => {
    const next = rows.filter((_, i) => i !== index);
    commit(next.length ? next : [EMPTY_ROW]);
  };

  return (
    <div className="space-y-2" data-testid="skill-years-filter">
      <FieldLabel>Lata z technologią (z dat stanowisk w CV)</FieldLabel>
      <div className="space-y-1.5">
        {rows.map((row, index) => (
          <div key={index} className="flex items-center gap-1.5">
            <Input
              aria-label={`Technologia ${index + 1}`}
              placeholder="np. Java"
              value={row.skill}
              maxLength={120}
              onChange={(e) => update(index, { skill: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter" && onSubmit) {
                  e.preventDefault();
                  onSubmit();
                }
              }}
              className="h-8 min-w-0 flex-1 text-sm"
            />
            <span className="shrink-0 text-xs text-muted-foreground">co najmniej</span>
            <Input
              type="number"
              aria-label={`Lata z technologią ${index + 1}`}
              min={SKILL_YEARS_MIN}
              max={SKILL_YEARS_MAX}
              value={row.years}
              onChange={(e) => {
                const n = Number.parseInt(e.target.value, 10);
                if (Number.isFinite(n)) {
                  update(index, {
                    years: Math.min(SKILL_YEARS_MAX, Math.max(SKILL_YEARS_MIN, n)),
                  });
                }
              }}
              className="h-8 w-14 shrink-0 text-sm"
            />
            <span className="w-6 shrink-0 text-xs text-muted-foreground">{yearsUnit(row.years)}</span>
            <button
              type="button"
              aria-label={`Usuń wiersz ${index + 1}`}
              onClick={() => remove(index)}
              className="shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
        ))}
      </div>
      {rows.length < SKILL_YEARS_MAX_ROWS && (
        <button
          type="button"
          onClick={() => setRows([...rows, EMPTY_ROW])}
          className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          technologia
        </button>
      )}
      <p className="text-[11px] leading-snug text-muted-foreground">
        Suma okresów stanowisk i projektów, przy których CV wymienia technologię. Każdy wiersz musi
        być spełniony.
      </p>
      <HideUnknownChoice
        label="Osoby z technologią, ale bez dat w CV"
        hidden={filters.hideUnknownSkillYears}
        onChange={(hidden) => onPatch({ hideUnknownSkillYears: hidden })}
        className="border-t border-border pt-2"
      />
    </div>
  );
}

/**
 * Lata przy wierszu listy: „Java 6 lat 8 mies.” dla technologii z datami
 * w CV. Brak dat pokazuje plakietka „bez dat w CV” (`unknown_fields`).
 */
export function SkillYearsBadges({
  entries,
  className,
}: {
  entries: readonly CandidateSkillYears[] | null | undefined;
  className?: string;
}) {
  const known = knownSkillYears(entries);
  if (known.length === 0) return null;
  return (
    <span className={cn("inline-flex gap-1", className)}>
      {known.map((k) => (
        <span
          key={k.skill}
          title={`${k.skill}: ${k.text} — suma okresów stanowisk i projektów z tą technologią w CV`}
          data-testid="skill-years-badge"
          className="inline-flex items-center whitespace-nowrap rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary"
        >
          {k.skill} {k.text}
        </span>
      ))}
    </span>
  );
}
