"use client";

/**
 * Notatki kandydata: jeden kompozytor (u góry zakładki „Historia”) i lista
 * notatek z edycją/usuwaniem (filtr „Notatki”). Wydzielone z
 * `CandidateDetailV2.tsx`. Kompozytor jest JEDEN — wcześniej drugi żył
 * w widoku „CV obok”, a oba trzymały wspólny stan tekstu.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, PencilLine, Plus, Target, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { MentionTextarea } from "@/components/v2/forms/MentionTextarea";
import { ConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { detectNotePersonMismatch } from "@/lib/note-person-mismatch";
import { useMentionableUsers, type MentionScope } from "@/hooks/useMentionableUsers";
import { buildUsersByEmail, renderWithMentions } from "@/lib/renderMentions";
import type { PresenceViewer } from "@/hooks/usePresence";
import { noteTypeLabel } from "@/components/v2/pages/candidate-timeline-labels";
import { cn, formatRelativeTime } from "@/lib/utils";
import { unwrapNoteContent } from "./profile-shared";

/* eslint-disable @typescript-eslint/no-explicit-any -- notatki i rekrutacje przychodzą z luźno typowanych endpointów profilu */

export interface NoteComposerProps {
  recruitments?: any[];
  defaultJobId?: number | null;
  noteText: string;
  setNoteText: (v: string) => void;
  onAdd: (jobId?: number | null) => void;
  saving: boolean;
  viewers?: PresenceViewer[];
  currentUserId?: number;
  setEditing?: (field: string, active: boolean) => void;
  candidateName?: string | null;
  candidateLastname?: string | null;
  /** >0 = „Dodaj notatkę” z nagłówka: przewiń do pola i ustaw fokus. */
  focusRequest?: number;
  onFocusHandled?: () => void;
}

function useRecruitmentOptions(recruitments: any[] | undefined) {
  const recList = useMemo(
    () =>
      Array.isArray(recruitments)
        ? recruitments.filter((r: any) => r && r.job_id != null)
        : [],
    [recruitments],
  );
  const jobTitleById = useMemo(() => {
    const m = new Map<number, string>();
    for (const r of recList) {
      m.set(Number(r.job_id), r.job_title ?? `Rekrutacja #${r.job_id}`);
    }
    return m;
  }, [recList]);
  return { recList, jobTitleById };
}

/** Kompozytor notatki — selektor rekrutacji + pole z @wzmiankami. */
export function NoteComposer({
  recruitments = [],
  defaultJobId = null,
  noteText,
  setNoteText,
  onAdd,
  saving,
  viewers = [],
  currentUserId,
  setEditing,
  candidateName,
  candidateLastname,
  focusRequest = 0,
  onFocusHandled,
}: NoteComposerProps) {
  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    if (focusRequest <= 0) return;
    const textarea = composerTextareaRef.current;
    if (!textarea) return;
    textarea.scrollIntoView?.({ block: "center" });
    textarea.focus({ preventScroll: true });
    onFocusHandled?.();
  }, [focusRequest, onFocusHandled]);

  const { recList, jobTitleById } = useRecruitmentOptions(recruitments);

  // Wybrana rekrutacja (null = notatka ogólna). Gdy ustawiona, @mention scope
  // zawęża się do członków joba — spójnie z backendem.
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);

  // Profil otwarty z pipeline'u (`?from=job&jobId=N`): nowa notatka domyślnie
  // trafia do tej rekrutacji. Raz — nie nadpisujemy ręcznego wyboru.
  const defaultJobApplied = useRef(false);
  useEffect(() => {
    if (defaultJobApplied.current) return;
    if (defaultJobId == null) return;
    if (recList.length === 0) return;
    defaultJobApplied.current = true;
    if (recList.some((r: any) => Number(r.job_id) === Number(defaultJobId))) {
      setSelectedJobId(Number(defaultJobId));
    }
  }, [defaultJobId, recList]);

  const othersEditingNotes = viewers.filter(
    (v) => v.user_id !== currentUserId && v.editing.includes("notes"),
  );

  const mentionScope: MentionScope =
    selectedJobId != null
      ? { kind: "job", jobId: selectedJobId }
      : { kind: "global" };

  // Bezpiecznik: wklejka formularza z polem "Imię i nazwisko:" wskazującym
  // inną osobę niż otwarty profil (incydent 29.07.2026). Tylko ostrzeżenie —
  // notatka MOŻE świadomie dotyczyć osoby poleconej.
  const personMismatch = useMemo(
    () => detectNotePersonMismatch(noteText, candidateName, candidateLastname),
    [noteText, candidateName, candidateLastname],
  );

  return (
    <div className="space-y-2">
      <MentionTextarea
        value={noteText}
        onChange={setNoteText}
        scope={mentionScope}
        onFocus={() => setEditing?.("notes", true)}
        onBlur={() => setEditing?.("notes", false)}
        placeholder="Nowa notatka… (@email aby oznaczyć osobę)"
        rows={3}
        ariaLabel="Treść nowej notatki"
        textareaRef={composerTextareaRef}
      />
      {personMismatch ? (
        <div
          role="alert"
          className="flex items-start gap-1.5 rounded-lg border border-warning/40 bg-warning/10 px-2.5 py-2 text-xs text-warning-muted-foreground"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
          <span>
            Notatka wygląda na opis innej osoby („{personMismatch}”) niż otwarty
            profil. Upewnij się, że dodajesz ją na właściwym kandydacie.
          </span>
        </div>
      ) : null}
      {othersEditingNotes.length > 0 ? (
        <div className="flex items-center gap-1.5 text-xs text-warning-muted-foreground">
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-warning" />
          {othersEditingNotes.length === 1
            ? `${othersEditingNotes[0].name} edytuje notatki`
            : `${othersEditingNotes.map((v) => v.name).join(", ")} edytują notatki`}
        </div>
      ) : null}
      <div className="flex flex-wrap items-center justify-end gap-2">
        {recList.length > 0 ? (
          <div className="mr-auto flex min-w-0 items-center gap-1.5">
            <label
              htmlFor="note-recruitment-select"
              className="flex items-center gap-1.5 text-xs text-muted-foreground"
            >
              <Target className="h-3.5 w-3.5" />
              Rekrutacja:
            </label>
            <select
              id="note-recruitment-select"
              className="max-w-72 truncate rounded-lg border border-border bg-card px-2 py-1 text-xs"
              value={selectedJobId ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                setSelectedJobId(v ? Number(v) : null);
              }}
              aria-label="Przypisz notatkę do rekrutacji"
            >
              <option value="">Notatka ogólna (bez rekrutacji)</option>
              {recList.map((r: any) => (
                <option key={r.job_id} value={r.job_id}>
                  {jobTitleById.get(Number(r.job_id))}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <Button
          size="sm"
          variant="primary"
          onClick={() => onAdd(selectedJobId)}
          loading={saving}
          disabled={!noteText.trim()}
        >
          <Plus className="h-3.5 w-3.5" />
          Dodaj notatkę
        </Button>
      </div>
    </div>
  );
}

/** Lista notatek z edycją/usuwaniem (autor albo admin). Bez kompozytora. */
export function NotesList({
  notes: rawNotes,
  recruitments = [],
  onEdit,
  onDelete,
  currentUserId,
  canModerate = false,
  readOnly = false,
  focusedNoteId = null,
}: {
  notes: any[];
  recruitments?: any[];
  onEdit: (noteId: number, content: string) => Promise<boolean>;
  onDelete: (noteId: number) => Promise<boolean>;
  currentUserId?: number;
  canModerate?: boolean;
  readOnly?: boolean;
  focusedNoteId?: number | null;
}) {
  const notes = (Array.isArray(rawNotes) ? rawNotes : []).filter(
    (t: any) => t.type === "note",
  );
  // Link z powiadomienia o wzmiance (`?note=<id>`) przewija do notatki i ją
  // wyróżnia — raz na notatkę, żeby odświeżenie listy nie szarpało widokiem.
  const focusedNotePresent =
    focusedNoteId != null && notes.some((n: any) => Number(n.id) === focusedNoteId);
  const handledNoteFocusRef = useRef<number | null>(null);
  useEffect(() => {
    if (!focusedNotePresent || focusedNoteId == null) return;
    if (handledNoteFocusRef.current === focusedNoteId) return;
    const el = document.querySelector(`[data-note-id="${focusedNoteId}"]`);
    if (!(el instanceof HTMLElement)) return;
    handledNoteFocusRef.current = focusedNoteId;
    el.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [focusedNoteId, focusedNotePresent]);

  const { jobTitleById } = useRecruitmentOptions(recruitments);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  // Notatkę może zmienić jej autor albo admin (moderacja) — zgodne z
  // _can_modify_note na backendzie. author_id bywa null dla importów Traffit.
  const canModifyNote = (n: any): boolean =>
    !readOnly &&
    currentUserId != null &&
    (canModerate ||
      (n.author_id != null && Number(n.author_id) === Number(currentUserId)));

  // Render wzmianek w liście (zawsze global — lista miesza rekrutacje).
  const { data: users = [] } = useMentionableUsers({ kind: "global" });
  const usersByEmail = useMemo(() => buildUsersByEmail(users), [users]);

  const confirmDelete = async () => {
    const noteId = confirmDeleteId;
    if (noteId == null) return;
    setConfirmDeleteId(null);
    setBusyId(noteId);
    const ok = await onDelete(noteId);
    setBusyId(null);
    if (ok && editingId === noteId) {
      setEditingId(null);
      setEditText("");
    }
  };

  return (
    <div className="space-y-2">
      {notes.length === 0 ? (
        <div className="py-6 text-center text-sm text-muted-foreground">
          Brak notatek.
        </div>
      ) : (
        notes.map((n: any, i: number) => {
          const editable = canModifyNote(n);
          const isEditing = editingId != null && editingId === n.id;
          const isBusy = busyId != null && busyId === n.id;
          const jobTitle = n.job_title ?? jobTitleById.get(Number(n.job_id));
          return (
            <div
              key={n.id ?? i}
              data-note-id={n.id ?? undefined}
              className={cn(
                "rounded-lg border border-border bg-background/40 p-3",
                focusedNoteId != null &&
                  Number(n.id) === focusedNoteId &&
                  "border-primary ring-2 ring-primary/30",
              )}
            >
              <div className="flex flex-wrap items-baseline gap-2 text-xs text-muted-foreground">
                <span className="font-medium text-foreground">
                  {noteTypeLabel(n.note_type)
                    ? `Notatka — ${noteTypeLabel(n.note_type)}`
                    : "Notatka"}
                </span>
                {jobTitle ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                    <Target className="h-3 w-3" />
                    {jobTitle}
                  </span>
                ) : null}
                {n.author_name ? (
                  <>
                    <span>·</span>
                    <span title={n.author_email ?? undefined}>{n.author_name}</span>
                  </>
                ) : null}
                <span>·</span>
                <span>{n.timestamp ? formatRelativeTime(n.timestamp) : ""}</span>
                {editable && !isEditing ? (
                  <span className="ml-auto inline-flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => {
                        setEditingId(n.id);
                        setEditText(unwrapNoteContent(n.content));
                      }}
                      className="inline-flex items-center justify-center rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                      title="Edytuj notatkę"
                      aria-label="Edytuj notatkę"
                    >
                      <PencilLine className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmDeleteId(n.id)}
                      className="inline-flex items-center justify-center rounded-md p-1 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                      title="Usuń notatkę"
                      aria-label="Usuń notatkę"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </span>
                ) : null}
              </div>
              {isEditing ? (
                <div className="mt-2 space-y-2">
                  <MentionTextarea
                    value={editText}
                    onChange={setEditText}
                    scope={
                      n.job_id != null
                        ? { kind: "job", jobId: Number(n.job_id) }
                        : { kind: "global" }
                    }
                    placeholder="Treść notatki… (@email aby oznaczyć osobę)"
                    rows={3}
                    ariaLabel="Edytuj treść notatki"
                  />
                  <div className="flex items-center justify-end gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={isBusy}
                      onClick={() => {
                        setEditingId(null);
                        setEditText("");
                      }}
                    >
                      <X className="h-3.5 w-3.5" />
                      Anuluj
                    </Button>
                    <Button
                      size="sm"
                      variant="primary"
                      loading={isBusy}
                      disabled={!editText.trim() || isBusy}
                      onClick={async () => {
                        setBusyId(n.id);
                        const ok = await onEdit(n.id, editText.trim());
                        setBusyId(null);
                        if (ok) {
                          setEditingId(null);
                          setEditText("");
                        }
                      }}
                    >
                      Zapisz
                    </Button>
                  </div>
                </div>
              ) : (
                <p className="mt-1 whitespace-pre-line text-sm text-foreground">
                  {renderWithMentions(
                    unwrapNoteContent(n.content_rendered ?? n.content),
                    usersByEmail,
                  )}
                </p>
              )}
            </div>
          );
        })
      )}

      <ConfirmV2
        open={confirmDeleteId != null}
        onOpenChange={(open) => {
          if (!open) setConfirmDeleteId(null);
        }}
        variant="destructive"
        title="Usunąć notatkę?"
        description="Tej operacji nie można cofnąć. Notatka zostanie trwale usunięta."
        confirmLabel="Usuń"
        onConfirm={() => void confirmDelete()}
      />
    </div>
  );
}
