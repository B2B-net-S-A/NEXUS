"use client";

/**
 * Okno „Historia i czat" — dawne zakładki `?tab=history` i `?tab=chat`
 * w jednym miejscu obok tabeli (makieta V3Historia).
 *
 * Czat i historia requestów to ISTNIEJĄCE komponenty, osadzone bez zmian:
 * przypinanie, reakcje, edycja i „przeczytane przez" czatu oraz bramkowanie
 * kwot fee w historii działają dokładnie jak w dawnych zakładkach.
 */

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { Cog } from "lucide-react";

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

/** Zdarzenie automatu (przegląd bazy, nowe CV, wygenerowane CV). */
export interface RecruitmentBackgroundEvent {
  /** Gotowa etykieta czasu („dziś 7:00", „19.09") — formatuje źródło. */
  when: string;
  label: string;
}

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
  /** Zdarzenia pracy w tle; brak = pusty stan z wyjaśnieniem. */
  backgroundEvents?: readonly RecruitmentBackgroundEvent[];
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

function BackgroundList({
  events,
}: {
  events: readonly RecruitmentBackgroundEvent[];
}) {
  if (events.length === 0) {
    return (
      <EmptyState
        icon={Cog}
        title="Brak zdarzeń pracy w tle"
        description="Tu pojawią się zdarzenia automatów (przegląd bazy, nowe CV, wygenerowane CV)."
        className="py-8"
      />
    );
  }
  return (
    <ul className="space-y-2.5" aria-label="Praca w tle">
      {events.map((event, index) => (
        <li key={`${event.when}-${index}`} className="flex gap-3 text-[13px]">
          <span className="w-[72px] shrink-0 text-muted-foreground">
            {event.when}
          </span>
          <span
            className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-muted-foreground/50"
            aria-hidden="true"
          />
          <span className="min-w-0 font-medium text-foreground">
            {event.label}
          </span>
        </li>
      ))}
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
  backgroundEvents = [],
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
    { value: "request", label: "Zmiany zlecenia" },
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
            <MovesList
              moves={moves.slice(0, ALL_TAB_MOVES_LIMIT)}
              columnsLoaded={columnsLoaded}
            />
            {moves.length > ALL_TAB_MOVES_LIMIT ? (
              <button
                type="button"
                onClick={() => setTab("moves")}
                className="text-xs font-medium text-primary hover:underline"
              >
                Pokaż wszystkie ruchy ({moves.length})
              </button>
            ) : null}
          </section>

          {/* Praca w tle wchodzi do „Wszystko" dopiero, gdy coś się wydarzyło —
              pusty stan ma swoją zakładkę i nie zabiera tu miejsca czatowi. */}
          {backgroundEvents.length > 0 ? (
            <section className="space-y-2.5">
              <SectionHeading>Praca w tle</SectionHeading>
              <BackgroundList
                events={backgroundEvents.slice(0, ALL_TAB_BACKGROUND_LIMIT)}
              />
            </section>
          ) : null}

          <section className="space-y-2.5">
            <SectionHeading>Zmiany zlecenia</SectionHeading>
            <RequestHistorySection
              jobId={jobId}
              clientId={clientId}
              readOnly={readOnly}
              compact
              maxItems={3}
            />
          </section>

          <section className="space-y-2.5">
            <SectionHeading>Czat zespołu</SectionHeading>
            <ChatSection jobId={jobId} readOnly={readOnly} />
          </section>
        </div>
      )}

      {tab === "chat" && <ChatSection jobId={jobId} readOnly={readOnly} />}

      {tab === "moves" && (
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Ostatni ruch każdej osoby — od najświeższego. Pełną historię etapów
            jednej osoby znajdziesz w jej panelu.
          </p>
          <MovesList moves={moves} columnsLoaded={columnsLoaded} />
        </div>
      )}

      {tab === "request" && (
        <RequestHistorySection
          jobId={jobId}
          clientId={clientId}
          readOnly={readOnly}
        />
      )}

      {tab === "background" && <BackgroundList events={backgroundEvents} />}
    </RecruitmentSheet>
  );
}
