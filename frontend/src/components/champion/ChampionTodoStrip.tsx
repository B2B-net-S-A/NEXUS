"use client";

/**
 * Pasek „Do dopięcia” nad Briefem Profilu Championa (04.10.2026).
 *
 * Zastępuje zakładkę „Gotowość” panelu bocznego, który stał obok Podglądu do
 * 04.10.2026. Treść ta sama, tylko pokazana wtedy, gdy JEST co dopiąć:
 *  - braki bramki „Przekaż do searchu” (`MissingBlock`) — tylko rekrutacja
 *    jeszcze nieprzekazana (od 04.10 każda nowa rekrutacja jest przekazana
 *    przy utworzeniu, więc to zostaje dla starych szkiców i opublikowanych
 *    bez przekazania),
 *  - przycisk przekazania — tylko gdy rekrutacja nie jest przekazana; panel
 *    pokazywał go także po przekazaniu, obok zdania „przekazane do searchu”,
 *  - trzy wiersze weryfikacji (rozmowa z klientem, z konsultantem, briefing).
 *
 * Widzi go konto z uprawnieniem do prowadzenia rekrutacji (bramka gotowości
 * odpowiada innym 403). Wiersze „Stack”, „Budżet”, „Rekruter” i „Hiring
 * manager” z dawnego panelu nie wracają: te fakty stoją w Briefie obok.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";

import api, { type ChampionBriefing, type ChampionVerification } from "@/lib/api";
import { countPl } from "@/lib/plural-pl";
import { priorityLevelOf, type PrioritySource } from "@/lib/request-priority";
import { useChampionProfile } from "@/components/champion/ChampionBriefForRecruiters";
import {
  ChampionVerificationChecklist,
  championVerificationDone,
} from "@/components/ChampionVerificationChecklist";
import { JobHandoffButton } from "@/components/v2/jobs/JobHandoffButton";
import { MissingBlock } from "@/components/v2/recruitment/OrderMissingBlock";

interface Readiness {
  ready: boolean;
  blockers: string[];
  closed: boolean;
  already_handed_off: boolean;
}

export interface ChampionTodoJob extends PrioritySource {
  status?: string | null;
  primary_owner?: { id: number; name?: string | null } | null;
  [key: string]: unknown;
}

export interface ChampionTodoStripProps {
  jobId: number;
  job: ChampionTodoJob;
  /** Uprawnienie „Rekrutacje: zakładanie, zamykanie…” + odczyt Pipeline. */
  canSeeGate: boolean;
  canWritePipeline: boolean;
  canEditChampion: boolean;
  canEditJob: boolean;
  /** Brak bramki z akcją w Championie — szuflada bloku albo pełny formularz. */
  onGoChampion: (anchor: string | null) => void;
  onEditJob: () => void;
}

export function ChampionTodoStrip({
  jobId,
  job,
  canSeeGate,
  canWritePipeline,
  canEditChampion,
  canEditJob,
  onGoChampion,
  onEditJob,
}: ChampionTodoStripProps) {
  const [open, setOpen] = useState(false);
  const readinessQuery = useQuery({
    queryKey: ["job-readiness", jobId],
    queryFn: () => api.get(`/api/jobs/${jobId}/readiness`).then((r) => r.data as Readiness),
    enabled: canSeeGate,
    staleTime: 30_000,
    retry: false,
  });
  const championQuery = useChampionProfile(jobId);

  if (!canSeeGate || !readinessQuery.isSuccess || !championQuery.isSuccess) return null;

  const readiness = readinessQuery.data;
  if (readiness.closed) return null;
  const profile = championQuery.data?.champion_profile as
    | { verification?: ChampionVerification; briefing?: ChampionBriefing }
    | undefined;
  const done = championVerificationDone(profile?.verification, profile?.briefing);
  const missingVerification = [done.client, done.consultant, done.briefing].filter((d) => !d)
    .length;
  const notHandedOff = !readiness.already_handed_off;
  const blockers = notHandedOff && Array.isArray(readiness.blockers) ? readiness.blockers : [];
  const showHandoff = notHandedOff && canWritePipeline;
  const total = missingVerification + blockers.length + (showHandoff ? 1 : 0);
  if (total === 0) return null;

  const labels = [
    blockers.length > 0 ? countPl(blockers.length, "brak w zleceniu", "braki w zleceniu", "braków w zleceniu") : null,
    showHandoff ? "przekazanie do searchu" : null,
    !done.client ? "rozmowa z klientem" : null,
    !done.consultant ? "rozmowa z naszym konsultantem" : null,
    !done.briefing ? "briefing" : null,
  ].filter(Boolean);
  // Braki i przekazanie są pilne — wtedy pasek otwiera się sam.
  const expanded = open || blockers.length > 0;

  return (
    <section
      className="rounded-xl border border-warning/30 bg-warning-muted/60"
      aria-label="Do dopięcia"
      data-testid="champion-todo-strip"
      data-help="job.champion.todo"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-left text-[13px]"
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-warning-muted-foreground" aria-hidden="true" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-warning-muted-foreground" aria-hidden="true" />
        )}
        <span className="font-semibold text-warning-muted-foreground">Do dopięcia · {total}</span>
        {/* Telefon: lista braków schodzi pod nagłówek zamiast ściskać się w kolumnę. */}
        <span className="w-full min-w-0 pl-7 text-foreground sm:w-auto sm:flex-1 sm:pl-0">
          {labels.join(" · ")}
        </span>
        {blockers.length === 0 && !showHandoff ? (
          <span className="hidden text-xs text-muted-foreground sm:inline">
            nie blokuje pracy rekruterów
          </span>
        ) : null}
      </button>
      {expanded ? (
        <div className="space-y-3 border-t border-warning/20 bg-card/70 px-4 py-3">
          {blockers.length > 0 ? (
            <MissingBlock
              jobId={jobId}
              job={job}
              canSeeGate={canSeeGate}
              canEditChampion={canEditChampion}
              canEditJob={canEditJob}
              onGoChampion={onGoChampion}
              onEditJob={onEditJob}
            />
          ) : null}
          {showHandoff ? (
            <JobHandoffButton
              jobId={jobId}
              priorityLevel={priorityLevelOf(job)}
              recruiter={job.primary_owner ?? null}
              jobStatus={job.status ?? null}
            />
          ) : null}
          {missingVerification > 0 ? (
            <div className="space-y-1.5">
              <ChampionVerificationChecklist
                jobId={jobId}
                verification={profile?.verification}
                briefing={profile?.briefing}
                canEdit={canEditChampion}
                variant="rows"
              />
              {!done.client || !done.consultant ? (
                <p className="text-[11px] text-muted-foreground">
                  Champion niezweryfikowany — rekruterzy widzą to na profilu kandydata jako
                  ostrzeżenie.
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
