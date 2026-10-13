"use client";

/**
 * Zakładka „Przegląd” (domyślna). Od 13.10.2026 (decyzja E2) odpowiada na
 * pytanie „kim jest i co trzeba zrobić” — do tej pory była kopią procesów
 * z „Rekrutacji” i przy osobie bez procesu prawie pusta:
 *
 * - „W skrócie” (karta AI albo opis z CV) i „Ostatnio” (3 ostatnie stanowiska),
 * - 8 głównych umiejętności (wszystkie w zakładce „CV”),
 * - „Do zrobienia” — zaległy telefon po ciszy klienta i TYLKO procesy, w których
 *   ruch jest po naszej stronie (pełna lista procesów: „Rekrutacje”),
 * - pasek „Z nami” (w toku, zakończone, ostatnia rozmowa, próby kontaktu,
 *   w bazie od),
 * - „Ostatnia rozmowa” zwinięta do 3 linii.
 *
 * Fakty do propozycji (dostępność, stawka, praca, języki) stoją w karcie
 * „Do propozycji” w lewej kolumnie — tu ich nie powtarzamy.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, MessageSquare, PhoneCall } from "lucide-react";

import { skillsApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CandidateActivitySummaryCard } from "@/components/v2/pages/CandidateActivitySummaryCard";
import { formatExperienceDate } from "@/components/v2/pages/candidate-profile-helpers";
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
  recentRoles,
  recruitmentsAwaitingUs,
} from "@/lib/candidate-overview";
import { collapsedNotePreview, noteDateLabel } from "@/lib/candidate-notes-view";
import { pluralPl } from "@/lib/plural-pl";
import { recruitmentOutcome, recruitmentStageLabel } from "@/lib/recruitment-stage-label";
import { displaySkills, skillDictionaryIndex } from "@/lib/skill-display";
import { cn, formatDate, formatRelativeTime } from "@/lib/utils";
import { screeningConfirmedSkills, splitRecruitments } from "./profile-helpers";
import { SectionError, SectionHeading, unwrapNoteContent } from "./profile-shared";

/* eslint-disable @typescript-eslint/no-explicit-any -- payload historii i notatek jest luźno typowany */

export type ProfileNavigate = (
  target:
    | { section: "recruitments" }
    | { section: "activity"; noteId?: number; activity?: "contact" }
    | { section: "cv" }
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
  /** `/api/notes?candidate_id=` — ten sam klucz co lista w zakładce „Notatki”. */
  notes: {
    items: any[];
    groupCounts?: Record<string, number> | null;
    isPending: boolean;
    isError: boolean;
    refetch: () => void;
  };
  onNavigate: ProfileNavigate;
}

/** Ile umiejętności na Przeglądzie — reszta w zakładce „CV”. */
const OVERVIEW_SKILLS = 8;
/** Ile procesów w „Do zrobienia” — reszta w „Rekrutacjach”. */
const OVERVIEW_TODO = 3;

export function ProfileTab({ candidate, readOnly, recruitments, notes, onNavigate }: ProfileTabProps) {
  return (
    <div className="min-w-0 space-y-6">
      <div className="grid min-w-0 gap-4 @2xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <CandidateActivitySummaryCard
          candidateId={Number(candidate.id)}
          cvSummary={candidate.ai_summary ?? null}
          variant="compact"
        />
        <RecentRolesSection candidate={candidate} onNavigate={onNavigate} />
      </div>
      <TopSkillsSection candidate={candidate} onNavigate={onNavigate} />
      <NowSection
        candidateId={Number(candidate.id)}
        readOnly={readOnly}
        recruitments={recruitments}
        onNavigate={onNavigate}
      />
      <WithUsStrip candidate={candidate} recruitments={recruitments} notes={notes} onNavigate={onNavigate} />
      <LastTalkSection notes={notes} onNavigate={onNavigate} />
    </div>
  );
}

function RecentRolesSection({
  candidate,
  onNavigate,
}: {
  candidate: any;
  onNavigate: ProfileNavigate;
}) {
  const roles = useMemo(
    () => recentRoles(candidate.experience, formatExperienceDate),
    [candidate.experience],
  );
  if (roles.length === 0) return null;
  return (
    <section aria-labelledby="candidate-recent-roles-heading" className="min-w-0 space-y-2">
      <SectionHeading
        id="candidate-recent-roles-heading"
        action={
          <button
            type="button"
            className="text-xs font-medium text-primary hover:underline"
            onClick={() => onNavigate({ section: "cv" })}
          >
            Pełne CV
          </button>
        }
      >
        Ostatnio
      </SectionHeading>
      <ul className="space-y-1.5" data-testid="recent-roles">
        {roles.map((role, index) => (
          <li key={index} className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-2 text-sm">
            <span className="text-xs tabular-nums text-muted-foreground">{role.period}</span>
            <span className="min-w-0">
              {role.role ? <span className="font-medium text-foreground">{role.role}</span> : null}
              {role.role && role.company ? <span className="text-muted-foreground"> · </span> : null}
              {role.company ? <span className="text-muted-foreground">{role.company}</span> : null}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Główne umiejętności — ten sam słownik nazw (klucz `["skills-dictionary", 500]`)
 * co zakładka „CV”, więc jedno pobranie. Potwierdzone na screeningu bierzemy
 * z profilu (`verified_tech`) — bez dodatkowego zapytania o profil AI na
 * domyślnej zakładce.
 */
function TopSkillsSection({ candidate, onNavigate }: { candidate: any; onNavigate: ProfileNavigate }) {
  const dictionaryQuery = useQuery({
    queryKey: ["skills-dictionary", 500],
    queryFn: () => skillsApi.list(500).then((r) => r.data.items),
    staleTime: 60 * 60 * 1000,
    retry: false,
  });
  const items = useMemo(
    () =>
      displaySkills(Array.isArray(candidate.skills) ? candidate.skills : [], {
        dictionary: skillDictionaryIndex(dictionaryQuery.data),
        confirmed: screeningConfirmedSkills(candidate.verified_tech, undefined),
      }),
    [candidate.skills, candidate.verified_tech, dictionaryQuery.data],
  );
  if (items.length === 0) return null;
  const rest = items.length - OVERVIEW_SKILLS;
  return (
    <section aria-label="Główne umiejętności" className="flex flex-wrap items-center gap-1.5">
      {items.slice(0, OVERVIEW_SKILLS).map((skill) => (
        <span
          key={skill.name}
          title={skill.variants.length > 1 ? `W CV jako: ${skill.variants.join(", ")}` : undefined}
          className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2.5 py-0.5 text-xs text-foreground"
        >
          {skill.name}
          {skill.years ? (
            <span className="text-[11px] text-muted-foreground">{skill.years} l.</span>
          ) : null}
        </span>
      ))}
      {rest > 0 ? (
        <button
          type="button"
          className="text-xs font-medium text-primary hover:underline"
          onClick={() => onNavigate({ section: "cv" })}
        >
          +{rest} w zakładce CV
        </button>
      ) : null}
    </section>
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
  const { active, ended } = useMemo(
    () => splitRecruitments(recruitments.items ?? []),
    [recruitments.items],
  );
  const awaiting = useMemo(() => recruitmentsAwaitingUs(active), [active]);
  const lastEnded = ended[0] ?? null;

  return (
    <section aria-labelledby="candidate-now-heading" className="space-y-3">
      <SectionHeading id="candidate-now-heading">Do zrobienia</SectionHeading>

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
          Nie jest teraz w żadnej rekrutacji.
          {lastEnded ? (
            <>
              {" "}
              Ostatnio: {recruitmentOutcome(lastEnded).label.toLowerCase()} ·{" "}
              {lastEnded.job_title ?? "rekrutacja"}
              {lastEnded.last_seen ? ` (${formatDate(lastEnded.last_seen)})` : ""}.{" "}
            </>
          ) : (
            " "
          )}
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
      ) : awaiting.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="now-nothing-on-us">
          W {active.length} {pluralPl(active.length, "procesie", "procesach", "procesach")} ruch jest
          po stronie klienta albo kandydata.{" "}
          <button
            type="button"
            className="font-medium text-primary underline-offset-2 hover:underline"
            onClick={() => onNavigate({ section: "recruitments" })}
          >
            Rekrutacje w toku ({active.length})
          </button>
        </p>
      ) : (
        <>
          <ul className="divide-y divide-border rounded-lg border border-border" data-testid="now-recruitments">
            {awaiting.slice(0, OVERVIEW_TODO).map((job: any) => (
              <NowRecruitmentRow key={job.job_id} candidateId={candidateId} job={job} />
            ))}
          </ul>
          {active.length > Math.min(awaiting.length, OVERVIEW_TODO) ? (
            <button
              type="button"
              className="text-xs font-medium text-primary hover:underline"
              onClick={() => onNavigate({ section: "recruitments" })}
            >
              Wszystkie w toku ({active.length}) w zakładce Rekrutacje
            </button>
          ) : null}
        </>
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

/** Pasek „Z nami” — liczby i daty, każda prowadzi do swojej zakładki. */
function WithUsStrip({
  candidate,
  recruitments,
  notes,
  onNavigate,
}: {
  candidate: any;
  recruitments: ProfileTabProps["recruitments"];
  notes: ProfileTabProps["notes"];
  onNavigate: ProfileNavigate;
}) {
  const { active, ended } = useMemo(
    () => splitRecruitments(recruitments.items ?? []),
    [recruitments.items],
  );
  const lastTalk = useMemo(() => latestTalkNote(notes.items ?? []), [notes.items]);
  const attempts = Number(notes.groupCounts?.contact ?? 0);
  const createdAt = candidate.created_at ? formatDate(candidate.created_at) : null;
  const source =
    candidate.external_source === "traffit" || candidate.source === "traffit"
      ? "Traffit"
      : null;
  const linkClass = "font-medium text-primary hover:underline";
  return (
    <p
      aria-label="Z nami"
      className="flex flex-wrap gap-x-5 gap-y-1 border-y border-border py-2 text-xs text-muted-foreground"
    >
      {!recruitments.isPending && !recruitments.isError ? (
        <>
          <button type="button" className={linkClass} onClick={() => onNavigate({ section: "recruitments" })}>
            W toku: <span className="tabular-nums">{active.length}</span>
          </button>
          <span>
            Zakończone: <span className="tabular-nums font-medium text-foreground">{ended.length}</span>
          </span>
        </>
      ) : null}
      {lastTalk ? (
        <span>
          Ostatnia rozmowa:{" "}
          <span className="font-medium text-foreground">
            {formatDate(lastTalk.created_at ?? lastTalk.timestamp)}
          </span>
          {lastTalk.author_name ? ` · ${shortPersonName(lastTalk.author_name)}` : ""}
        </span>
      ) : null}
      {attempts > 0 ? (
        <button type="button" className={linkClass} onClick={() => onNavigate({ section: "activity", activity: "contact" })}>
          Prób kontaktu: <span className="tabular-nums">{attempts}</span>
        </button>
      ) : null}
      {createdAt ? (
        <span>
          W bazie od <span className="font-medium text-foreground">{createdAt}</span>
          {source ? ` (${source})` : ""}
        </span>
      ) : null}
    </p>
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
          <p className="mt-1.5 line-clamp-3 whitespace-pre-line text-sm text-foreground">{text}</p>
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
    </section>
  );
}
