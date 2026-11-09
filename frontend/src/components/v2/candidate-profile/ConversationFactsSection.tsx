"use client";

/**
 * Blok „Z rozmów” na Przeglądzie profilu (08.11.2026, wariant A): co rejestr
 * wie o osobie, skąd i z jakiego dnia. Fakty zapisują się same, więc nie ma
 * tu przycisku potwierdzania. Przy wyłączonej fladze blok nie istnieje.
 */

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { SectionError, SectionHeading } from "@/components/v2/candidate-profile/profile-shared";
import { formatWarsawDay } from "@/lib/added-to-base";
import { candidateFactsApi, type ConversationFact } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { factKindLabel, factSourceLabel } from "@/lib/conversation-facts";

const COLLAPSED = 6;

function FactRow({ fact }: { fact: ConversationFact }) {
  const day = formatWarsawDay(fact.noted_at);
  const origin = [fact.author_name, day, fact.job_title].filter(Boolean).join(" · ");
  return (
    <li className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-1.5 text-sm">
      <span className="min-w-0 [overflow-wrap:anywhere]">
        <span className="font-medium text-foreground">{fact.value}</span>{" "}
        <span className="text-xs text-muted-foreground">
          {factKindLabel(fact)}
          {fact.job_only ? " · tylko ta rekrutacja" : ""}
        </span>
        {fact.evidence ? (
          <span className="block text-xs text-muted-foreground">{fact.evidence}</span>
        ) : null}
      </span>
      <span className="flex min-w-0 flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
        {fact.status === "absent" ? (
          <Badge variant="warning" size="sm">
            Nie ma
          </Badge>
        ) : (
          <Badge variant={fact.source === "sheet" ? "success" : "soft"} size="sm">
            {factSourceLabel(fact)}
          </Badge>
        )}
        {origin ? <span className="[overflow-wrap:anywhere]">{origin}</span> : null}
      </span>
    </li>
  );
}

export function ConversationFactsSection({ candidateId }: { candidateId: number }) {
  const [expanded, setExpanded] = useState(false);
  const query = useQuery({
    queryKey: ["candidate-conversation-facts", candidateId],
    queryFn: () => candidateFactsApi.getConversationFacts(candidateId),
    staleTime: 60_000,
  });
  if (query.isError) {
    return (
      <section aria-labelledby="conversation-facts-heading">
        <SectionHeading id="conversation-facts-heading">Z rozmów</SectionHeading>
        <SectionError
          title={apiErrorMessage(query.error, "Nie udało się wczytać faktów z rozmów.")}
          onRetry={query.refetch}
        />
      </section>
    );
  }
  const facts = query.data?.enabled ? query.data.facts : [];
  if (!query.isSuccess || facts.length === 0) return null;
  const visible = expanded ? facts : facts.slice(0, COLLAPSED);
  return (
    <section aria-labelledby="conversation-facts-heading" data-testid="conversation-facts">
      <SectionHeading id="conversation-facts-heading">Z rozmów</SectionHeading>
      <ul className="divide-y divide-border rounded-lg border border-border bg-card px-3">
        {visible.map((fact) => (
          <FactRow key={fact.id} fact={fact} />
        ))}
      </ul>
      {facts.length > COLLAPSED ? (
        <button
          type="button"
          className="mt-1 text-xs font-medium text-primary hover:underline"
          onClick={() => setExpanded((open) => !open)}
        >
          {expanded ? "Pokaż mniej" : `Pokaż wszystkie (${facts.length})`}
        </button>
      ) : null}
    </section>
  );
}
