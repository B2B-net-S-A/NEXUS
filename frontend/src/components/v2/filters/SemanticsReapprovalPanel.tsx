"use client";

import { Button } from "@/components/ui/button";
import { semanticsReapproval } from "@/lib/saved-search-reapproval";

export type SemanticsReapprovalChoice = "accept" | "keep_legacy";

interface SemanticsReapprovalPanelProps {
  name: string;
  /** `filters` zapisu — panel renderuje się tylko, gdy niosą `migration`. */
  filters: unknown;
  /** Decyzję podejmuje właściciel zapisu; pozostali widzą sam opis. */
  canDecide: boolean;
  pending?: boolean;
  error?: string | null;
  onChoose: (choice: SemanticsReapprovalChoice) => void;
  className?: string;
}

/**
 * „Zmieniły się zasady wyszukiwania" — zapis wstrzymany przez migrację na
 * wspólną semantykę filtrów (backend: `saved_search_migration.py`). JEDEN panel
 * dla listy kandydatów (`SavedSearchesMenu`) i wyszukiwarki
 * (`CandidateSearchView`): te same zdania, liczby przed/po, przyczyny i dwa
 * przyciski. To INNY przypadek niż wycofanie miesięcznych kryteriów stawki —
 * tamten zapis nie ma `filters.migration` i zostaje przy własnym komunikacie.
 */
export function SemanticsReapprovalPanel({
  name,
  filters,
  canDecide,
  pending = false,
  error = null,
  onChoose,
  className,
}: SemanticsReapprovalPanelProps) {
  const review = semanticsReapproval(filters);
  if (!review) return null;
  const counted = review.legacyTotal !== null && review.unifiedTotal !== null;
  return (
    <div
      role="group"
      aria-label={`Zmiana zasad wyszukiwania: ${name}`}
      className={`rounded-md border border-border bg-muted/40 p-2.5 text-xs ${className ?? ""}`}
    >
      <p className="font-semibold text-foreground">
        Zmieniły się zasady wyszukiwania
      </p>
      <p className="mt-1 text-muted-foreground">
        Ujednoliciliśmy filtry listy i wyszukiwarki kandydatów. Wyniki tego
        zapisu by się zmieniły
        {counted
          ? `: dotąd ${review.legacyTotal}, po zmianie ${review.unifiedTotal}.`
          : "."}
      </p>
      <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-muted-foreground">
        {review.ruleLabels.map((label) => (
          <li key={label}>{label}</li>
        ))}
      </ul>
      {review.alertWasOn && (
        <p className="mt-1.5 text-muted-foreground">
          Alert jest wstrzymany do Twojej decyzji.
        </p>
      )}
      {canDecide ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Button
            type="button"
            size="sm"
            disabled={pending}
            onClick={() => onChoose("accept")}
          >
            Zatwierdź nowe wyniki
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={pending}
            onClick={() => onChoose("keep_legacy")}
          >
            Zostaw po staremu
          </Button>
        </div>
      ) : (
        <p className="mt-1.5 text-muted-foreground">
          Decyzję podejmuje właściciel zapisu.
        </p>
      )}
      {error && (
        <p role="alert" className="mt-1.5 text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
