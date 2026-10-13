"use client";

/**
 * Zakładka „Notatki” (do 04.10.2026 „Historia”, do 13.10.2026 „Notatki
 * i historia”): jeden kompozytor notatki u góry, pod nim filtry w dwóch
 * grupach (E4, 13.10.2026):
 * - notatki po rodzaju — „Rozmowy · Delivery Lead · Próby kontaktu ·
 *   Automat” — z licznikami z serwera (decyzja 03.10: nic nie znika, szum ma
 *   własne miejsce); rodzaj bez notatek jest schowany (poza „Rozmowami”
 *   i wybranym). Domyślnie „Rozmowy” (klucz `notes`);
 * - inne źródła — „Maile” (skrzynka M365 i maile zapisane w notatkach)
 *   i „Czat zespołu”;
 * - przełącznik „Zmiany etapów i automaty” = oś czasu (klucz `timeline`,
 *   dawne „Wszystko”), ładowana dopiero tutaj, z „Pokaż więcej” do 200
 *   wpisów i „Pokaż CV obok”.
 *
 * Lista notatek ma grupy miesięczne, przypięte na górze i 10 najnowszych
 * z „Pokaż starsze”. Filtr „Telefony” (rejestr połączeń CloudTalk) zniknął
 * 13.10.2026 — stary adres `activity=calls` otwiera oś czasu.
 *
 * Czytnik maili (`EmailThreadList`) MUSI mieć tu wejście — raz już osierociał
 * (PR #539), a synchronizacja M365 zapisuje treści maili pod RODO.
 */

import * as React from "react";
import { useId, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, FileText, Loader2 } from "lucide-react";

import api, { extractErrorMsg } from "@/lib/api";
import { celebrate } from "@/lib/celebrate";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import EmailThreadList from "@/components/emails/EmailThreadList";
import CandidateChatTab from "@/components/v2/pages/CandidateChatTab";
import {
  FilePreviewContent,
  downloadDocumentBlob,
  type CandidateDocument,
} from "@/components/v2/files/FilePreviewModal";
import {
  candidateQueryKeys,
  candidateViewerScopeKey,
} from "@/components/v2/pages/candidate-query-keys";
import {
  useCandidateCardOverview,
  type CandidateCardNoteLink,
} from "@/lib/api/candidateCards";
import { noteLinksById } from "@/lib/candidate-card-facts";
import {
  NOTE_GROUP_BY_VIEW,
  NOTE_GROUP_EMPTY_TEXT,
  VIEW_BY_NOTE_GROUP,
  noteGroup,
  noteGroupCounts,
  notesOfGroup,
} from "@/lib/candidate-note-groups";
import { threadContainsNote } from "@/lib/candidate-notes-view";
import { useAuthStore } from "@/store/auth";
import type { CandidateActivityView } from "@/components/v2/pages/candidate-profile-navigation";
import type { PresenceViewer } from "@/hooks/usePresence";
import { cn } from "@/lib/utils";
import { NoteComposer, NotesList } from "./Notes";
import { TimelineTab } from "./Timeline";
import { SectionError, SectionLoading } from "./profile-shared";
import { useNoAnswer, useNoteActions } from "./useNoteActions";

// Okno „Screening” ciągnie formularz screeningu — ładuje się dopiero po
// kliknięciu przy notatce, żeby profil kandydata go nie nosił.
const ScreeningSummaryDialog = dynamic(
  () => import("@/components/v2/screening-form/ScreeningSummaryDialog").then((m) => m.ScreeningSummaryDialog),
  { ssr: false },
);

/* eslint-disable @typescript-eslint/no-explicit-any -- oś czasu i notatki są luźno typowane */

/** Grupa notatek po rodzaju — kolejność z makiety E4 (13.10.2026). */
const NOTE_FILTERS = ["notes", "delivery", "contact", "automat"] as const;
/** Inne źródła: skrzynka M365 (z mailami zapisanymi w notatkach) i czat zespołu. */
const SOURCE_FILTERS = ["emails", "chat"] as const;

export type ActivityFilter =
  | (typeof NOTE_FILTERS)[number]
  | (typeof SOURCE_FILTERS)[number];

export const ACTIVITY_FILTER_LABELS: Record<ActivityFilter, string> = {
  notes: "Rozmowy",
  delivery: "Delivery Lead",
  contact: "Próby kontaktu",
  automat: "Automat",
  emails: "Maile",
  chat: "Czat zespołu",
};

/** Przełącznik osi czasu (widok `timeline`, do 13.10.2026 filtr „Wszystko”). */
const TIMELINE_TOGGLE_LABEL = "Zmiany etapów i automaty";

/** Oś czasu: pierwsza porcja i sufit backendu (`/timeline?limit=` ≤ 200). */
const TIMELINE_FIRST_PAGE = 50;
const TIMELINE_MAX = 200;

/** Notatki: tyle najnowszych od razu, reszta za „Pokaż starsze”. */
const NOTES_FIRST_PAGE = 10;

/**
 * Filtry rodzajów notatek do pokazania: rodzaj bez żadnej notatki znika
 * (decyzja D1, 04.10.2026), chyba że jest wybrany albo liczby jeszcze nie
 * znamy. „Rozmowy” stoją zawsze.
 */
export function visibleActivityFilters(
  active: CandidateActivityView,
  counts: Partial<Record<CandidateActivityView, number>>,
): ActivityFilter[] {
  return NOTE_FILTERS.filter(
    (value) =>
      value === "notes" ||
      value === active ||
      counts[value] === undefined ||
      (counts[value] ?? 0) > 0,
  );
}

export interface HistoryTabProps {
  candidateId: number;
  candidate: {
    name?: string | null;
    lastname?: string | null;
    email?: string | null;
    cv_filename?: string | null;
  };
  activityView: CandidateActivityView;
  onActivityViewChange: (view: CandidateActivityView) => void;
  recruitments: any[];
  defaultJobId: number | null;
  readOnly: boolean;
  canModerate: boolean;
  currentUserId?: number;
  viewers: PresenceViewer[];
  setPresenceEditing: (field: string, active: boolean) => void;
  focusedNoteId: number | null;
  composeRequest: number;
  onComposeHandled: () => void;
}

export function HistoryTab({
  candidateId,
  candidate,
  activityView: requestedView,
  onActivityViewChange,
  recruitments,
  defaultJobId,
  readOnly,
  canModerate,
  currentUserId,
  viewers,
  setPresenceEditing,
  focusedNoteId,
  composeRequest,
  onComposeHandled,
}: HistoryTabProps) {
  // `calls` („Telefony”) to już tylko stary klucz z adresu — nawigacja
  // zamienia go na oś czasu; tu zabezpieczenie, gdyby dotarł.
  const activityView: CandidateActivityView =
    requestedView === "calls" ? "timeline" : requestedView;
  const { showError } = useToast();
  const queryClient = useQueryClient();
  const [noteText, setNoteText] = useState("");
  const [noteSaving, setNoteSaving] = useState(false);
  const { recordNoAnswer, saving: noAnswerSaving } = useNoAnswer(candidateId, readOnly);
  const [timelineLimit, setTimelineLimit] = useState(TIMELINE_FIRST_PAGE);
  const timelineQuery = useQuery<{ timeline?: any[] } | any[]>({
    queryKey: candidateQueryKeys.timeline(candidateId, timelineLimit),
    queryFn: ({ signal }) =>
      api
        .get(`/api/candidates/${candidateId}/timeline?limit=${timelineLimit}`, { signal })
        .then((r) => r.data),
    enabled: candidateId > 0 && activityView === "timeline",
    staleTime: 30_000,
    placeholderData: (previous) => previous,
  });
  const timelineItems: any[] = Array.isArray(timelineQuery.data)
    ? timelineQuery.data
    : (timelineQuery.data?.timeline ?? []);
  const timelineMayHaveMore =
    timelineItems.length >= timelineLimit && timelineLimit < TIMELINE_MAX;
  const [openCard, setOpenCard] = useState<CandidateCardNoteLink | null>(null);
  // „Pokaż CV obok” — domyślnie po wejściu z rekrutacji (widok z Traffita),
  // ale tylko od `lg`: węższy ekran stawia CV NAD historią, więc historia
  // byłaby dopiero pod całym podglądem CV.
  const [showCv, setShowCv] = useState(
    () =>
      defaultJobId != null &&
      typeof window !== "undefined" &&
      window.matchMedia?.("(min-width: 1024px)")?.matches === true,
  );

  // Notatki — dedykowane, NIEUCINANE źródło. Oś czasu miesza notatki
  // z etapami i ucina do limitu, więc starsze notatki znikały z filtra.
  // Ten sam klucz co licznik zakładki „Historia” w profilu (jedno pobranie).
  const notesQuery = useQuery<{ items?: any[]; group_counts?: Record<string, number> }>({
    queryKey: candidateQueryKeys.notes(candidateId),
    queryFn: ({ signal }) =>
      api
        .get(`/api/notes?candidate_id=${candidateId}`, { signal })
        .then((r) => r.data),
    enabled: candidateId > 0,
  });
  const noteItems = useMemo(
    () =>
      (notesQuery.data?.items ?? []).map((n: any) => ({
        ...n,
        type: "note",
        timestamp: n.created_at,
      })),
    [notesQuery.data],
  );

  const groupCounts = useMemo(
    () => noteGroupCounts(notesQuery.data?.group_counts, noteItems),
    [notesQuery.data, noteItems],
  );
  const activeGroup = NOTE_GROUP_BY_VIEW[activityView];
  // Link z powiadomienia (`?note=<id>`) prowadzi do zakładki „Rozmowy”; gdy
  // notatka leży w innej zakładce (np. próba kontaktu), dokładamy jej wątek.
  const groupNotes = useMemo(() => {
    if (!activeGroup) return [];
    const inGroup = notesOfGroup(noteItems, activeGroup);
    if (focusedNoteId == null) return inGroup;
    const focused = noteItems.find((n: any) => threadContainsNote(n, focusedNoteId));
    return focused && noteGroup(focused) !== activeGroup ? [focused, ...inGroup] : inGroup;
  }, [activeGroup, noteItems, focusedNoteId]);

  // Co z której notatki trafiło do karty rekomendacji (dodatek — awaria albo
  // brak sekcji nie zmienia listy notatek).
  const viewerScope = candidateViewerScopeKey(useAuthStore((state) => state.user));
  const cardOverview = useCandidateCardOverview(candidateId, viewerScope);
  const cardLinks = useMemo(
    () => noteLinksById(cardOverview.data?.note_links),
    [cardOverview.data],
  );

  const {
    invalidateNotes,
    editNote: handleEditNote,
    pinNote: handlePinNote,
    replyToNote: handleReplyNote,
    deleteNote: handleDeleteNote,
  } = useNoteActions(candidateId, readOnly);

  const handleAddNote = async (jobId?: number | null) => {
    if (readOnly || !noteText.trim()) return;
    setNoteSaving(true);
    try {
      // Bez trailing slash — backend rejestruje POST /api/notes; wariant
      // z "/" zwracał 404 i przycisk „nie działał”.
      await api.post("/api/notes", {
        candidate_id: candidateId,
        content: noteText.trim(),
        note_type: "general",
        ...(jobId ? { job_id: jobId } : {}),
      });
      setNoteText("");
      invalidateNotes();
      celebrate({ small: true, message: "Notatka dodana! 📝" });
    } catch (e) {
      showError(extractErrorMsg(e) || "Nie udało się dodać notatki");
    } finally {
      setNoteSaving(false);
    }
  };

  const noteCount = (group: keyof typeof VIEW_BY_NOTE_GROUP) =>
    notesQuery.isSuccess ? groupCounts[group] : undefined;
  const counts: Partial<Record<CandidateActivityView, number>> = {
    // Oś czasu bez liczby: pokazywała limit pobrania (50), nie liczbę zdarzeń.
    // Liczniki notatek liczy serwer dla całej historii (bez odpowiedzi).
    notes: noteCount("talks"),
    contact: noteCount("contact"),
    delivery: noteCount("delivery"),
    // „Maile” bez licznika: zakładka łączy skrzynkę M365 z mailami zapisanymi
    // w notatkach, a liczba samych notatek czytałaby się jak liczba maili.
    automat: noteCount("automat"),
  };
  const timelineOn = activityView === "timeline";
  const timelineToggleId = useId();

  const notesList = (emptyText: string) => (
    <NotesList
      notes={groupNotes}
      recruitments={recruitments}
      onEdit={handleEditNote}
      onDelete={handleDeleteNote}
      onPin={handlePinNote}
      onReply={handleReplyNote}
      currentUserId={currentUserId}
      canModerate={canModerate}
      readOnly={readOnly}
      focusedNoteId={focusedNoteId}
      emptyText={emptyText}
      includeSystem={activeGroup === "automat"}
      cardLinks={cardLinks}
      onOpenCard={setOpenCard}
      groupByMonth
      initialVisible={NOTES_FIRST_PAGE}
    />
  );

  const filterTab = (value: ActivityFilter) => {
    const active = value === activityView;
    const count = counts[value];
    return (
      <button
        key={value}
        type="button"
        role="tab"
        aria-selected={active}
        data-filter={value}
        onClick={() => onActivityViewChange(value)}
        className={cn(
          "inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
          active
            ? "bg-card text-foreground shadow-xs"
            : "text-muted-foreground hover:bg-accent hover:text-foreground",
        )}
      >
        {ACTIVITY_FILTER_LABELS[value]}
        {/* Spacja dla czytników ekranu: „Rozmowy · 4”, nie „Rozmowy· 4”. */}
        {typeof count === "number" ? " " : null}
        {typeof count === "number" ? (
          <span className="tabular-nums text-muted-foreground">· {count}</span>
        ) : null}
      </button>
    );
  };

  return (
    <div className="space-y-4">
      {!readOnly ? (
        <NoteComposer
          recruitments={recruitments}
          defaultJobId={defaultJobId}
          noteText={noteText}
          setNoteText={setNoteText}
          onAdd={handleAddNote}
          saving={noteSaving}
          onNoAnswer={recordNoAnswer}
          noAnswerSaving={noAnswerSaving}
          viewers={viewers}
          currentUserId={currentUserId}
          setEditing={setPresenceEditing}
          candidateName={candidate.name ?? null}
          candidateLastname={candidate.lastname ?? null}
          focusRequest={composeRequest}
          onFocusHandled={onComposeHandled}
        />
      ) : null}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {/* Przy włączonej osi czasu żaden filtr nie jest wybrany — klik
            w filtr wyłącza przełącznik. */}
        <div
          role="tablist"
          aria-label="Filtr notatek"
          className="flex max-w-full items-center gap-1 overflow-x-auto rounded-lg bg-muted p-1"
        >
          {visibleActivityFilters(activityView, counts).map(filterTab)}
          <span aria-hidden="true" className="mx-1 h-5 w-px shrink-0 bg-border" />
          {SOURCE_FILTERS.map(filterTab)}
        </div>
        <label
          htmlFor={timelineToggleId}
          className="inline-flex min-h-9 cursor-pointer items-center gap-2 text-xs font-medium text-muted-foreground"
        >
          <Switch
            id={timelineToggleId}
            checked={timelineOn}
            onCheckedChange={(on) => onActivityViewChange(on ? "timeline" : "notes")}
          />
          {TIMELINE_TOGGLE_LABEL}
        </label>
        {timelineOn && candidate.cv_filename ? (
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            aria-pressed={showCv}
            onClick={() => setShowCv((visible) => !visible)}
          >
            <FileText className="h-3.5 w-3.5" />
            {showCv ? "Ukryj CV" : "Pokaż CV obok"}
          </Button>
        ) : null}
      </div>

      {timelineOn ? (
        timelineQuery.isPending ? (
          <SectionLoading label="Ładowanie historii…" />
        ) : timelineQuery.error && timelineItems.length === 0 ? (
          <SectionError
            title="Nie udało się pobrać historii"
            onRetry={() => void timelineQuery.refetch()}
          />
        ) : (
          <>
            {showCv && candidate.cv_filename ? (
              <CvSidePane
                candidateId={candidateId}
                cvFilename={candidate.cv_filename}
              >
                <TimelineTab items={timelineItems} />
              </CvSidePane>
            ) : (
              <TimelineTab items={timelineItems} />
            )}
            {timelineMayHaveMore ? (
              <Button
                size="sm"
                variant="outline"
                loading={timelineQuery.isFetching}
                onClick={() =>
                  setTimelineLimit((limit) => Math.min(TIMELINE_MAX, limit * 2))
                }
              >
                Pokaż więcej
              </Button>
            ) : timelineItems.length >= TIMELINE_MAX ? (
              <p className="text-xs text-muted-foreground">
                Pokazujemy {TIMELINE_MAX} najnowszych zdarzeń. Starsze notatki
                zobaczysz po wyłączeniu przełącznika „{TIMELINE_TOGGLE_LABEL}”.
              </p>
            ) : null}
          </>
        )
      ) : null}

      {activeGroup && activityView !== "emails" ? (
        notesQuery.isPending ? (
          <SectionLoading label="Ładowanie notatek…" />
        ) : notesQuery.error ? (
          <SectionError
            title="Nie udało się pobrać notatek"
            onRetry={() => notesQuery.refetch()}
          />
        ) : (
          notesList(NOTE_GROUP_EMPTY_TEXT[activeGroup])
        )
      ) : null}

      {activityView === "emails" ? (
        <div className="space-y-4">
          <EmailThreadList
            candidateId={candidateId}
            candidateName={`${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim()}
            candidateEmail={candidate.email ?? null}
          />
          {/* Maile zapisane jako notatki (import z Traffita) — obok skrzynki M365. */}
          {notesQuery.error ? (
            <SectionError
              title="Nie udało się pobrać maili zapisanych w notatkach"
              onRetry={() => notesQuery.refetch()}
            />
          ) : groupNotes.length > 0 ? (
            <section aria-labelledby="history-email-notes-title" className="space-y-2">
              <h3
                id="history-email-notes-title"
                className="text-xs font-semibold text-foreground"
              >
                Maile zapisane w notatkach · {groupCounts.email}
              </h3>
              {notesList(NOTE_GROUP_EMPTY_TEXT.email)}
            </section>
          ) : null}
        </div>
      ) : null}

      {activityView === "chat" ? (
        <CandidateChatTab candidateId={candidateId} readOnly={readOnly} />
      ) : null}

      {openCard ? (
        <ScreeningSummaryDialog
          open
          onOpenChange={(open) => {
            if (open) return;
            setOpenCard(null);
            void queryClient.invalidateQueries({
              queryKey: candidateQueryKeys.cardOverviewRoot(candidateId),
            });
          }}
          candidateId={candidateId}
          jobId={openCard.job_id}
          jobTitle={openCard.job_title}
          candidateName={`${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim()}
          readOnly={readOnly}
        />
      ) : null}
    </div>
  );
}

/**
 * „Pokaż CV obok” — główne CV kandydata inline obok osi czasu (wzór ekranu
 * kandydata z Traffita). Awaria pobrania NIE udaje „brak CV”.
 */
function CvSidePane({
  candidateId,
  cvFilename,
  children,
}: {
  candidateId: number;
  cvFilename: string | null;
  children: React.ReactNode;
}) {
  const { showError } = useToast();
  const documentsQuery = useQuery<CandidateDocument[]>({
    queryKey: candidateQueryKeys.cvDocuments(candidateId),
    queryFn: async () => {
      const res = await api.get<CandidateDocument[]>(
        `/api/candidates/${candidateId}/documents?kind=cv`,
      );
      return res.data;
    },
    enabled: candidateId > 0,
    staleTime: 30_000,
  });
  const primaryDoc = useMemo<CandidateDocument | null>(() => {
    const docs = documentsQuery.data ?? [];
    return (
      docs.find((d) => d.is_primary) ??
      docs.find((d) => d.filename === cvFilename) ??
      docs[0] ??
      null
    );
  }, [documentsQuery.data, cvFilename]);

  const handleDownload = async (doc: CandidateDocument) => {
    try {
      await downloadDocumentBlob(candidateId, doc);
    } catch {
      showError("Nie udało się pobrać pliku.");
    }
  };

  return (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <div className="min-w-0 overflow-hidden rounded-lg border border-border bg-muted/30">
        {primaryDoc ? (
          <div className="flex h-[60dvh] flex-col lg:h-[78dvh]">
            <div className="flex items-center justify-between gap-2 border-b border-border bg-card px-3 py-2">
              <span className="min-w-0 truncate text-sm font-medium text-foreground">
                {primaryDoc.filename}
              </span>
              <button
                type="button"
                onClick={() => handleDownload(primaryDoc)}
                className="inline-flex shrink-0 items-center gap-1 text-sm text-primary hover:underline"
                title="Pobierz plik na dysk"
              >
                <Download className="h-3.5 w-3.5" />
                Pobierz
              </button>
            </div>
            <FilePreviewContent
              doc={primaryDoc}
              candidateId={candidateId}
              onDownload={handleDownload}
              hidePdfSidebar
              className="min-h-0 flex-1"
            />
          </div>
        ) : documentsQuery.isError ? (
          <div className="flex h-[40dvh] flex-col items-center justify-center gap-2 p-6 text-center">
            <AlertTriangle className="h-8 w-8 text-destructive" />
            <p className="text-sm text-destructive">
              Nie udało się wczytać dokumentów kandydata — nie wiemy, czy CV tu
              jest.
            </p>
            <button
              type="button"
              onClick={() => documentsQuery.refetch()}
              className="text-sm text-primary underline"
            >
              Ponów
            </button>
          </div>
        ) : !documentsQuery.isSuccess ? (
          <div className="flex h-[40dvh] flex-col items-center justify-center gap-2 p-6 text-center">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">Wczytywanie CV…</p>
          </div>
        ) : (
          <div className="flex h-[40dvh] flex-col items-center justify-center gap-2 p-6 text-center">
            <FileText className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              Brak CV w profilu kandydata.
            </p>
          </div>
        )}
      </div>
      <div className="min-w-0 lg:max-h-[78dvh] lg:overflow-y-auto lg:pr-1">{children}</div>
    </div>
  );
}
