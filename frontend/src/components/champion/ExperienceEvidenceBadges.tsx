"use client";

/**
 * Plakietki sekcji 4 Championa przy kandydacie: „płatności ✓” (jest ślad
 * w CV, tooltip mówi gdzie) albo „płatności ?” (brak danych — dopytaj).
 * Nigdy „nie ma”: branża w CV bywa pusta. Plakietka nie zmienia wyniku
 * dopasowania (decyzja 23.09.2026).
 */

import { EXPERIENCE_KIND_LABEL, type ExperienceEvidence } from "@/lib/champion-experience";
import { cn } from "@/lib/utils";

export function ExperienceEvidenceBadges({
  evidence,
}: {
  evidence: readonly ExperienceEvidence[];
}) {
  if (evidence.length === 0) return null;
  return (
    <span className="inline-flex flex-wrap gap-1" data-testid="experience-evidence">
      {evidence.map((item) => {
        const met = item.status === "met";
        const title = met
          ? `${EXPERIENCE_KIND_LABEL[item.kind]}: jest ślad (${item.source ?? "CV"})`
          : `${EXPERIENCE_KIND_LABEL[item.kind]}: brak danych w CV — dopytaj w screeningu`;
        return (
          <span
            key={`${item.kind}:${item.name}`}
            title={title}
            aria-label={title.replace(":", ` ${item.name}:`)}
            className={cn(
              "inline-flex items-center rounded-full px-1.5 py-0.5 text-[11px] font-medium",
              met
                ? "bg-success-muted text-success-muted-foreground"
                : "border border-dashed border-border text-muted-foreground",
            )}
          >
            {item.name} {met ? "✓" : "?"}
          </span>
        );
      })}
    </span>
  );
}
