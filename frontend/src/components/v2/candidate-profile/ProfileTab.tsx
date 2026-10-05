"use client";

/**
 * Zakładka „Przegląd” (domyślna, 04.10.2026). Odpowiada na dwa pytania:
 *
 * - „Teraz” — co się dzieje z tą osobą: zaległy telefon po ciszy klienta
 *   i procesy w toku (etap, kto ma ruch, od ilu dni, link do Tablicy),
 * - „Ostatnia rozmowa” — najnowsza notatka z rozmowy i liczba prób kontaktu.
 *
 * Fakty (dostępność, stawka, tryb, miasto, języki), „W skrócie” i ustalenia
 * z notatek stoją w karcie „Podsumowanie” w lewej kolumnie. CV i umiejętności
 * przeszły do „CV i dokumenty”, odpowiedzi ze screeningu mają własną
 * zakładkę — tu niczego nie powtarzamy.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, MessageSquare, PhoneCall } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CandidateFollowupDialog } from "@/components/v2/followups/CandidateFollowupDialog";
import { candidateStageLabel } from "@/components/v2/pages/candidate-timeline-labels";
import { useCandidateFollowup } from "@/lib/api/candidateFollowups";
import {
  followupDueLabel,
  followupTone,
  shortPersonName,
} from "@/lib/candidate-followup";
import {
  daysSince,
  latestTalkNote,
  nextActionOwnerLabel,
} from "@/lib/candidate-overview";
import { collapsedNotePreview, noteDateLabel } from "@/lib/candidate-notes-view";
import { pluralPl } from "@/lib/plural-pl";
import { recruitmentStageLabel } from "@/lib/recruitment-stage-label";
import { cn, formatRelativeTime } from "@/lib/utils";
import { splitRecruitments } from "./profile-helpers";
import { SectionError, SectionHeading, unwrapNoteContent } from "./profile-shared";

/* eslint-disable @typescript-eslint/no-explicit-any -- payload historii i notatek jest luźno typowany */

export type ProfileNavigate = (
  target:
    | { section: "recruitments" }
    | { section: "activity"; noteId?: number }
    | { section: "documents" },
) => void;

export interface ProfileTabProps {
  candidate: any;
  readOnly: boolean;
  /** `/history` — te same dane co zakładka Rekrutacje. */
  recruitments: {
    items: any[];
    isPending: boolean;
    isError: boolean;
    refetch: () => void;
  };
  /** `/api/notes?candidate_id=` — ten sam klucz co lista w „Notatki i historia”. */
  notes: {
    items: any[];
    groupCounts?: Record<string, number> | null;
    isPending: boolean;
    isError: boolean;
    refetch: () => void;
  };
  onNavigate: ProfileNavigate;
}

export function ProfileTab({ candidate, readOnly, recruitments, notes, onNavigate }: ProfileTabProps) {
  return (
    <div className="min-w-0 space-y-6">
      <NowSection
        candidateId={Number(candidate.id)}
        readOnly={readOnly}
        recruitments={recruitments}
        onNavigate={onNavigate}
      />
      <LastTalkSection notes={notes} onNavigate={onNavigate} />
    </div>
  );
}

const FOLLOWUP_TONE_CLASS = {
  danger: "border-destructive/30 bg-destructive/10 text-destructive",
  warning: "border-warning/30 bg-warning-muted text-warning-muted-foreground",
  neutral: "border-border bg-muted/40 text-foreground",
} as const;

export function NowSection({
  candidateId,
  readOnly,
  recruitments,
  onNavigate,
}: {
  candidateId: number;
  readOnly: boolean;
  recruitments: ProfileTabProps["recruitments"];
  onNavigate: ProfileNavigate;
}) {
  const followupQuery = useCandidateFollowup(candidateId);
  const followup = followupQuery.data?.followup ?? null;
  const [followupOpen, setFollowupOpen] = useState(false);
  const active = useMemo(
    () => splitRecruitments(recruitments.items ?? []).active,
    [recruitments.items],
  );

  return (
    <section aria-labelledby="candidate-now-heading" className="space-y-3">
      <SectionHeading id="candidate-now-heading">Teraz</SectionHeading>

      {followup ? (
        <div
          data-testid="now-followup"
          className={cn(
            "flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3 py-2.5 text-sm",
            FOLLOWUP_TONE_CLASS[followupTone(followup.state)],
          )}
        >
          <span className="flex min-w-0 items-center gap-2">
            <PhoneCall className="size-4 shrink-0" aria-hidden />
            <span className="min-w-0">
              <span className="font-medium">
                Telefon po ciszy klienta: {followupDueLabel(followup)}
              </span>
              {followup.caller_name ? (
                <span> · dzwoni {shortPersonName(followup.caller_name)}</span>
              ) : null}
              <span className="text-muted-foreground">
                {" "}
                · {followup.processes.length}{" "}
                {pluralPl(followup.processes.length, "proces czeka", "procesy czekają", "procesów czeka")}
              </span>
            </span>
          </span>
          {!readOnly ? (
            <Button size="sm" variant="outline" onClick={() => setFollowupOpen(true)}>
              Zapisz wynik telefonu
            </Button>
          ) : null}
        </div>
      ) : null}

      {recruitments.isError ? (
        <SectionError title="Nie udało się wczytać rekrutacji." onRetry={recruitments.refetch} />
      ) : recruitments.isPending ? (
        <p className="text-sm text-muted-foreground" aria-busy="true">
          Wczytuję rekrutacje…
        </p>
      ) : active.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nie jest teraz w żadnej rekrutacji.{" "}
          {(recruitments.items ?? []).length > 0 ? (
            <button
              type="button"
              className="font-medium text-primary underline-offset-2 hover:underline"
              onClick={() => onNavigate({ section: "recruitments" })}
            >
              Zakończone rekrutacje ({recruitments.items.length})
            </button>
          ) : null}
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border" data-testid="now-recruitments">
          {active.map((job: any) => (
            <NowRecruitmentRow key={job.job_id} candidateId={candidateId} job={job} />
          ))}
        </ul>
      )}

      {followupOpen ? (
        <CandidateFollowupDialog
          candidateId={candidateId}
          open={followupOpen}
          onOpenChange={setFollowupOpen}
        />
      ) : null}
    </section>
  );
}

function NowRecruitmentRow({ candidateId, job }: { candidateId: number; job: any }) {
  const stage = recruitmentStageLabel(job.latest_stage, job.latest_stage_name, candidateStageLabel);
  const owner = nextActionOwnerLabel(job.next_action_owner);
  const days = daysSince(job.last_seen);
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-sm">
      <span className="min-w-0 flex-1">
        <span className="font-medium text-foreground">{job.job_title ?? "Rekrutacja"}</span>
        {job.client_name ? (
          <span className="text-muted-foreground"> · {job.client_name}</span>
        ) : null}
      </span>
      <Badge variant="neutral">{stage}</Badge>
      {owner ? (
        <span className="text-xs text-muted-foreground">
          ruch: <span className="font-medium text-foreground">{owner}</span>
          {days != null ? ` · ${days} ${pluralPl(days, "dzień", "dni", "dni")}` : null}
        </span>
      ) : null}
      <Link
        href={`/jobs/${job.job_id}?candidate=${candidateId}`}
        className="inline-flex min-h-8 items-center gap-1 text-xs font-medium text-primary hover:underline"
      >
        Tablica <ArrowRight className="size-3" aria-hidden />
      </Link>
    </li>
  );
}

export function LastTalkSection({
  notes,
  onNavigate,
}: {
  notes: ProfileTabProps["notes"];
  onNavigate: ProfileNavigate;
}) {
  const note = useMemo(() => latestTalkNote(notes.items ?? []), [notes.items]);
  const attempts = Number(notes.groupCounts?.contact ?? 0);
  const text = note ? collapsedNotePreview(unwrapNoteContent(note.content_rendered ?? note.content)) : "";
  const dateIso = note?.created_at ?? note?.timestamp ?? null;

  return (
    <section aria-labelledby="candidate-last-talk-heading" className="space-y-3">
      <SectionHeading
        id="candidate-last-talk-heading"
        action={
          <button
            type="button"
            className="text-xs font-medium text-primary hover:underline"
            onClick={() => onNavigate({ section: "activity" })}
          >
            Wszystkie notatki
          </button>
        }
      >
        Ostatnia rozmowa
      </SectionHeading>
      {notes.isError ? (
        <SectionError title="Nie udało się wczytać notatek." onRetry={notes.refetch} />
      ) : notes.isPending ? (
        <p className="text-sm text-muted-foreground" aria-busy="true">
          Wczytuję notatki…
        </p>
      ) : note ? (
        <article className="rounded-lg border border-border px-3 py-2.5" data-testid="last-talk">
          <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
            <MessageSquare className="size-3.5" aria-hidden />
            <span className="font-medium text-foreground">{note.author_name ?? "Import z Traffita"}</span>
            {dateIso ? (
              <time dateTime={dateIso}>{noteDateLabel(dateIso, new Date(), formatRelativeTime)}</time>
            ) : null}
            {note.job_title ? <span>· {note.job_title}</span> : null}
          </p>
          <p className="mt-1.5 whitespace-pre-line text-sm text-foreground">{text}</p>
          <button
            type="button"
            className="mt-1.5 text-xs font-medium text-primary hover:underline"
            onClick={() =>
              onNavigate({ section: "activity", noteId: Number(note.id) || undefined })
            }
          >
            Otwórz notatkę
          </button>
        </article>
      ) : (
        <p className="text-sm text-muted-foreground">Nikt jeszcze nie zapisał rozmowy z tą osobą.</p>
      )}
      {attempts > 0 ? (
        <p className="text-xs text-muted-foreground">
          Prób kontaktu: {attempts} (zakładka „Notatki i historia” → Próby kontaktu)
        </p>
      ) : null}
    </section>
  );
}
