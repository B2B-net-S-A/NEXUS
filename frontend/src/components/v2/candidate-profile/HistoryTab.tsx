"use client";

/**
 * Zakładka „Historia”: jeden kompozytor notatki u góry i filtry
 * „Wszystko · Notatki · Maile · Rozmowy · Czat zespołu”. Każdy filtr to
 * dotychczasowy komponent (oś czasu, lista notatek, czytnik maili M365,
 * rozmowy CloudTalk, czat zespołu) — zmieniło się tylko miejsce.
 *
 * Czytnik maili (`EmailThreadList`) MUSI mieć tu wejście — raz już osierociał
 * (PR #539), a synchronizacja M365 zapisuje treści maili pod RODO.
 */

import * as React from "react";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, FileText, Loader2 } from "lucide-react";

import api, { callsApi, extractErrorMsg, type Call } from "@/lib/api";
import { celebrate } from "@/lib/celebrate";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import EmailThreadList from "@/components/emails/EmailThreadList";
import CallsTimeline from "@/components/calls/CallsTimeline";
import CandidateChatTab from "@/components/v2/pages/CandidateChatTab";
import {
  FilePreviewContent,
  downloadDocumentBlob,
  type CandidateDocument,
} from "@/components/v2/files/FilePreviewModal";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import type { CandidateActivityView } from "@/components/v2/pages/candidate-profile-navigation";
import type { PresenceViewer } from "@/hooks/usePresence";
import { cn } from "@/lib/utils";
import { NoteComposer, NotesList } from "./Notes";
import { TimelineTab } from "./Timeline";
import { SectionError, SectionLoading } from "./profile-shared";

/* eslint-disable @typescript-eslint/no-explicit-any -- oś czasu i notatki są luźno typowane */

export const ACTIVITY_FILTER_LABELS: Record<CandidateActivityView, string> = {
  timeline: "Wszystko",
  notes: "Notatki",
  emails: "Maile",
  calls: "Rozmowy",
  chat: "Czat zespołu",
};

const FILTER_ORDER: CandidateActivityView[] = [
  "timeline",
  "notes",
  "emails",
  "calls",
  "chat",
];

export interface HistoryTimelineState {
  items: any[];
  isPending: boolean;
  error: unknown;
  refetch: () => void;
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
  timeline: HistoryTimelineState;
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
  activityView,
  onActivityViewChange,
  timeline,
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
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const [noteText, setNoteText] = useState("");
  const [noteSaving, setNoteSaving] = useState(false);
  // „Pokaż CV obok” — domyślnie po wejściu z rekrutacji (widok z Traffita).
  const [showCv, setShowCv] = useState(defaultJobId != null);

  // Notatki — dedykowane, NIEUCINANE źródło. Oś czasu miesza notatki
  // z etapami i ucina do limitu, więc starsze notatki znikały z filtra.
  const notesQuery = useQuery<{ items?: any[] }>({
    queryKey: candidateQueryKeys.notes(candidateId),
    queryFn: ({ signal }) =>
      api
        .get(`/api/notes?candidate_id=${candidateId}`, { signal })
        .then((r) => r.data),
    enabled: candidateId > 0 && activityView === "notes",
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

  const callsQuery = useQuery<Call[]>({
    queryKey: candidateQueryKeys.calls(candidateId),
    queryFn: () => callsApi.getForCandidate(candidateId),
    enabled: candidateId > 0 && activityView === "calls",
  });

  const invalidateNotes = () => {
    queryClient.invalidateQueries({
      queryKey: candidateQueryKeys.timelineRoot(candidateId),
    });
    queryClient.invalidateQueries({
      queryKey: candidateQueryKeys.notes(candidateId),
    });
  };

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

  // PATCH re-parsuje @wzmianki; wynik bool — lista wychodzi z edycji po sukcesie.
  const handleEditNote = async (noteId: number, content: string) => {
    if (readOnly) return false;
    try {
      await api.patch(`/api/notes/${noteId}`, { content });
      invalidateNotes();
      return true;
    } catch (e) {
      showError(extractErrorMsg(e) || "Nie udało się zapisać notatki");
      return false;
    }
  };

  // Backend kaskaduje NoteMention; 403 gdy nie autor i nie admin.
  const handleDeleteNote = async (noteId: number) => {
    if (readOnly) return false;
    try {
      await api.delete(`/api/notes/${noteId}`);
      invalidateNotes();
      return true;
    } catch (e) {
      showError(extractErrorMsg(e) || "Nie udało się usunąć notatki");
      return false;
    }
  };

  const counts: Partial<Record<CandidateActivityView, number>> = {
    timeline: timeline.isPending ? undefined : timeline.items.length,
    notes: notesQuery.isSuccess ? noteItems.length : undefined,
    calls: callsQuery.isSuccess ? (callsQuery.data ?? []).length : undefined,
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
          viewers={viewers}
          currentUserId={currentUserId}
          setEditing={setPresenceEditing}
          candidateName={candidate.name ?? null}
          candidateLastname={candidate.lastname ?? null}
          focusRequest={composeRequest}
          onFocusHandled={onComposeHandled}
        />
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <div
          role="tablist"
          aria-label="Filtr historii"
          className="flex max-w-full gap-1 overflow-x-auto rounded-lg bg-muted p-1"
        >
          {FILTER_ORDER.map((value) => {
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
                {typeof count === "number" ? (
                  <span className="tabular-nums text-muted-foreground">
                    {count}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
        {activityView === "timeline" && candidate.cv_filename ? (
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

      {activityView === "timeline" ? (
        timeline.isPending ? (
          <SectionLoading label="Ładowanie historii…" />
        ) : timeline.error && timeline.items.length === 0 ? (
          <SectionError
            title="Nie udało się pobrać historii"
            onRetry={timeline.refetch}
          />
        ) : showCv && candidate.cv_filename ? (
          <CvSidePane
            candidateId={candidateId}
            cvFilename={candidate.cv_filename}
          >
            <TimelineTab items={timeline.items} />
          </CvSidePane>
        ) : (
          <TimelineTab items={timeline.items} />
        )
      ) : null}

      {activityView === "notes" ? (
        notesQuery.isPending ? (
          <SectionLoading label="Ładowanie notatek…" />
        ) : notesQuery.error ? (
          <SectionError
            title="Nie udało się pobrać notatek"
            onRetry={() => notesQuery.refetch()}
          />
        ) : (
          <NotesList
            notes={noteItems}
            recruitments={recruitments}
            onEdit={handleEditNote}
            onDelete={handleDeleteNote}
            currentUserId={currentUserId}
            canModerate={canModerate}
            readOnly={readOnly}
            focusedNoteId={focusedNoteId}
          />
        )
      ) : null}

      {activityView === "emails" ? (
        <EmailThreadList
          candidateId={candidateId}
          candidateName={`${candidate.name ?? ""} ${candidate.lastname ?? ""}`.trim()}
          candidateEmail={candidate.email ?? null}
        />
      ) : null}

      {activityView === "calls" ? (
        callsQuery.error ? (
          <SectionError
            title="Nie udało się pobrać rozmów"
            onRetry={() => callsQuery.refetch()}
          />
        ) : callsQuery.isPending ? (
          <SectionLoading label="Ładowanie rozmów…" />
        ) : (
          <CallsTimeline calls={callsQuery.data ?? []} />
        )
      ) : null}

      {activityView === "chat" ? (
        <CandidateChatTab candidateId={candidateId} readOnly={readOnly} />
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
          <div className="flex h-[78vh] flex-col">
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
          <div className="flex h-[40vh] flex-col items-center justify-center gap-2 p-6 text-center">
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
          <div className="flex h-[40vh] flex-col items-center justify-center gap-2 p-6 text-center">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">Wczytywanie CV…</p>
          </div>
        ) : (
          <div className="flex h-[40vh] flex-col items-center justify-center gap-2 p-6 text-center">
            <FileText className="h-8 w-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              Brak CV w profilu kandydata.
            </p>
          </div>
        )}
      </div>
      <div className="max-h-[78vh] min-w-0 overflow-y-auto pr-1">{children}</div>
    </div>
  );
}
