"use client";

/**
 * Karta osoby obok panelu „Podobne rekrutacje” (02.10.2026, makieta C:
 * https://claude.ai/artifact/Kj3gM7bCVBPePkXuQLmKc2).
 *
 * Rekruter ma ocenić podpowiedź PRZED przepięciem, bez wychodzenia z panelu:
 * dopasowanie do TEJ rekrutacji, fakty z profilu, status w rekrutacji
 * źródłowej, ostatnia notatka, CV i profil. Trzy istniejące odczyty, każdy
 * z własnym stanem — awaria jednego nie udaje pustki i nie gasi reszty.
 */

import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import {
  ArrowLeft,
  Check,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  FileText,
  Loader2,
  Pin,
  X,
} from "lucide-react";

import { MatchScoreBadge } from "@/components/ds/MatchScoreBadge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { useCandidateCvPreview } from "@/components/v2/candidates/CandidateCvCell";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { scoreFailureFor } from "@/hooks/useVisibleMatchScores";
import api from "@/lib/api";
import { candidateSearchApi, type MatchScoresResponse } from "@/lib/candidate-search-api";
import { jobProposalsApi, jobProposalsKeys, type ProposalFacts } from "@/lib/job-proposals-api";
import { summarizeBreakdown, unmeasuredReason } from "@/lib/match-breakdown";
import {
  clientHistoryLine,
  cvYearBadge,
  factsRateLabel,
  workModeLabel,
  yearsLabel,
} from "@/lib/proposal-facts";
import { availabilityLabel } from "@/lib/proposals-merge";
import {
  similarPersonScoreKey,
  type SentPerson,
  type SimilarJobItem,
} from "@/lib/similar-jobs-api";
import { personStatusLine } from "@/lib/similar-reassign";
import { cn, formatRelativeTime } from "@/lib/utils";

export interface SimilarPersonPreviewProps {
  /** Rekrutacja, DO której przepinamy — do niej liczy się dopasowanie. */
  jobId: number;
  person: SentPerson;
  /** Rekrutacja, w której osoba była wysłana do klienta. */
  sourceJob: SimilarJobItem | null;
  position: { index: number; total: number };
  onPrev: () => void;
  onNext: () => void;
  onClose: () => void;
  canOpenProfile: boolean;
  selection: { checked: boolean; disabled: boolean; onToggle: () => void };
}

/** Z `GET /api/candidates/{id}/quick-view` karta czyta tylko notatki. */
interface QuickViewNotes {
  recent_notes?: Array<{
    id: number;
    content: string;
    created_at: string;
    author_name: string | null;
    pinned?: boolean;
  }>;
}

const SCORE_STALE_MS = 5 * 60_000;
const FACTS_STALE_MS = 60_000;

function httpStatus(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null || !("response" in error)) return undefined;
  const status = (error as { response?: { status?: unknown } }).response?.status;
  return typeof status === "number" ? status : undefined;
}

export function SimilarPersonPreview({
  jobId,
  person,
  sourceJob,
  position,
  onPrev,
  onNext,
  onClose,
  canOpenProfile,
  selection,
}: SimilarPersonPreviewProps) {
  const candidateId = person.candidate_id;
  const rootRef = useRef<HTMLElement>(null);
  const cv = useCandidateCvPreview(candidateId);

  // Fokus na karcie od razu po otwarciu i po zmianie osoby (karta jest
  // montowana per osoba) — ↑ ↓ działają bez dodatkowego kliknięcia.
  useEffect(() => {
    rootRef.current?.focus();
  }, []);

  // Ten sam klucz i kształt cache (lista) co „Dodaj kandydatów” → Propozycje.
  const facts = useQuery({
    queryKey: jobProposalsKeys.facts(jobId, [candidateId]),
    queryFn: ({ signal }) =>
      jobProposalsApi.facts(jobId, [candidateId], signal).then((data) => data.items),
    select: (items: ProposalFacts[]) => items[0] ?? null,
    staleTime: FACTS_STALE_MS,
  });
  const score = useQuery({
    queryKey: similarPersonScoreKey(jobId, candidateId),
    queryFn: ({ signal }) => candidateSearchApi.matchScores(jobId, [candidateId], { signal }),
    staleTime: SCORE_STALE_MS,
  });
  const notes = useQuery<QuickViewNotes>({
    queryKey: candidateQueryKeys.quickView(candidateId),
    queryFn: ({ signal }) =>
      api.get(`/api/candidates/${candidateId}/quick-view`, { signal }).then((r) => r.data),
    staleTime: FACTS_STALE_MS,
  });

  const hasPrev = position.index > 0;
  const hasNext = position.index < position.total - 1;

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    // Okno CV jest portalem: jego zdarzenia bąbelkują przez drzewo Reacta,
    // ale nie leżą w DOM karty — strzałki w podglądzie CV nie zmieniają osoby.
    if (!event.currentTarget.contains(event.target as Node)) return;
    const target = event.target as HTMLElement;
    if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;
    if (event.key === "ArrowUp" && hasPrev) {
      event.preventDefault();
      onPrev();
    } else if (event.key === "ArrowDown" && hasNext) {
      event.preventDefault();
      onNext();
    }
  };

  const f = facts.data ?? null;
  const headline = [
    f?.title ? [f.title, f.company ? `@ ${f.company}` : null].filter(Boolean).join(" ") : null,
    yearsLabel(f?.years_experience),
  ]
    .filter(Boolean)
    .join(" · ");

  const lockedReason = !person.selectable
    ? person.already_in_job
      ? "Ta osoba jest już w tej rekrutacji."
      : "Pracuje u klienta — nie da się jej przepiąć."
    : null;

  return (
    <section
      ref={rootRef}
      tabIndex={-1}
      aria-label={`Podgląd: ${person.name}`}
      onKeyDown={onKeyDown}
      className="flex h-full min-h-0 flex-col outline-hidden"
      data-testid="similar-person-preview"
    >
      <header className="border-b border-border px-4 py-3">
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon-sm"
            className="lg:hidden"
            onClick={onClose}
            aria-label="Wróć do listy"
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h3 className="min-w-0 flex-1 truncate px-1 text-base font-semibold">{person.name}</h3>
          <span className="whitespace-nowrap px-1 text-xs tabular-nums text-muted-foreground">
            {position.index + 1} z {position.total}
          </span>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onPrev}
            disabled={!hasPrev}
            aria-label="Poprzednia osoba"
          >
            <ChevronUp className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onNext}
            disabled={!hasNext}
            aria-label="Następna osoba"
          >
            <ChevronDown className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className="max-lg:hidden"
            onClick={onClose}
            aria-label="Zamknij podgląd"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
        {headline ? (
          <p className="truncate px-1 text-sm text-muted-foreground">{headline}</p>
        ) : null}
      </header>

      <div className="flex items-center gap-2 border-b border-border px-5 py-2">
        <Checkbox
          id={`similar-preview-pick-${candidateId}`}
          checked={selection.checked}
          onCheckedChange={selection.onToggle}
          disabled={selection.disabled}
        />
        <label htmlFor={`similar-preview-pick-${candidateId}`} className="text-sm">
          {lockedReason ?? "Przepnij tę osobę do „Nowych”"}
        </label>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-4">
        <Section
          title="Dopasowanie do tej rekrutacji"
          aside={<ScoreBadge query={score} candidateId={candidateId} />}
        >
          <ScoreBody query={score} candidateId={candidateId} />
        </Section>

        <Section title="Profil">
          {facts.isPending ? (
            <Muted>Wczytuję dane z profilu…</Muted>
          ) : facts.isError ? (
            <Failure text="Nie udało się wczytać danych z profilu." onRetry={() => facts.refetch()} />
          ) : (
            <FactsBody facts={f} />
          )}
        </Section>

        <Section title={sourceJob ? `W rekrutacji: ${sourceJob.title}` : "W rekrutacji źródłowej"}>
          <p className="text-sm">{personStatusLine(person)}</p>
          {sourceJob ? (
            <p className="text-xs text-muted-foreground">
              {[sourceJob.client_name, sourceJob.reference_number].filter(Boolean).join(" · ")}
            </p>
          ) : null}
        </Section>

        {notes.isError && httpStatus(notes.error) === 403 ? null : (
          <Section title="Notatki">
            {notes.isPending ? (
              <Muted>Wczytuję notatki…</Muted>
            ) : notes.isError ? (
              <Failure text="Nie udało się wczytać notatek." onRetry={() => notes.refetch()} />
            ) : (
              <NotesBody notes={notes.data?.recent_notes ?? []} />
            )}
          </Section>
        )}
      </div>

      <footer className="flex flex-wrap items-center gap-2 border-t border-border px-5 py-3">
        <Button variant="outline" size="sm" onClick={() => void cv.open()} disabled={cv.loading}>
          {cv.loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <FileText className="h-3.5 w-3.5" aria-hidden />
          )}
          Podgląd CV
        </Button>
        {canOpenProfile ? (
          <Button asChild size="sm">
            <a
              href={`/candidates/${candidateId}?from=job&jobId=${jobId}`}
              target="_blank"
              rel="noopener"
            >
              Otwórz profil
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            </a>
          </Button>
        ) : null}
        {cv.modal}
      </footer>
    </section>
  );
}

function Section({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-label={title} className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h4 className="min-w-0 truncate text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </h4>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Muted({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

function Failure({ text, onRetry }: { text: string; onRetry: () => void }) {
  return (
    <p className="text-sm text-destructive">
      {text}{" "}
      <button type="button" className="font-medium underline" onClick={onRetry}>
        Ponów
      </button>
    </p>
  );
}

type ScoreQuery = UseQueryResult<MatchScoresResponse>;

function ScoreBadge({ query, candidateId }: { query: ScoreQuery; candidateId: number }) {
  if (!query.isSuccess) return null;
  const value = query.data.scores[String(candidateId)];
  return (
    <MatchScoreBadge
      score={typeof value === "number" ? value : null}
      emptyLabel="Ocena niepełna"
      className="shrink-0"
    />
  );
}

function ScoreBody({ query, candidateId }: { query: ScoreQuery; candidateId: number }) {
  if (query.isPending) return <Muted>Liczę dopasowanie…</Muted>;
  if (query.isError) {
    return scoreFailureFor(query.error) === "forbidden" ? (
      <Muted>Nie masz dostępu do oceny dopasowania w tej rekrutacji.</Muted>
    ) : (
      <Failure text="Nie policzono dopasowania." onRetry={() => query.refetch()} />
    );
  }
  const key = String(candidateId);
  const breakdown = query.data.breakdowns[key];
  const measured = typeof query.data.scores[key] === "number";
  const summary = summarizeBreakdown(breakdown);
  const reason = unmeasuredReason(breakdown?.measurement);
  const hasMust = summary.matchedMust.length > 0 || summary.gapMust.length > 0;
  return (
    <div className="space-y-2">
      {!measured ? (
        <Muted>
          Brak pełnego pomiaru{reason ? ` — ${reason}` : ""}. To nie znaczy, że osoba nie pasuje.
        </Muted>
      ) : null}
      {hasMust ? (
        <ul className="flex flex-wrap gap-1.5" aria-label="Wymagania must-have">
          {summary.matchedMust.map((skill) => (
            <li
              key={`met-${skill}`}
              className="inline-flex items-center gap-1 rounded-md bg-success-muted px-2 py-0.5 text-xs text-success-muted-foreground"
            >
              <Check className="h-3 w-3" aria-hidden />
              {skill}
            </li>
          ))}
          {summary.gapMust.map((skill) => (
            <li
              key={`gap-${skill}`}
              className="rounded-md bg-warning-muted px-2 py-0.5 text-xs text-warning-muted-foreground"
            >
              {skill} — nie znaleziono
            </li>
          ))}
        </ul>
      ) : measured ? (
        <Muted>Ta rekrutacja nie ma wymagań must-have do porównania.</Muted>
      ) : null}
    </div>
  );
}

function FactsBody({ facts }: { facts: ProposalFacts | null }) {
  if (!facts) return <Muted>Nie znaleziono profilu tej osoby.</Muted>;
  const tiles: Array<[string, string | null]> = [
    ["Miasto", facts.city?.trim() || null],
    ["Tryb pracy", workModeLabel(facts)],
    ["Stawka", factsRateLabel(facts)],
    ["Dostępność", availabilityLabel(facts.availability_status, facts.availability_date)],
  ];
  const known = tiles.filter((tile): tile is [string, string] => tile[1] !== null);
  const history = clientHistoryLine(facts.client_history);
  const cvBadge = cvYearBadge(facts.cv_uploaded_on);
  if (known.length === 0 && !history && !cvBadge) {
    return <Muted>Profil nie ma jeszcze miasta, trybu pracy, stawki ani dostępności.</Muted>;
  }
  return (
    <div className="space-y-2">
      {known.length > 0 ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
          {known.map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="truncate text-sm">{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {history ? <p className="text-sm">{history}</p> : null}
      {cvBadge ? (
        <span
          className={cn(
            "inline-block rounded px-1.5 py-0.5 text-xs",
            cvBadge.stale
              ? "bg-warning-muted text-warning-muted-foreground"
              : "bg-muted text-muted-foreground",
          )}
        >
          {cvBadge.label}
        </span>
      ) : null}
    </div>
  );
}

function NotesBody({ notes }: { notes: NonNullable<QuickViewNotes["recent_notes"]> }) {
  // Jak w szybkim podglądzie kandydata: przypięte + ostatnia zwykła.
  const pinned = notes.filter((note) => note.pinned);
  const latest = notes.find((note) => !note.pinned);
  const shown = latest ? [...pinned, latest] : pinned;
  if (shown.length === 0) return <Muted>Brak notatek.</Muted>;
  return (
    <div className="space-y-2">
      {shown.map((note) => (
        <figure key={note.id} className="rounded-lg bg-muted/50 px-3 py-2">
          <blockquote className="line-clamp-4 whitespace-pre-wrap text-sm">{note.content}</blockquote>
          <figcaption className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
            {note.pinned ? <Pin className="h-3 w-3 text-primary" aria-label="Przypięta" /> : null}
            {note.author_name || "System / import"} · {formatRelativeTime(note.created_at)}
          </figcaption>
        </figure>
      ))}
    </div>
  );
}
