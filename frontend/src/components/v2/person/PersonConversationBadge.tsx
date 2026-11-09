"use client";

/**
 * Plakietka „Z rozmów” w panelu osoby na Tablicy (08.11.2026): ile faktów
 * z rozmów zna rejestr, dymek wymienia je z pochodzeniem. Błąd zapytania nie
 * wygląda jak brak faktów, bo plakietki wtedy po prostu nie ma, a pełny stan
 * z komunikatem pokazuje blok w profilu.
 */

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { candidateFactsApi } from "@/lib/api";
import { factSourceLabel, factsSummary, factsSummaryText } from "@/lib/conversation-facts";

export function PersonConversationBadge({ candidateId }: { candidateId: number }) {
  const { data } = useQuery({
    queryKey: ["candidate-conversation-facts", candidateId],
    queryFn: () => candidateFactsApi.getConversationFacts(candidateId),
    staleTime: 60_000,
  });
  const facts = data?.enabled ? data.facts : [];
  const summary = factsSummary(facts);
  if (!summary) return null;
  const title = facts
    .map((fact) => `${fact.status === "absent" ? "Nie ma" : "✓"} ${fact.value} (${factSourceLabel(fact)})`)
    .join("\n");
  return (
    <p className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground" data-testid="person-conversation-badge">
      <Badge variant="success" size="sm" title={title}>
        Z rozmów
      </Badge>
      <span>{factsSummaryText(summary)}</span>
    </p>
  );
}
