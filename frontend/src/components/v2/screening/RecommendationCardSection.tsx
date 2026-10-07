"use client";

/**
 * Karta rekomendacji w doku osoby: zwarta karta + okno całej karty (0413).
 *
 * Od 0424 (07.10.2026) karta jest tu TYLKO DO ODCZYTU — pola karty wpisuje
 * się w jednym formularzu screeningu (`onEditInScreening` otwiera panel osoby
 * na zakładce „Screening”).
 */

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useRecommendationCard } from "@/lib/api/recommendationCards";

import { RecommendationCardDialog } from "./RecommendationCardDialog";
import { RecommendationCardView } from "./RecommendationCardView";

export interface RecommendationCardSectionProps {
  candidateId: number;
  jobId: number;
  candidateName: string;
  readOnly?: boolean;
  /** Okno całej karty otwarte z zewnątrz. */
  fullOpen?: boolean;
  onFullOpenChange?: (open: boolean) => void;
  /** „Edytuj w screeningu” — formularz screeningu tej osoby. */
  onEditInScreening?: () => void;
}

export function RecommendationCardSection({
  candidateId,
  jobId,
  candidateName,
  readOnly = false,
  fullOpen,
  onFullOpenChange,
  onEditInScreening,
}: RecommendationCardSectionProps) {
  const query = useRecommendationCard(candidateId, jobId);
  const [localOpen, setLocalOpen] = useState(false);
  const open = fullOpen ?? localOpen;
  const setOpen = onFullOpenChange ?? setLocalOpen;

  return (
    <>
      {query.isLoading ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" aria-hidden /> Wczytywanie karty…
        </p>
      ) : query.isError ? (
        <div className="space-y-2 text-xs">
          <p className="text-destructive">Nie udało się wczytać karty rekomendacji.</p>
          <Button size="sm" variant="outline" onClick={() => void query.refetch()}>
            Ponów
          </Button>
        </div>
      ) : query.data ? (
        <RecommendationCardView
          card={query.data}
          onOpenFull={() => setOpen(true)}
          onEditInScreening={readOnly ? undefined : onEditInScreening}
        />
      ) : null}
      <RecommendationCardDialog
        open={open}
        onOpenChange={setOpen}
        candidateId={candidateId}
        jobId={jobId}
        candidateName={candidateName}
        readOnly={readOnly}
        onEditInScreening={
          readOnly || !onEditInScreening
            ? undefined
            : () => {
                setOpen(false);
                onEditInScreening();
              }
        }
      />
    </>
  );
}
