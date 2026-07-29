"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ExpandableText } from "@/components/v2/ExpandableText";
import {
  activitySummaryApi,
  extractErrorMsg,
  type CandidateActivitySummary,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { cn, formatDate } from "@/lib/utils";
import { candidateQueryKeys } from "./candidate-query-keys";

interface CandidateActivitySummaryCardProps {
  candidateId: number;
}

/**
 * "Podsumowanie aktywności" — krótka notatka AI kondensująca historię
 * kandydata (wysyłki na projekty, feedbacki po interview, preferencje,
 * stawki, dostępność). GET nigdy nie generuje (profil otwiera się za darmo);
 * przycisk „Aktualizuj notatkę" zbiera historię ponownie i płaci za nowe
 * wywołanie AI tylko gdy coś się zmieniło.
 */
export function CandidateActivitySummaryCard({
  candidateId,
}: CandidateActivitySummaryCardProps) {
  const { showError, showSuccess } = useToast();
  const queryClient = useQueryClient();
  const queryKey = candidateQueryKeys.activitySummary(candidateId);

  const query = useQuery<CandidateActivitySummary>({
    queryKey,
    queryFn: () => activitySummaryApi.get(candidateId).then((r) => r.data),
    retry: false,
    staleTime: 5 * 60_000,
  });

  const refreshMut = useMutation({
    mutationFn: () =>
      activitySummaryApi.refresh(candidateId).then((r) => r.data),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKey, data);
      showSuccess(
        data.refreshed === false
          ? "Podsumowanie jest aktualne — brak nowych danych"
          : "Podsumowanie zaktualizowane",
      );
    },
    onError: (e) =>
      showError(extractErrorMsg(e) || "Nie udało się zaktualizować podsumowania"),
  });

  const data = query.data;
  const hasSummary = Boolean(data?.summary);

  return (
    <Card variant="default" size="md" className="py-4!">
      <div className="flex items-start gap-2">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-primary">
              Podsumowanie aktywności
            </h3>
            {hasSummary ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => refreshMut.mutate()}
                disabled={refreshMut.isPending}
              >
                <RefreshCw
                  className={cn("h-3.5 w-3.5", refreshMut.isPending && "animate-spin")}
                />
                Aktualizuj notatkę
              </Button>
            ) : null}
          </div>

          {query.isPending ? (
            <div className="flex items-center gap-2 py-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Ładowanie podsumowania…
            </div>
          ) : query.isError ? (
            <div className="space-y-2 py-1">
              <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
                Podsumowanie aktywności jest niedostępne
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => query.refetch()}
                disabled={query.isFetching}
              >
                <RefreshCw
                  className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")}
                />
                Spróbuj ponownie
              </Button>
            </div>
          ) : hasSummary ? (
            <>
              <ExpandableText text={data!.summary!} maxLines={6} />
              <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                <span>
                  Wygenerowane przez AI{data!.model ? ` (${data!.model})` : ""} —
                  zweryfikuj przed decyzją.
                </span>
                {data!.generated_at ? (
                  <span>Zaktualizowano {formatDate(data!.generated_at)}</span>
                ) : null}
              </p>
            </>
          ) : (
            <div className="space-y-2 py-1">
              <p className="text-sm text-muted-foreground">
                AI streści historię kandydata: wysyłki na projekty, feedbacki po
                interview, preferencje, stawki i dostępność.
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => refreshMut.mutate()}
                disabled={refreshMut.isPending}
              >
                {refreshMut.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5" />
                )}
                {refreshMut.isPending
                  ? "Generuję podsumowanie…"
                  : "Wygeneruj podsumowanie"}
              </Button>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

export default CandidateActivitySummaryCard;
