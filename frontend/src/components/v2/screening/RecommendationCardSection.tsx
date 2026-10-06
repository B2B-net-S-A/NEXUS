"use client";

/**
 * Karta rekomendacji w doku osoby: zwarta karta + okno całej karty (0413).
 * Odczyt i zapis przez `/api/recommendation-cards`.
 */

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { useRecommendationCard, useSaveRecommendationCard } from "@/lib/api/recommendationCards";

import { RecommendationCardDialog } from "./RecommendationCardDialog";
import { RecommendationCardView } from "./RecommendationCardView";

export interface RecommendationCardSectionProps {
  candidateId: number;
  jobId: number;
  candidateName: string;
  readOnly?: boolean;
  /** Okno całej karty otwarte z zewnątrz (akcja „Uzupełnij kartę”). */
  fullOpen?: boolean;
  /** Arkusz screeningu ma niezapisane odpowiedzi (warsztat screeningu). */
  screeningDirty?: boolean;
  onFullOpenChange?: (open: boolean) => void;
}

export function RecommendationCardSection({
  candidateId,
  jobId,
  candidateName,
  readOnly = false,
  fullOpen,
  onFullOpenChange,
  screeningDirty = false,
}: RecommendationCardSectionProps) {
  const { showError } = useToast();
  const query = useRecommendationCard(candidateId, jobId);
  const save = useSaveRecommendationCard(candidateId, jobId);
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
          readOnly={readOnly}
          saving={save.isPending}
          onSave={(fields) =>
            save.mutate(
              { fields },
              {
                onError: (err) =>
                  showError(apiErrorMessage(err, "Nie udało się zapisać pola. Spróbuj ponownie.")),
              },
            )
          }
          onOpenFull={() => setOpen(true)}
        />
      ) : null}
      <RecommendationCardDialog
        open={open}
        onOpenChange={setOpen}
        candidateId={candidateId}
        jobId={jobId}
        candidateName={candidateName}
        readOnly={readOnly}
        screeningDirty={screeningDirty}
      />
    </>
  );
}
