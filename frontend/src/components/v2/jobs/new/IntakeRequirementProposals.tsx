"use client";

/**
 * Propozycje z odczytu maila nad wierszami wymagań (07.11.2026, makiety M1
 * i M2: https://claude.ai/artifact/U5xPzXiKJXixweYv5M8v7n).
 *
 * M1 — krytyczne z lat w mailu („minimum 5 lat z D365”) albo z tytułu. Nic
 * nie zapisuje się samo: decyzję podejmuje Delivery Lead jednym kliknięciem.
 * M2 — hasła słownika, które stoją w mailu, a nie ma ich w żadnym wierszu
 * (789198: DL dopisywał je ręcznie jedno po drugim).
 */

import { Button } from "@/components/ui/button";
import {
  missingTechnologies,
  proposalRowKeys,
  type CriticalProposal,
  type RequirementRowForm,
} from "@/lib/requirement-rows";

export interface IntakeRequirementProposalsProps {
  rows: readonly RequirementRowForm[];
  noCritical: boolean;
  criticalProposal: readonly CriticalProposal[];
  mailTechnologies: readonly string[];
  onApproveCritical: () => void;
  onNoCritical: () => void;
  onDismissCritical: () => void;
  onAddTechnologies: (names: string[]) => void;
  onDismissTechnologies: () => void;
}

export function IntakeRequirementProposals({
  rows,
  noCritical,
  criticalProposal,
  mailTechnologies,
  onApproveCritical,
  onNoCritical,
  onDismissCritical,
  onAddTechnologies,
  onDismissTechnologies,
}: IntakeRequirementProposalsProps) {
  const hasCritical = rows.some((row) => row.level === "critical" && row.words.length > 0);
  const matched = proposalRowKeys(rows, criticalProposal);
  const proposed = criticalProposal.filter((item) =>
    rows.some(
      (row) =>
        matched.includes(row.key) &&
        row.words[0]?.trim().toLocaleLowerCase("pl") === item.label.trim().toLocaleLowerCase("pl"),
    ),
  );
  const showCritical = !hasCritical && !noCritical && proposed.length > 0;
  const missing = missingTechnologies(rows, mailTechnologies);
  if (!showCritical && missing.length === 0) return null;
  return (
    <div
      className="flex flex-col gap-2"
      data-testid="intake-requirement-proposals"
      data-tour="requirements.intake-proposals"
    >
      {showCritical ? (
        <div
          role="note"
          className="flex flex-col gap-1.5 rounded-md border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-foreground"
          data-testid="intake-critical-proposal"
        >
          <span className="font-medium">
            Propozycja AI: krytyczne {proposed.map((item) => `„${item.label}”`).join(", ")}.
          </span>
          <ul className="flex flex-col gap-0.5 text-muted-foreground">
            {proposed.map((item) => (
              <li key={item.label}>
                {item.label}: {item.reason.startsWith("technologia") ? item.reason : `klient pisze „${item.reason}”`}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2 pt-0.5">
            <Button type="button" size="sm" onClick={onApproveCritical}>
              Zatwierdź krytyczne
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={onNoCritical}>
              Brak krytycznych
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={onDismissCritical}>
              Wybiorę sam
            </Button>
          </div>
        </div>
      ) : null}
      {missing.length > 0 ? (
        <div
          role="note"
          className="flex flex-col gap-1.5 rounded-md border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-foreground"
          data-testid="intake-mail-technologies"
        >
          <span>
            <span className="font-medium">W mailu są też:</span> kliknij, żeby dodać jako „mile
            widziane”.
          </span>
          <div className="flex flex-wrap gap-1.5">
            {missing.map((name) => (
              <Button
                key={name}
                type="button"
                size="sm"
                variant="outline"
                onClick={() => onAddTechnologies([name])}
              >
                + {name}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            {missing.length > 1 ? (
              <Button type="button" size="sm" onClick={() => onAddTechnologies(missing)}>
                Dodaj wszystkie ({missing.length})
              </Button>
            ) : null}
            <Button type="button" size="sm" variant="ghost" onClick={onDismissTechnologies}>
              Zostaw
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
