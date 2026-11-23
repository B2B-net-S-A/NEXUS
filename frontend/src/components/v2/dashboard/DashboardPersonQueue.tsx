"use client";

/**
 * „Pracuj po kolei” w „Czeka na Ciebie” (23.11.2026, decyzja Artura —
 * rekomendacja 3 z analizy dnia rekrutera). Panel osoby z Tablicy otwiera się
 * NAD pulpitem, a „‹ N z M ›” i „Dalej” chodzą przez trzy listy pulpitu
 * i wszystkie rekrutacje. Do tej daty „Otwórz” prowadził na Tablicę jednej
 * rekrutacji i strzałki panelu chodziły tylko po jej kolumnie — rekruter
 * przeskakiwał między rekrutacjami ok. 11 razy dziennie.
 *
 * Panel to ten sam `KanbanBoardV2` co na Tablicy, w trybie `panelOnly`
 * (plansza ukryta): ruchy, okna ostrzeżeń, bramki, odrzucenie i notatka idą
 * tą samą drogą (`usePipelineMove`), bez drugiej kopii panelu.
 * Zasady: `docs/claude/ui/pracuj-po-kolei-na-pulpicie.md`.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, ExternalLink, Loader2, X } from "lucide-react";

import { useToast } from "@/components/Toast";
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState";
import { KanbanBoardV2, type PanelOnlyQueue } from "@/components/v2/pages/KanbanBoardV2";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import { PersonPanelShell } from "@/components/v2/person/PersonPanelShell";
import api, { matchingApi } from "@/lib/api";
import { BOARD_TASKS_QUERY_KEY } from "@/lib/api/boardTasks";
import {
  PERSON_QUEUE_LABEL,
  PERSON_QUEUE_LIST_LABEL,
  mergeQueueOrder,
  pairKey,
  personQueueView,
  type PersonPair,
  type PersonQueueEntry,
} from "@/lib/dashboard-person-queue";
import { hasSectionAccess } from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";

type ClosedVerb = "Odrzucono" | "Rezygnacja";

interface AfterClose {
  closed: PersonPair;
  closedKey: string;
  name: string;
  verb: ClosedVerb;
  reason: string | null;
  /** Osoba, która przejęła panel — pasek „Odrzucono: …” stoi tylko przy niej. */
  nextKey: string;
}

export interface DashboardPersonQueueApi {
  /** Otwiera panel na wskazanej osobie albo na pierwszej w kolejce. */
  open: (pair?: PersonPair) => void;
  /** Panel osoby nad pulpitem (portal do `<main>`); `null`, gdy zamknięty. */
  element: ReactNode;
}

function jobKeys(jobId: number) {
  // Te same klucze co strona rekrutacji (`app/jobs/[id]/page.tsx`): ruch
  // z pulpitu odświeża Tablicę otwartą w drugiej karcie i odwrotnie.
  const id = String(jobId);
  return { job: ["job", id], kanban: ["kanban", id], scores: ["pipeline-scores", id] } as const;
}

function fetchJob(jobId: number) {
  return api.get(`/api/jobs/${jobId}`).then((r) => r.data);
}

function fetchKanban(jobId: number) {
  return api.get(`/api/pipeline/kanban/${jobId}`).then((r) => r.data);
}

/**
 * Stan kolejki „Pracuj po kolei”. Kolejność to migawka z chwili otwarcia,
 * do której dochodzą na koniec osoby nowe na liście (`mergeQueueOrder`).
 */
export function useDashboardPersonQueue(entries: readonly PersonQueueEntry[]): DashboardPersonQueueApi {
  const [isOpen, setOpen] = useState(false);
  const [order, setOrder] = useState<string[]>([]);
  const [current, setCurrent] = useState<PersonPair | null>(null);
  const [anchorKey, setAnchorKey] = useState<string | null>(null);
  const [done, setDone] = useState<ReadonlySet<string>>(new Set());
  const [afterClose, setAfterClose] = useState<AfterClose | null>(null);
  const { showSuccess } = useToast();

  // Wpisy, które z listy już wyszły, nadal opisują osobę w panelu (pasek).
  const knownRef = useRef(new Map<string, PersonQueueEntry>());
  for (const entry of entries) knownRef.current.set(entry.key, entry);

  useEffect(() => {
    if (!isOpen) return;
    setOrder((prev) => {
      const merged = mergeQueueOrder(prev, entries);
      return merged.length === prev.length ? prev : merged;
    });
  }, [entries, isOpen]);

  const open = useCallback(
    (pair?: PersonPair) => {
      const target = pair ?? (entries[0] ? { jobId: entries[0].jobId, candidateId: entries[0].candidateId } : null);
      if (!target) return;
      setOrder(entries.map((e) => e.key));
      setCurrent(target);
      setAnchorKey(pairKey(target));
      setDone(new Set());
      setAfterClose(null);
      setOpen(true);
    },
    [entries],
  );
  const close = useCallback(() => {
    setOpen(false);
    setAfterClose(null);
  }, []);
  const goTo = useCallback((entry: PersonQueueEntry) => {
    setCurrent({ jobId: entry.jobId, candidateId: entry.candidateId });
    setAnchorKey(entry.key);
  }, []);

  const currentKey = current ? pairKey(current) : null;
  const view = useMemo(
    () => personQueueView(order, entries, currentKey, anchorKey, done),
    [order, entries, currentKey, anchorKey, done],
  );

  const onClosedFromPanel = useCallback<PanelOnlyQueue["onClosedFromPanel"]>(
    ({ candidateId, name, verb, reasonLabel }) => {
      if (!current || current.candidateId !== candidateId) return;
      const closedKey = pairKey(current);
      // Rekruter zdążył przejść do innej osoby — panel nie skacze.
      if (closedKey !== currentKey) return;
      const nextDone = new Set([...done, closedKey]);
      setDone(nextDone);
      const next = personQueueView(order, entries, closedKey, closedKey, nextDone).next;
      if (!next) {
        close();
        showSuccess(`${verb}: ${name}. To była ostatnia osoba w kolejce „${PERSON_QUEUE_LABEL}”.`);
        return;
      }
      setAfterClose({ closed: current, closedKey, name, verb, reason: reasonLabel, nextKey: next.key });
      goTo(next);
    },
    [current, currentKey, done, order, entries, close, showSuccess, goTo],
  );

  const element =
    isOpen && current ? (
      <QueuePanelHost
        current={current}
        entry={view.current ?? (currentKey ? (knownRef.current.get(currentKey) ?? null) : null)}
        inQueue={view.current != null}
        position={view.position}
        total={view.live.length}
        previous={view.previous}
        next={view.next}
        onGoTo={goTo}
        onClose={close}
        onClosedFromPanel={onClosedFromPanel}
        closedNotice={
          afterClose && currentKey === afterClose.nextKey
            ? {
                verb: afterClose.verb,
                name: afterClose.name,
                reason: afterClose.reason,
                onShow: () => {
                  setCurrent(afterClose.closed);
                  setAnchorKey(afterClose.closedKey);
                },
              }
            : null
        }
        onPersonChange={(candidateId) => {
          const pair = { jobId: current.jobId, candidateId };
          setCurrent(pair);
          if (order.includes(pairKey(pair))) setAnchorKey(pairKey(pair));
        }}
      />
    ) : null;

  return { open, element };
}

interface QueuePanelHostProps {
  current: PersonPair;
  /** Wpis z kolejki osoby w panelu; `null` — osoba spoza list pulpitu. */
  entry: PersonQueueEntry | null;
  inQueue: boolean;
  position: number | null;
  total: number;
  previous: PersonQueueEntry | null;
  next: PersonQueueEntry | null;
  onGoTo: (entry: PersonQueueEntry) => void;
  onClose: () => void;
  onClosedFromPanel: PanelOnlyQueue["onClosedFromPanel"];
  closedNotice: PanelOnlyQueue["closedNotice"];
  onPersonChange: (candidateId: number) => void;
}

function QueuePanelHost(props: QueuePanelHostProps) {
  const { current, next } = props;
  const [target, setTarget] = useState<HTMLElement | null>(null);
  useEffect(() => {
    setTarget(document.getElementById("main") ?? document.body);
  }, []);
  const queryClient = useQueryClient();
  // Osoba dalej w innej rekrutacji: jej Tablica wczytuje się w tle, żeby
  // „Dalej” nie czekało na sieć.
  const nextJobId = next?.jobId ?? null;
  useEffect(() => {
    if (nextJobId == null || nextJobId === current.jobId) return;
    const keys = jobKeys(nextJobId);
    void queryClient.prefetchQuery({ queryKey: keys.kanban, queryFn: () => fetchKanban(nextJobId) });
    void queryClient.prefetchQuery({ queryKey: keys.job, queryFn: () => fetchJob(nextJobId) });
  }, [nextJobId, current.jobId, queryClient]);
  if (!target) return null;
  return createPortal(<QueueJobPanel key={current.jobId} {...props} />, target);
}

function QueueBar({
  entry,
  inQueue,
  next,
  jobId,
  candidateId,
  onGoTo,
}: {
  entry: PersonQueueEntry | null;
  inQueue: boolean;
  next: PersonQueueEntry | null;
  jobId: number;
  candidateId: number;
  onGoTo: (entry: PersonQueueEntry) => void;
}) {
  return (
    <div
      data-testid="person-queue-bar"
      className="shrink-0 space-y-1 border-b border-border bg-primary/5 px-4 py-2 text-[12px] leading-snug"
    >
      <div className="flex min-w-0 items-center gap-2">
        <span className="shrink-0 font-semibold text-primary" data-testid="person-queue-list">
          {entry && inQueue ? PERSON_QUEUE_LIST_LABEL[entry.list] : "Poza kolejką"}
        </span>
        {entry ? (
          <span className="min-w-0 truncate text-muted-foreground" title={entry.jobLabel}>
            {entry.jobLabel}
            {entry.clientName ? ` · ${entry.clientName}` : ""}
            {inQueue ? ` · czeka ${entry.waiting.replace(/^czeka /, "")}` : ""}
          </span>
        ) : null}
        <Link
          href={`/jobs/${jobId}?candidate=${candidateId}`}
          className="ml-auto inline-flex shrink-0 items-center gap-1 font-medium text-primary hover:underline"
        >
          Otwórz Tablicę
          <ExternalLink className="h-3 w-3" aria-hidden="true" />
        </Link>
      </div>
      {!inQueue ? (
        <p className="text-muted-foreground">Ta osoba nie czeka już na liście „Czeka na Ciebie”.</p>
      ) : null}
      {next ? (
        <button
          type="button"
          onClick={() => onGoTo(next)}
          data-testid="person-queue-next"
          className="inline-flex max-w-full items-center gap-1 rounded-md font-medium text-foreground hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          title={`${next.candidateName} · ${next.jobLabel}`}
        >
          <span className="truncate">
            Dalej: <span className="font-semibold">{next.candidateName}</span>
            <span className="text-muted-foreground"> · {next.jobLabel}</span>
          </span>
          <ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        </button>
      ) : (
        <p className="text-muted-foreground">To ostatnia osoba w kolejce.</p>
      )}
    </div>
  );
}

function mainTop(): number | null {
  const main = typeof document !== "undefined" ? document.getElementById("main") : null;
  return main ? Math.round(main.getBoundingClientRect().top) : null;
}

function QueueJobPanel({
  current,
  entry,
  inQueue,
  position,
  total,
  previous,
  next,
  onGoTo,
  onClose,
  onClosedFromPanel,
  closedNotice,
  onPersonChange,
}: QueuePanelHostProps) {
  const { jobId, candidateId } = current;
  const keys = jobKeys(jobId);
  const router = useRouter();
  const queryClient = useQueryClient();
  const authUser = useAuthStore((s) => s.user);
  const impersonating = useAuthStore((s) => s.realUser !== null);
  const readOnly = impersonating || !hasSectionAccess(authUser, "pipeline", "write");

  const job = useQuery({ queryKey: keys.job, queryFn: () => fetchJob(jobId) });
  const kanban = useQuery({ queryKey: keys.kanban, queryFn: () => fetchKanban(jobId) });
  const scores = useQuery({
    queryKey: keys.scores,
    queryFn: () => matchingApi.pipelineScores(jobId).then((r) => r.data),
    staleTime: 5 * 60_000,
  });

  // Ruch z panelu odświeża Tablicę (`kanban`) — wtedy też listy pulpitu, żeby
  // osoba, która przeszła dalej, zniknęła z licznika.
  const seenUpdate = useRef<number | null>(null);
  useEffect(() => {
    if (!kanban.dataUpdatedAt) return;
    if (seenUpdate.current != null && seenUpdate.current !== kanban.dataUpdatedAt) {
      void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
    }
    seenUpdate.current = kanban.dataUpdatedAt;
  }, [kanban.dataUpdatedAt, queryClient]);

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: keys.kanban });
    void queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
    void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
    // `keys` to nowy obiekt w każdym renderze — zależność po numerze rekrutacji.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryClient, jobId]);

  const scoreMap = useMemo(() => {
    const s = scores.data?.scores;
    if (!s) return undefined;
    return new Map<number, number>(Object.entries(s).map(([cid, v]) => [Number(cid), v as number]));
  }, [scores.data]);
  const criticalGapMap = useMemo(() => {
    const m = new Map<number, string[]>();
    for (const [cid, ex] of Object.entries(scores.data?.exclusions ?? {})) {
      if (ex.missing_critical.length) m.set(Number(cid), ex.missing_critical);
    }
    return m;
  }, [scores.data]);
  const criticalAltMap = useMemo(() => {
    const m = new Map<number, Record<string, string[]>>();
    for (const [cid, alts] of Object.entries(scores.data?.alternatives ?? {})) m.set(Number(cid), alts);
    return m;
  }, [scores.data]);

  const bar = (
    <QueueBar
      entry={entry}
      inQueue={inQueue}
      next={next}
      jobId={jobId}
      candidateId={candidateId}
      onGoTo={onGoTo}
    />
  );

  // Pusty stan i plansza wiszą na `isSuccess` — awaria nie może wyglądać jak
  // „brak osoby” (`ui/design-system-…`, reguła frontu z CLAUDE.md).
  if (!kanban.isSuccess || !job.isSuccess) {
    const failed = kanban.isError ? kanban : job.isError ? job : null;
    return (
      <PersonPanelShell size="dock" chromeTop={mainTop()} onBackdropClick={onClose}>
        <div className="flex min-h-0 flex-1 flex-col">
          {bar}
          <div className="flex items-start gap-2 px-4 py-4">
            <div className="min-w-0 flex-1">
              {failed ? (
                <WidgetErrorBlock
                  title="Nie udało się wczytać Tablicy tej rekrutacji."
                  error={failed.error}
                  onRetry={() => void failed.refetch()}
                />
              ) : (
                <p className="inline-flex items-center gap-2 text-sm text-muted-foreground" role="status">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  Wczytuję panel osoby…
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-accent pointer-coarse:p-2.5"
              aria-label="Zamknij dok"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      </PersonPanelShell>
    );
  }

  const jobData = job.data;
  const panelOnly: PanelOnlyQueue = {
    candidateId,
    label: PERSON_QUEUE_LABEL,
    position,
    total,
    onPrevious: () => (previous ? onGoTo(previous) : undefined),
    onNext: () => (next ? onGoTo(next) : undefined),
    next: next ? { name: next.candidateName, stageLabel: next.jobLabel } : null,
    onClosedFromPanel,
    closedNotice,
    onReturnToQueue: !inQueue && next ? () => onGoTo(next) : undefined,
    banner: bar,
    onPersonChange,
    onClose,
  };

  return (
    <KanbanBoardV2
      columns={(kanban.data?.columns ?? []) as KanbanColumn[]}
      offTemplate={kanban.data?.off_template ?? null}
      jobId={jobId}
      jobTitle={jobData?.title}
      scoreMap={scoreMap}
      criticalGapMap={criticalGapMap}
      criticalAltMap={criticalAltMap}
      scoresLoading={scores.isLoading}
      readOnly={readOnly}
      clientId={jobData?.client_id ?? null}
      workbenchContext={{
        clientId: jobData?.client_id ?? null,
        clientName: jobData?.client_name ?? null,
        onMoved: invalidate,
        // Inna zakładka rekrutacji (np. z warsztatu screeningu) jest na jej stronie.
        onTabChange: (tab) => router.push(`/jobs/${jobId}?tab=${encodeURIComponent(tab)}&candidate=${candidateId}`),
        // Zamknięcie rekrutacji zostaje na jej stronie (okno „Zlecenie”).
        canCloseJob: false,
        headcount: typeof jobData?.headcount === "number" ? jobData.headcount : null,
        jobClosed: jobData?.status === "closed",
      }}
      kanbanQueryState={{
        isLoading: kanban.isLoading,
        isError: kanban.isError,
        error: kanban.error,
        isSuccess: kanban.isSuccess,
        refetch: () => void kanban.refetch(),
      }}
      cproEnabled={jobData?.cpro_enabled === true}
      viewerOwnsDlReview={kanban.data?.viewer_owns_dl_review === true}
      openingStartedAt={kanban.data?.opening_started_at ?? null}
      panelOnly={panelOnly}
    />
  );
}
