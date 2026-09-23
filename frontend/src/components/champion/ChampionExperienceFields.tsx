"use client";

/**
 * Pola sekcji 4 „Doświadczenie poza stackiem” — dziedzina, certyfikaty,
 * regulacje. Wspólne dla edytora Championa i strony `/jobs/new`, żeby oba
 * miejsca zapisywały ten sam kształt (`ChampionExperience`).
 */

import type { ChampionExperience, ExperienceKind } from "@/lib/api";
import {
  EXPERIENCE_KIND_HINT,
  EXPERIENCE_KIND_LABEL,
  EXPERIENCE_KINDS,
  EXPERIENCE_SUGGESTIONS,
} from "@/lib/champion-experience";
import { RequirementChipInput } from "@/components/ds/RequirementChipInput";

export interface ChampionExperienceFieldsProps {
  value: ChampionExperience;
  onChange: (next: ChampionExperience) => void;
  disabled?: boolean;
  /** Pole „Niuanse” — edytor tak, `/jobs/new` bez (tam liczy się tempo). */
  showNotes?: boolean;
  notesClassName?: string;
}

export function ChampionExperienceFields({
  value,
  onChange,
  disabled = false,
  showNotes = true,
  notesClassName,
}: ChampionExperienceFieldsProps) {
  const patch = (kind: ExperienceKind, items: ChampionExperience[ExperienceKind]) =>
    onChange({ ...value, [kind]: items });

  return (
    <div className="flex flex-col gap-3">
      {EXPERIENCE_KINDS.map((kind) => (
        <RequirementChipInput
          key={kind}
          label={EXPERIENCE_KIND_LABEL[kind]}
          hint={EXPERIENCE_KIND_HINT[kind]}
          items={value[kind] ?? []}
          onChange={(items) => patch(kind, items)}
          withYears={kind === "domains"}
          suggestions={EXPERIENCE_SUGGESTIONS[kind]}
          disabled={disabled}
          testId={`champion-experience-${kind}`}
        />
      ))}
      {showNotes ? (
        <label className="block" data-champion-field="experience.notes">
          <span className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground">
            Niuanse
          </span>
          <input
            type="text"
            disabled={disabled}
            value={value.notes ?? ""}
            onChange={(e) => onChange({ ...value, notes: e.target.value })}
            placeholder="np. karty debetowe, nie kredytowe; wystarczy acquiring albo issuing"
            className={notesClassName}
          />
        </label>
      ) : null}
    </div>
  );
}
