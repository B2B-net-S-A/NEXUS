"use client";

/**
 * Okno „Historia i czat" — dawne zakładki `?tab=history` i `?tab=chat`
 * w jednym miejscu obok tabeli (makieta V3Historia).
 *
 * „Wszystko" NIE oznacza czatu jako przeczytanego: pokazuje podgląd ostatnich
 * wiadomości tylko do odczytu, a pełny czat (który oznacza) jest na swojej
 * zakładce. „Ruchy" czytają dziennik ruchów rekrutacji z serwera.
 *
 * Czat i historia requestów to ISTNIEJĄCE komponenty, osadzone bez zmian:
 * przypinanie, reakcje, edycja i „przeczytane przez" czatu oraz bramkowanie
 * kwot fee w historii działają dokładnie jak w dawnych zakładkach.
 */

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cog } from "lucide-react";

import api, { jobChatApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { httpStatusFromError } from "@/lib/view-state";
import { Button } from "@/components/ui/button";
import { cn, formatDate } from "@/lib/utils";
import {
  BACKGROUND_EVENTS_MAX,
  BACKGROUND_EVENTS_STEP,
  backgroundEventMessage,
  backgroundEventTone,
  jobBackgroundEventsApi,
  jobBackgroundEventsQueryKey,
  type BackgroundEventTone,
  type JobBackgroundEvent,
} from "@/lib/job-background-events";

import { EmptyState, TabbedNav } from "@/components/ds";
import { RequestHistorySection } from "@/components/RequestHistorySection";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import JobChatTab from "@/components/v2/pages/JobChatTab";

import {
  formatDaysAgo,
  latestMovesFromKanban,
  type RecruitmentMoveEntry,
} from "./history-moves";
import { RecruitmentSheet } from "./RecruitmentSheet";

export type HistoryChatTab = "all" | "chat" | "moves" | "request" | "background";

export interface HistoryChatSlideOverProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  clientId: number | null;
  readOnly?: boolean;
  /**
   * Zakładka startowa. Stare linki: `?tab=history` → `"request"`,
   * `?tab=chat` → `"chat"`. Czytana przy KAŻDYM otwarciu okna, nie raz przy
   * montażu — okno żyje na stronie cały czas, zmienia się tylko `open`.
   */
  initialTab?: HistoryChatTab;
  /** Nieprzeczytane wiadomości czatu — odznaka na zakładce. */
  chatUnreadCount?: number;
  /**
   * Kolumny kanbana, które strona już ma. `undefined` = jeszcze nie wczytane
   * (zakładka „Ruchy" mówi to wprost zamiast udawać pustą rekrutację).
   */
  columns?: readonly KanbanColumn[];
}

const ALL_TAB_MOVES_LIMIT = 5;
const ALL_TAB_BACKGROUND_LIMIT = 5;

function SectionHeading({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-[11px] font-bold uppercase tracking-wide text-muted-foreground">
      {children}
    </h3>
  );
}

function MovesList({
  moves,
  columnsLoaded,
}: {
  moves: RecruitmentMoveEntry[];
  columnsLoaded: boolean;
}) {
  if (!columnsLoaded) {
    return (
      <p className="text-sm text-muted-foreground">Ładowanie osób w rekrutacji…</p>
    );
  }
  if (moves.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        W tej rekrutacji nie ma jeszcze nikogo, więc nie było żadnego ruchu.
      </p>
    );
  }
  return (
    <ul className="space-y-2.5" aria-label="Ostatnie ruchy w rekrutacji">
      {moves.map((move) => (
        <li key={move.key} className="flex gap-3 text-[13px]">
          <span className="w-[72px] shrink-0 text-muted-foreground">
            {formatDaysAgo(move.daysInStage)}
          </span>
          <span
            className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-primary"
            aria-hidden="true"
          />
          <span className="min-w-0">
            <Link
              href={`/candidates/${move.candidateId}`}
              className="font-medium text-foreground hover:text-primary hover:underline"
            >
              {move.fullName}
            </Link>
            <span className="text-foreground"> → {move.stageLabel}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

// ── Dziennik ruchów rekrutacji (`GET /api/pipeline/job/{id}/moves`) ─────────

export interface JobMoveLogItem {
  id: number;
  candidate_id: number;
  /** `null` = rola bez odczytu kandydatów (nazwiska zredagowane). */
  candidate_name: string | null;
  from_stage_name: string | null;
  to_stage_name: string | null;
  moved_by_name: string | null;
  moved_at: string | null;
  source: "traffit" | "nexus" | (string & {});
}

interface JobMoveLogPage {
  items: JobMoveLogItem[];
  total: number;
  next_offset?: number | null;
}

const MOVES_PAGE = 50;

export const jobMovesQueryKey = (jobId: number) => ["job-pipeline-moves", jobId] as const;

function moveWhen(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const time = date.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
  return `${formatDate(iso)} ${time}`;
}

function MoveLogList({ items }: { items: readonly JobMoveLogItem[] }) {
  return (
    <ul className="space-y-2.5" aria-label="Ruchy w rekrutacji">
      {items.map((move) => (
        <li key={move.id} className="flex gap-3 text-[13px]">
          <span className="w-[92px] shrink-0 text-xs text-muted-foreground">{moveWhen(move.moved_at)}</span>
          <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
          <span className="min-w-0">
            <Link
              href={`/candidates/${move.candidate_id}`}
              className="font-medium text-foreground hover:text-primary hover:underline"
            >
              {move.candidate_name ?? `Kandydat #${move.candidate_id}`}
            </Link>
            <span className="text-foreground">
              {move.from_stage_name ? ` ${move.from_stage_name}` : ""} → {move.to_stage_name ?? "—"}
            </span>
            <span className="block text-xs text-muted-foreground">
              {move.moved_by_name ?? (move.source === "traffit" ? "import z Traffita" : "autor nieznany")}
              {move.source === "traffit" && move.moved_by_name ? " · Traffit" : ""}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * Pełny dziennik ruchów z serwera; gdy trasy jeszcze nie ma (404 — starszy
 * backend), wraca lista wyprowadzona z tablicy („ostatni ruch każdej osoby").
 * Inny błąd renderuje się jako błąd, nigdy jako pusta rekrutacja.
 */
function MovesSection({
  jobId,
  fallbackMoves,
  columnsLoaded,
  limit,
  onShowAll,
}: {
  jobId: number;
  fallbackMoves: RecruitmentMoveEntry[];
  columnsLoaded: boolean;
  /** Skrót na zakładce „Wszystko" — bez stronicowania. */
  limit?: number;
  onShowAll?: () => void;
}) {
  const query = useInfiniteQuery({
    queryKey: jobMovesQueryKey(jobId),
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api
        .get<JobMoveLogPage>(`/api/pipeline/job/${jobId}/moves`, {
          params: { limit: MOVES_PAGE, offset: pageParam },
        })
        .then((r) => r.data),
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0);
      return loaded < last.total && last.items.length > 0 ? loaded : undefined;
    },
    retry: false,
    staleTime: 30_000,
  });

  if (query.isError && httpStatusFromError(query.error) === 404) {
    const moves = limit ? fallbackMoves.slice(0, limit) : fallbackMoves;
    return (
      <div className="space-y-3">
        {!limit ? (
          <p className="text-xs text-muted-foreground">
            Ostatni ruch każdej osoby — od najświeższego. Pełną historię etapów
            jednej osoby znajdziesz w jej panelu.
          </p>
        ) : null}
        <MovesList moves={moves} columnsLoaded={columnsLoaded} />
        {limit && fallbackMoves.length > limit && onShowAll ? (
          <button type="button" onClick={onShowAll} className="text-xs font-medium text-primary hover:underline">
            Pokaż wszystkie ruchy ({fallbackMoves.length})
          </button>
        ) : null}
      </div>
    );
  }
  if (query.isLoading) {
    return <p className="text-sm text-muted-foreground">Ładowanie ruchów…</p>;
  }
  if (query.isError) {
    return (
      <p role="alert" className="text-sm text-destructive-muted-foreground">
        Nie udało się wczytać ruchów: {apiErrorMessage(query.error, "błąd serwera")}.{" "}
        <button type="button" className="font-medium underline underline-offset-2" onClick={() => void query.refetch()}>
          Ponów
        </button>
      </p>
    );
  }

  const all = query.data?.pages.flatMap((p) => p.items) ?? [];
  const total = query.data?.pages[0]?.total ?? all.length;
  if (query.isSuccess && all.length === 0) {
    return <p className="text-sm text-muted-foreground">W tej rekrutacji nie było jeszcze żadnego ruchu.</p>;
  }
  const items = limit ? all.slice(0, limit) : all;
  return (
    <div className="space-y-3">
      {!limit ? (
        <p className="text-xs text-muted-foreground">
          Wszystkie ruchy etapów w tej rekrutacji — od najnowszego ({total}).
        </p>
      ) : null}
      <MoveLogList items={items} />
      {limit ? (
        total > limit && onShowAll ? (
          <button type="button" onClick={onShowAll} className="text-xs font-medium text-primary hover:underline">
            Pokaż wszystkie ruchy ({total})
          </button>
        ) : null
      ) : query.hasNextPage ? (
        <Button variant="outline" size="sm" loading={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
          Pokaż więcej
        </Button>
      ) : null}
    </div>
  );
}

// ── Podgląd czatu na zakładce „Wszystko" ────────────────────────────────────

const CHAT_PREVIEW_LIMIT = 5;

/**
 * Ostatnie wiadomości TYLKO DO ODCZYTU. `JobChatTab` oznacza czat jako
 * przeczytany już przy montażu, a „Wszystko" otwiera się domyślnie — samo
 * zajrzenie do historii ruchów kasowałoby odznakę nieprzeczytanych, zanim
 * ktokolwiek zobaczy wiadomości. Odczyt listy niczego nie oznacza.
 */
function ChatPreview({
  jobId,
  unreadCount,
  onOpenChat,
}: {
  jobId: number;
  unreadCount: number;
  onOpenChat: () => void;
}) {
  const query = useQuery({
    queryKey: ["job-chat-preview", jobId],
    queryFn: () =>
      jobChatApi.listMessages(jobId, { limit: CHAT_PREVIEW_LIMIT }).then((r) => r.data),
    staleTime: 15_000,
    retry: false,
  });
  // Serwer oddaje od najnowszej; czytamy jak rozmowę — od najstarszej.
  const messages = [...(query.data?.items ?? [])].reverse();
  return (
    <div className="space-y-2.5">
      {query.isLoading ? (
        <p className="text-sm text-muted-foreground">Ładowanie wiadomości…</p>
      ) : query.isError ? (
        <p role="alert" className="text-sm text-destructive-muted-foreground">
          Nie udało się wczytać wiadomości: {apiErrorMessage(query.error, "błąd serwera")}.
        </p>
      ) : query.isSuccess && messages.length === 0 ? (
        <p className="text-sm text-muted-foreground">W czacie tej rekrutacji nie ma jeszcze wiadomości.</p>
      ) : (
        <ul className="space-y-2" aria-label="Ostatnie wiadomości czatu">
          {messages.map((message) => (
            <li key={message.id} className="text-[13px]">
              <span className="text-xs text-muted-foreground">
                {message.author?.name ?? "Nieznany autor"} · {moveWhen(message.created_at)}
              </span>
              <span className="block whitespace-pre-line text-foreground line-clamp-3">{message.content}</span>
            </li>
          ))}
        </ul>
      )}
      <button type="button" onClick={onOpenChat} className="text-xs font-medium text-primary hover:underline">
        {unreadCount > 0 ? `Otwórz czat (${unreadCount} nieprzeczytane)` : "Otwórz czat"}
      </button>
    </div>
  );
}

// ── „Praca w tle" (`GET /api/jobs/{id}/background-events`) ──────────────────

const BACKGROUND_DOT: Record<BackgroundEventTone, string> = {
  neutral: "bg-muted-foreground/50",
  skipped: "bg-warning",
  failed: "bg-destructive",
};

const BACKGROUND_TEXT: Record<BackgroundEventTone, string> = {
  neutral: "text-foreground",
  skipped: "text-warning-muted-foreground",
  failed: "text-destructive-muted-foreground",
};

const BACKGROUND_TONE_LABEL: Record<BackgroundEventTone, string | null> = {
  neutral: null,
  skipped: "Pominięto",
  failed: "Awaria",
};

/**
 * Zdarzenia automatów tej rekrutacji, od najnowszego. Serwer nie stronicuje —
 * „Pokaż więcej" podnosi `limit` (najwyżej 100). Z `limit` (zakładka
 * „Wszystko") sekcja renderuje się WYŁĄCZNIE, gdy coś się wydarzyło: pusty
 * stan, ładowanie i błąd mają swoją zakładkę i nie zabierają tu miejsca.
 */
function BackgroundSection({
  jobId,
  limit,
  onShowAll,
}: {
  jobId: number;
  limit?: number;
  onShowAll?: () => void;
}) {
  const [fetchLimit, setFetchLimit] = useState(BACKGROUND_EVENTS_STEP);
  const query = useQuery({
    queryKey: jobBackgroundEventsQueryKey(jobId, fetchLimit),
    queryFn: () => jobBackgroundEventsApi.list(jobId, fetchLimit),
    // Podniesienie limitu nie może na chwilę opróżnić listy.
    placeholderData: (previous) => previous,
    retry: false,
    staleTime: 30_000,
  });
  const all = query.data?.items ?? [];
  // 404 = backend sprzed automatów: nic się nie wydarzyło, nie „awaria".
  const unavailable = query.isError && httpStatusFromError(query.error) === 404;

  if (limit) {
    if (all.length === 0) return null;
    return (
      <section className="space-y-2.5">
        <SectionHeading>Praca w tle</SectionHeading>
        <BackgroundList events={all.slice(0, limit)} />
        {all.length > limit && onShowAll ? (
          <button type="button" onClick={onShowAll} className="text-xs font-medium text-primary hover:underline">
            Pokaż całą pracę w tle
          </button>
        ) : null}
      </section>
    );
  }

  if (query.isLoading) {
    return <p className="text-sm text-muted-foreground">Ładowanie pracy w tle…</p>;
  }
  if (query.isError && !unavailable) {
    return (
      <p role="alert" className="text-sm text-destructive-muted-foreground">
        Nie udało się wczytać pracy w tle: {apiErrorMessage(query.error, "błąd serwera")}.{" "}
        <button type="button" className="font-medium underline underline-offset-2" onClick={() => void query.refetch()}>
          Ponów
        </button>
      </p>
    );
  }
  if ((query.isSuccess && all.length === 0) || unavailable) {
    return (
      <EmptyState
        icon={Cog}
        title="Brak zdarzeń pracy w tle"
        description="Tu pojawią się zdarzenia automatów (przegląd bazy, nowe CV, wygenerowane CV)."
        className="py-8"
      />
    );
  }
  if (all.length === 0) return null;
  // Pełna strona = serwer może mieć więcej; sufit 100 kończy dokładanie.
  const canLoadMore = all.length >= fetchLimit && fetchLimit < BACKGROUND_EVENTS_MAX;
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Co automaty zrobiły w tej rekrutacji bez udziału człowieka — od najnowszego.
      </p>
      <BackgroundList events={all} />
      {canLoadMore ? (
        <Button
          variant="outline"
          size="sm"
          loading={query.isFetching}
          onClick={() => setFetchLimit((n) => Math.min(n + BACKGROUND_EVENTS_STEP, BACKGROUND_EVENTS_MAX))}
        >
          Pokaż więcej
        </Button>
      ) : null}
    </div>
  );
}

function BackgroundList({ events }: { events: readonly JobBackgroundEvent[] }) {
  return (
    <ul className="space-y-2.5" aria-label="Praca w tle">
      {events.map((event) => {
        const tone = backgroundEventTone(event);
        const toneLabel = BACKGROUND_TONE_LABEL[tone];
        return (
          <li key={event.id} className="flex gap-3 text-[13px]" data-tone={tone}>
            <span className="w-[92px] shrink-0 text-xs text-muted-foreground">{moveWhen(event.created_at)}</span>
            <span className={cn("mt-1 h-2.5 w-2.5 shrink-0 rounded-full", BACKGROUND_DOT[tone])} aria-hidden="true" />
            <span className={cn("min-w-0", BACKGROUND_TEXT[tone])}>
              {toneLabel ? <span className="font-semibold">{toneLabel}: </span> : null}
              {backgroundEventMessage(event)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Czat + odświeżenie odznaki po wyjściu.
 *
 * `JobChatTab` sam oznacza wiadomości jako przeczytane (przy montażu i przy
 * każdej nowej wiadomości), ale licznik strony żyje pod kluczem z `id` jako
 * napisem, a czat unieważnia klucz z liczbą. Unieważniamy więc cały prefiks
 * przy ODMONTOWANIU — wtedy `markRead` dawno doszedł, a odznaka w nagłówku
 * znika od razu po zamknięciu okna, nie dopiero przy najbliższym odpytaniu.
 */
function ChatSection({ jobId, readOnly }: { jobId: number; readOnly: boolean }) {
  const queryClient = useQueryClient();
  useEffect(
    () => () => {
      void queryClient.invalidateQueries({ queryKey: ["job-chat-unread"] });
    },
    [queryClient],
  );
  return <JobChatTab jobId={jobId} readOnly={readOnly} />;
}

export function HistoryChatSlideOver({
  open,
  onOpenChange,
  jobId,
  clientId,
  readOnly = false,
  initialTab = "all",
  chatUnreadCount = 0,
  columns,
}: HistoryChatSlideOverProps) {
  const [tab, setTab] = useState<HistoryChatTab>(initialTab);
  // Okno jest zamontowane cały czas, a stary link (`?tab=chat`) otwiera je
  // dopiero po chwili — sam inicjalizator `useState` by go nie zobaczył.
  // Korekta stanu W TRAKCIE renderu (nie w efekcie): efekt pokazałby na jedną
  // klatkę „Wszystko" i wysłał zapytania zakładki, której nikt nie chciał.
  const openKey = open ? initialTab : null;
  const [seenOpenKey, setSeenOpenKey] = useState(openKey);
  if (openKey !== seenOpenKey) {
    setSeenOpenKey(openKey);
    if (openKey) setTab(openKey);
  }

  const moves = columns ? latestMovesFromKanban(columns) : [];
  const columnsLoaded = columns !== undefined;

  const tabs = [
    { value: "all", label: "Wszystko" },
    {
      value: "chat",
      label: "Czat zespołu",
      count: chatUnreadCount > 0 ? chatUnreadCount : undefined,
    },
    { value: "moves", label: "Ruchy" },
    { value: "request", label: "Historia requestów" },
    { value: "background", label: "Praca w tle" },
  ];

  return (
    <RecruitmentSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Historia i czat"
      description="Rozmowa zespołu, ruchy osób, historia zlecenia i praca automatów w tej rekrutacji."
      descriptionHidden
      toolbar={
        <TabbedNav
          ariaLabel="Widok historii i czatu"
          value={tab}
          onValueChange={(value) => setTab(value as HistoryChatTab)}
          tabs={tabs}
          overflow="scroll"
          dense
        />
      }
      data-testid="history-chat-slideover"
    >
      {tab === "all" && (
        <div className="space-y-6">
          <section className="space-y-2.5">
            <SectionHeading>Ostatnie ruchy</SectionHeading>
            <MovesSection
              jobId={jobId}
              fallbackMoves={moves}
              columnsLoaded={columnsLoaded}
              limit={ALL_TAB_MOVES_LIMIT}
              onShowAll={() => setTab("moves")}
            />
          </section>

          {/* Praca w tle wchodzi do „Wszystko" dopiero, gdy coś się wydarzyło —
              pusty stan ma swoją zakładkę i nie zabiera tu miejsca czatowi. */}
          <BackgroundSection
            jobId={jobId}
            limit={ALL_TAB_BACKGROUND_LIMIT}
            onShowAll={() => setTab("background")}
          />

          <section className="space-y-2.5">
            <SectionHeading>Historia requestów</SectionHeading>
            <RequestHistorySection
              jobId={jobId}
              clientId={clientId}
              readOnly={readOnly}
              compact
              narrow
              maxItems={3}
            />
          </section>

          <section className="space-y-2.5">
            <SectionHeading>Czat zespołu</SectionHeading>
            <ChatPreview
              jobId={jobId}
              unreadCount={chatUnreadCount}
              onOpenChat={() => setTab("chat")}
            />
          </section>
        </div>
      )}

      {tab === "chat" && <ChatSection jobId={jobId} readOnly={readOnly} />}

      {tab === "moves" && (
        <MovesSection jobId={jobId} fallbackMoves={moves} columnsLoaded={columnsLoaded} />
      )}

      {tab === "request" && (
        <RequestHistorySection
          jobId={jobId}
          clientId={clientId}
          readOnly={readOnly}
        />
      )}

      {tab === "background" && <BackgroundSection jobId={jobId} />}
    </RecruitmentSheet>
  );
}
