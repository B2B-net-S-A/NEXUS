"use client";

import { useState, type MouseEvent, type ReactNode } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, Trophy } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  CHAMPION_TONE_CLASS,
  REQUEST_TONE_CLASS,
  RequestStatusMark,
  STAGE_TONE_CLASS,
} from "@/components/v2/jobs/JobListCells";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CHAMPION_SEARCH_MIN,
  championEffectLines,
  championStatusView,
  filterChampionCandidates,
  groupChampionCandidates,
  type ChampionStatusView,
  type JobChampionsFields,
} from "@/lib/job-champions";
import {
  invalidateAfterChampionsChange,
  jobChampionsApi,
  jobChampionsQueryKey,
} from "@/lib/job-champions-api";
import { REQUEST_STAGE_META, requestStageOf, type RequestStage } from "@/lib/request-stage";
import { cn, formatDate } from "@/lib/utils";

export interface JobChampionsStatusProps {
  jobId: number;
  /** Detal rekrutacji: `request_status`, `champions`, `champion_seats`, `hired_count`. */
  job: JobChampionsFields;
  /**
   * Delivery Lead, Head of Recruitment, administrator z zapisem w rekrutacjach
   * (lustro `_CHAMPION_ROLES`): plakietka otwiera edycję listy.
   */
  canEdit: boolean;
  /** Okienko trzyma strona — otwiera je też menu „⋯” → „Championi…”. */
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Rekrutacja z kolejką Cpro: grupa „CV wysłane” nazywa się jak kolumna Tablicy. */
  cproEnabled?: boolean;
  /** Imię championa otwiera panel osoby na Tablicy (bez przeładowania strony). */
  onOpenPerson?: (candidateId: number) => void;
  /** Stan requestu z serwera (`request_stage`) — „Po terminie”, „Klient milczy”… */
  requestStage?: unknown;
  /**
   * Sekcja „Stan rekrutacji” na górze dymka (26.11.2026): DL wstrzymuje
   * i wznawia, rekruter zgłasza „klient wstrzymał?” (`JobHoldPopoverSection`).
   * Z nią plakietka otwiera dymek także bez championów.
   */
  holdSection?: ReactNode;
}

const BADGE_CLASS =
  "inline-flex h-6 min-w-0 max-w-[13rem] items-center gap-1.5 whitespace-nowrap rounded-md px-2 text-xs font-semibold";

function toneClass(view: ChampionStatusView, stage: RequestStage | null): string {
  if (stage) return STAGE_TONE_CLASS[REQUEST_STAGE_META[stage].tone];
  return view.tone === "champion" ? CHAMPION_TONE_CLASS : REQUEST_TONE_CLASS[view.tone];
}

/**
 * Stany listy, które status requestu zna tylko jako „Szukamy” (24.11.2026):
 * „Po terminie”, „Klient milczy”, „Do przejrzenia”, „Zakończony”. Nagłówek
 * mówi to samo co lista — po „Klient milczy” na pasku „Po terminie” nie
 * może dalej stać „Szukamy”.
 */
const STAGES_OVER_SEARCHING: ReadonlySet<RequestStage> = new Set([
  "overdue",
  "client_silent",
  "on_hold",
  "to_review",
  "finished",
]);

export function headerStage(view: ChampionStatusView, requestStage: unknown): RequestStage | null {
  const stage = requestStageOf(requestStage);
  return stage && view.tone !== "champion" && STAGES_OVER_SEARCHING.has(stage) ? stage : null;
}

/** Napis stanu z listy; przy części miejsc z championem zostaje „· 🏆 1 z 2”. */
export function stageStatusView(view: ChampionStatusView, stage: RequestStage): ChampionStatusView {
  const meta = REQUEST_STAGE_META[stage];
  return {
    ...view,
    label: view.seatsText ? `${meta.label} · ${view.seatsText}` : meta.label,
    lead: meta.label,
    title: `${meta.hint} ${view.title}`,
  };
}

function StatusContent({
  view,
  chevron,
  hold = false,
}: {
  view: ChampionStatusView;
  chevron: boolean;
  hold?: boolean;
}) {
  return (
    <>
      {view.kind === "partial" ? (
        <>
          <RequestStatusMark champion={false} />
          <span className="truncate">{view.lead} ·</span>
          <Trophy className="h-3 w-3 shrink-0" aria-hidden="true" />
          <span className="shrink-0 tabular-nums">{view.seatsText}</span>
        </>
      ) : (
        <>
          <RequestStatusMark champion={view.tone === "champion"} hold={hold} />
          <span className="truncate">{view.label}</span>
        </>
      )}
      {chevron ? <ChevronDown className="h-3 w-3 shrink-0 opacity-70" aria-hidden="true" /> : null}
    </>
  );
}

/**
 * Status requestu w nagłówku rekrutacji = jedyne miejsce oznaczania
 * championów (D2, 15.10.2026, makiety
 * https://claude.ai/artifact/VsMAfe4GgPC3g9LHEx2M1z).
 *
 * Plakietka mówi, kto jest championem („Champion: Karol W.”, „Championi:
 * Karol W. +1”), ile miejsc ma championa, gdy szukamy dalej („Szukamy · 1 z 2”),
 * albo „Mamy championa” przy starej fladze bez osób (D1). Delivery Lead
 * klika i zaznacza osoby od „CV wysłane” dalej; zapis wysyła pełną listę.
 * Pozostali widzą listę championów do odczytu, a bez championów — samą
 * plakietkę.
 */
export function JobChampionsStatus({
  jobId,
  job,
  canEdit,
  open,
  onOpenChange,
  cproEnabled = false,
  onOpenPerson,
  requestStage,
  holdSection,
}: JobChampionsStatusProps) {
  const baseView = championStatusView(job);
  if (!baseView) return <span className="text-xs text-muted-foreground">—</span>;
  const stage = headerStage(baseView, requestStage);
  const view = stage ? stageStatusView(baseView, stage) : baseView;
  const hasChampions = Array.isArray(job.champions) && job.champions.length > 0;
  const hold = stage === "on_hold" || baseView.tone === "hold";
  const showChampions = canEdit || hasChampions;

  if (!showChampions && !holdSection) {
    return (
      <span
        title={view.title}
        className={cn(BADGE_CLASS, toneClass(view, stage))}
        data-help="job.champion.found"
        data-testid="job-champions-status"
        data-kind={view.kind}
        data-hold={hold ? "true" : undefined}
      >
        <StatusContent view={view} chevron={false} hold={hold} />
      </span>
    );
  }

  const close = () => onOpenChange(false);
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          title={view.title}
          aria-label={
            showChampions
              ? `${view.label} — championi tej rekrutacji`
              : `${view.label} — stan rekrutacji`
          }
          className={cn(
            BADGE_CLASS,
            toneClass(view, stage),
            "hit-area hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          )}
          data-help="job.champion.found"
          data-testid="job-champions-status"
          data-kind={view.kind}
          data-hold={hold ? "true" : undefined}
        >
          <StatusContent view={view} chevron={canEdit || Boolean(holdSection)} hold={hold} />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        collisionPadding={8}
        className="w-[min(360px,calc(100vw-2rem))] space-y-3"
        data-testid="job-champions-popover"
        // Otwarte z menu „⋯”: zamykane menu oddaje fokus swojemu przyciskowi
        // już PO otwarciu okienka, a to zamykało je od razu. Okienko zamyka
        // klik poza nim, Escape albo „Anuluj” — nie sam ruch fokusu.
        onFocusOutside={(event) => event.preventDefault()}
      >
        {holdSection}
        {showChampions ? (
          <div className={cn("space-y-3", holdSection ? "border-t border-border pt-3" : null)}>
            <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-eyebrow text-muted-foreground">
              <Trophy className="h-3.5 w-3.5 text-medal-gold-foreground" aria-hidden="true" />
              Championi tej rekrutacji
            </p>
            {canEdit ? (
              <ChampionsEditor jobId={jobId} cproEnabled={cproEnabled} onClose={close} />
            ) : (
              <ChampionsReadList jobId={jobId} onOpenPerson={onOpenPerson} onClose={close} />
            )}
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}

function useJobChampions(jobId: number) {
  // Dopiero po otwarciu okienka (komponent żyje tylko wtedy) i zawsze świeże:
  // kolumny osób zmieniają się z każdym ruchem karty.
  return useQuery({
    queryKey: jobChampionsQueryKey(jobId),
    queryFn: () => jobChampionsApi.get(jobId),
    staleTime: 0,
    retry: false,
  });
}

function sameIds(a: ReadonlySet<number>, b: ReadonlySet<number>): boolean {
  if (a.size !== b.size) return false;
  for (const id of a) if (!b.has(id)) return false;
  return true;
}

function ChampionsEditor({
  jobId,
  cproEnabled,
  onClose,
}: {
  jobId: number;
  cproEnabled: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { showSuccess } = useToast();
  const query = useJobChampions(jobId);
  const [draft, setDraft] = useState<ReadonlySet<number> | null>(null);
  const [search, setSearch] = useState("");
  const save = useMutation({
    mutationFn: (candidateIds: number[]) => jobChampionsApi.save(jobId, candidateIds),
    onSuccess: (data) => {
      queryClient.setQueryData(jobChampionsQueryKey(jobId), data);
      invalidateAfterChampionsChange(queryClient, jobId);
      showSuccess("Zapisano championów.");
      onClose();
    },
  });

  if (query.isLoading) {
    return <p className="text-sm text-muted-foreground">Wczytywanie…</p>;
  }
  if (!query.data) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {apiErrorMessage(query.error, "Nie udało się wczytać championów.")}
      </p>
    );
  }

  const data = query.data;
  const initial = new Set(data.eligible.filter((e) => e.is_champion).map((e) => e.candidate_id));
  const selected = draft ?? initial;
  const toggle = (candidateId: number, checked: boolean) => {
    const next = new Set(selected);
    if (checked) next.add(candidateId);
    else next.delete(candidateId);
    setDraft(next);
  };
  const searchable = data.eligible.length >= CHAMPION_SEARCH_MIN;
  const groups = groupChampionCandidates(
    searchable ? filterChampionCandidates(data.eligible, search) : data.eligible,
    { cproEnabled },
  );
  const chosen = data.eligible.filter((e) => selected.has(e.candidate_id));
  const effects = championEffectLines({
    selected: chosen,
    seats: data.seats,
    hiredCount: data.hired_count,
    hadChampions: data.champions.length > 0 || data.legacy_flag,
    workState: data.work_state,
  });
  // Stara flaga bez osób: pusty zapis też jest zmianą — wraca szukanie.
  const dirty = !sameIds(selected, initial) || (data.legacy_flag && selected.size === 0);

  return (
    <div className="space-y-3" data-testid="job-champions-editor">
      {data.legacy_flag ? (
        <p
          className="flex items-start gap-1.5 rounded-md bg-warning-muted px-2 py-1.5 text-xs leading-snug text-warning-muted-foreground"
          data-testid="job-champions-legacy"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          Oznaczone wcześniej bez wskazania osoby. Zaznacz, kto jest championem.
        </p>
      ) : null}

      {data.eligible.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="job-champions-empty">
          Nikt z tej rekrutacji nie jest jeszcze u klienta. Championa można wskazać od „CV
          wysłane”.
        </p>
      ) : (
        <>
          {searchable ? (
            <Input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Szukaj osoby"
              aria-label="Szukaj osoby"
              className="h-8"
            />
          ) : null}
          <div className="max-h-64 space-y-2 overflow-y-auto">
            {groups.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nikt nie pasuje do „{search.trim()}”.</p>
            ) : (
              groups.map((group) => (
                <div key={group.column ?? "other"} role="group" aria-label={group.label}>
                  <p className="px-1.5 text-[11px] font-semibold uppercase tracking-eyebrow text-muted-foreground">
                    {group.label}
                  </p>
                  {group.items.map((person) => {
                    const inputId = `job-${jobId}-champion-${person.candidate_id}`;
                    return (
                      <label
                        key={person.candidate_id}
                        htmlFor={inputId}
                        className="flex cursor-pointer items-start gap-2 rounded-md px-1.5 py-1 hover:bg-accent"
                      >
                        <Checkbox
                          id={inputId}
                          checked={selected.has(person.candidate_id)}
                          onCheckedChange={(value) => toggle(person.candidate_id, value === true)}
                          disabled={save.isPending}
                          className="mt-0.5"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium text-foreground">
                            {person.name}
                          </span>
                          {person.stage_label && person.stage_label !== group.label ? (
                            <span className="block truncate text-xs text-muted-foreground">
                              {person.stage_label}
                            </span>
                          ) : null}
                        </span>
                      </label>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        </>
      )}

      {effects.length > 0 ? (
        <div className="space-y-1 border-t border-border pt-2" data-testid="job-champions-effects">
          {effects.map((line) => (
            <p key={line} className="text-xs leading-snug text-muted-foreground">
              {line}
            </p>
          ))}
        </div>
      ) : null}

      {save.isError ? (
        <p role="alert" className="text-sm text-destructive" data-testid="job-champions-error">
          {apiErrorMessage(save.error, "Nie udało się zapisać championów.")}
        </p>
      ) : null}

      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onClose}>
          Anuluj
        </Button>
        <Button
          type="button"
          size="sm"
          loading={save.isPending}
          disabled={!dirty}
          onClick={() => save.mutate(chosen.map((person) => person.candidate_id))}
          data-testid="job-champions-save"
        >
          Zapisz
        </Button>
      </div>
    </div>
  );
}

function ChampionsReadList({
  jobId,
  onOpenPerson,
  onClose,
}: {
  jobId: number;
  onOpenPerson?: (candidateId: number) => void;
  onClose: () => void;
}) {
  const query = useJobChampions(jobId);
  if (query.isLoading) {
    return <p className="text-sm text-muted-foreground">Wczytywanie…</p>;
  }
  if (!query.data) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {apiErrorMessage(query.error, "Nie udało się wczytać championów.")}
      </p>
    );
  }
  const champions = query.data.champions;
  if (champions.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">Nikt nie jest teraz championem tej rekrutacji.</p>
    );
  }
  const openPerson = (event: MouseEvent<HTMLAnchorElement>, candidateId: number) => {
    // Zwykły klik zostaje na stronie (panel osoby bez przewijania na górę);
    // klik z klawiszem albo środkowym przyciskiem otwiera nową kartę.
    if (!onOpenPerson || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) {
      return;
    }
    event.preventDefault();
    onClose();
    onOpenPerson(candidateId);
  };
  return (
    <ul className="space-y-2" data-testid="job-champions-read-list">
      {champions.map((champion) => {
        const marked = [
          champion.marked_by_name,
          champion.marked_at ? formatDate(champion.marked_at) : null,
        ].filter(Boolean);
        return (
          <li key={champion.candidate_id} className="min-w-0">
            <div className="flex min-w-0 items-baseline gap-1.5 text-sm">
              <Link
                href={`/jobs/${jobId}?candidate=${champion.candidate_id}`}
                onClick={(event) => openPerson(event, champion.candidate_id)}
                className="truncate font-medium text-primary hover:underline"
              >
                {champion.name}
              </Link>
              {champion.stage_label ? (
                <span className="shrink-0 text-xs text-muted-foreground">
                  · {champion.stage_label}
                </span>
              ) : null}
            </div>
            {marked.length > 0 ? (
              <p className="text-xs text-muted-foreground">Oznaczył(a): {marked.join(", ")}</p>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
