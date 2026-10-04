"use client";

/**
 * „Profil Championa” → zakładka „Klient i historia” (04.10.2026).
 *
 * Wszystko o kliencie w jednym miejscu: opis (karta klienta albo internet),
 * branże i karta klienta, pytania klienta z wcześniejszych rozmów, wiedza
 * z rozmów i wcześniejsze zapytania tego klienta. Do 04.10.2026 te bloki stały
 * na końcu długiej strony „Podgląd”, a opis klienta był drugi raz w „Po ludzku”.
 */

import { ChampionInsightsDigest, useChampionProfile } from "@/components/champion/ChampionBriefForRecruiters";
import { AskClientList, BriefSection } from "@/components/champion/ChampionBriefView";
import { PlainBriefBlock } from "@/components/champion/plain/PlainBriefBlock";
import { ChampionClientQuestionsPanel } from "@/components/ChampionClientQuestionsPanel";
import { RequestHistorySection } from "@/components/RequestHistorySection";
import { ClientPlaybookCard } from "@/components/client-playbook/ClientPlaybookCard";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Skeleton } from "@/components/ui/skeleton";
import { EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import type { ChampionBlock } from "@/lib/champion-blocks";
import { clientPlaybookEditHref } from "@/lib/client-playbooks";
import { resolveViewState } from "@/lib/view-state";

export interface ChampionClientTabProps {
  jobId: number;
  clientId: number | null;
  /** Brak = rola nie edytuje Championa. */
  onEditBlock?: (block: ChampionBlock) => void;
  /** Wcześniejsze zapytania: `readOnly` = bez „Skopiuj jako template”. */
  requestHistoryReadOnly: boolean;
}

export function ChampionClientTab({
  jobId,
  clientId,
  onEditBlock,
  requestHistoryReadOnly,
}: ChampionClientTabProps) {
  const query = useChampionProfile(jobId);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (state === "loading") {
    return <Skeleton className="h-40 w-full rounded-xl" />;
  }
  if (state !== "ready" && state !== "empty") {
    return <QueryStateNotice state={state} onRetry={() => void query.refetch()} />;
  }
  const profile: Partial<ChampionProfile> = {
    ...EMPTY_CHAMPION_PROFILE,
    ...((query.data?.champion_profile ?? {}) as Partial<ChampionProfile>),
  };
  const questions = profile.screening_questions ?? [];
  const sectors = profile.client?.sectors ?? [];
  const edit = (block: ChampionBlock) => (onEditBlock ? () => onEditBlock(block) : undefined);

  return (
    <div
      className="grid grid-cols-1 gap-3.5 xl:grid-cols-[minmax(0,1fr)_380px]"
      data-testid="champion-client-tab"
    >
      <div className="min-w-0 space-y-3.5">
        <PlainBriefBlock jobId={jobId} parts="client" />
        <BriefSection title="Karta klienta" onEdit={edit("client")} testId="client-tab-playbook">
          {sectors.length > 0 ? (
            <p className="text-[13px] text-muted-foreground">Branże klienta: {sectors.join(", ")}</p>
          ) : null}
          {clientId != null ? (
            <ClientPlaybookCard
              clientId={clientId}
              variant="compact"
              editHref={clientPlaybookEditHref(clientId)}
            />
          ) : (
            <p className="text-[13px] text-muted-foreground">Rekrutacja nie ma klienta.</p>
          )}
        </BriefSection>
        <BriefSection title="Pytania klienta z wcześniejszych rozmów" testId="client-tab-questions">
          <ChampionClientQuestionsPanel
            jobId={jobId}
            screeningQuestions={questions.map((q) => q.question)}
            historicalQuestions={profile.client?.historical_questions ?? ""}
            canEdit={false}
            onAddScreening={() => undefined}
            onAddHistorical={() => undefined}
          />
        </BriefSection>
        <BriefSection title="Wiedza z rozmów" onEdit={edit("insights")} testId="client-tab-insights">
          <AskClientList profile={profile} />
          <ChampionInsightsDigest profile={profile} limit={8} historyLimit={5} />
        </BriefSection>
      </div>
      <aside className="min-w-0" aria-label="Wcześniejsze zapytania klienta">
        <BriefSection title="Wcześniejsze zapytania klienta" testId="client-tab-history">
          <RequestHistorySection
            jobId={jobId}
            clientId={clientId}
            readOnly={requestHistoryReadOnly}
            compact
            narrow
            maxItems={5}
          />
        </BriefSection>
      </aside>
    </div>
  );
}
