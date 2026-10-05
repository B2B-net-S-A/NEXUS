"use client";

/**
 * Notatki kandydata: jeden kompozytor (u góry zakładki „Historia”) i lista
 * notatek z edycją/usuwaniem (filtr „Notatki”). Wydzielone z
 * `CandidateDetailV2.tsx`. Kompozytor jest JEDEN — wcześniej drugi żył
 * w widoku „CV obok”, a oba trzymały wspólny stan tekstu.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ClipboardList,
  PencilLine,
  PhoneMissed,
  Pin,
  PinOff,
  Plus,
  Reply,
  Target,
  Trash2,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { MentionTextarea } from "@/components/v2/forms/MentionTextarea";
import { ConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import type { CandidateCardNoteLink } from "@/lib/api/candidateCards";
import { noteLinkSummary } from "@/lib/candidate-card-facts";
import { detectNotePersonMismatch } from "@/lib/note-person-mismatch";
import { useMentionableUsers, type MentionScope } from "@/hooks/useMentionableUsers";
import { buildUsersByEmail, renderWithMentions } from "@/lib/renderMentions";
import type { PresenceViewer } from "@/hooks/usePresence";
import { noteTypeLabel } from "@/components/v2/pages/candidate-timeline-labels";
import { cn, formatRelativeTime } from "@/lib/utils";
import {
  collapsedNotePreview,
  isLongNote,
  noteDateLabel,
  noteRecruitmentOptions,
  parseRecruitmentFilter,
  systemNoteCount,
  threadContainsNote,
  visibleNotes,
  type NoteRecruitmentFilter,
} from "@/lib/candidate-notes-view";
import { unwrapNoteContent } from "./profile-shared";

/* eslint-disable @typescript-eslint/no-explicit-any -- notatki i rekrutacje przychodzą z luźno typowanych endpointów profilu */

export interface NoteComposerProps {
  recruitments?: any[];
  defaultJobId?: number | null;
  noteText: string;
  setNoteText: (v: string) => void;
  onAdd: (jobId?: number | null) => void;
  saving: boolean;
  /**
   * „Nie odebrał” — jednym kliknięciem zapisuje próbę kontaktu (osobna
   * zakładka Historii; nie liczy się jako rozmowa). Brak = bez przycisku.
   */
  onNoAnswer?: (jobId?: number | null) => void;
  noAnswerSaving?: boolean;
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
  onNoAnswer,
  noAnswerSaving = false,
  viewers = [],
  currentUserId,
  setEditing,
  candidateName,
  candidateLastname,
  focusRequest = 0,
  onFocusHandled,
}: NoteComposerProps) {
  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  // 04.10.2026: pole zwinięte do jednej linii, dopóki ktoś do niego nie wejdzie
  // — trzy puste linie i rząd przycisków zabierały połowę ekranu historii.
  const [expanded, setExpanded] = useState(false);
  const open = expanded || noteText.trim().length > 0;
  useEffect(() => {
    if (focusRequest <= 0) return;
    setExpanded(true);
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
        onFocus={() => {
          setExpanded(true);
          setEditing?.("notes", true);
        }}
        onBlur={() => setEditing?.("notes", false)}
        placeholder="Nowa notatka… (@email aby oznaczyć osobę)"
        rows={open ? 3 : 1}
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
      {open ? (
      <div className="flex flex-wrap items-center justify-end gap-2" data-testid="note-composer-actions">
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
        {onNoAnswer ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => onNoAnswer(selectedJobId)}
            loading={noAnswerSaving}
            disabled={saving}
            title="Zapisuje próbę kontaktu jednym kliknięciem — trafia do zakładki „Próby kontaktu”"
          >
            <PhoneMissed className="h-3.5 w-3.5" />
            Nie odebrał
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="primary"
          onClick={() => onAdd(selectedJobId)}
          loading={saving}
          disabled={!noteText.trim() || noAnswerSaving}
        >
          <Plus className="h-3.5 w-3.5" />
          Dodaj notatkę
        </Button>
        {!noteText.trim() ? (
          <Button size="sm" variant="ghost" onClick={() => setExpanded(false)}>
            Zwiń
          </Button>
        ) : null}
      </div>
      ) : null}
    </div>
  );
}

/**
 * Lista notatek (29.09.2026): zwarte karty „autor · data · rekrutacja”,
 * długa treść zwinięta, filtr rekrutacji, notatki automatów schowane za
 * „Pokaż systemowe”, przypięcie wspólne dla zespołu i odpowiedzi (jeden
 * poziom). Reguły listy: `lib/candidate-notes-view.ts`.
 */
export function NotesList({
  notes: rawNotes,
  recruitments = [],
  onEdit,
  onDelete,
  onPin,
  onReply,
  currentUserId,
  canModerate = false,
  readOnly = false,
  focusedNoteId = null,
  now,
  emptyText = "Brak notatek.",
  hideRecruitment = false,
  includeSystem = false,
  cardLinks,
  onOpenCard,
}: {
  notes: any[];
  recruitments?: any[];
  onEdit: (noteId: number, content: string) => Promise<boolean>;
  onDelete: (noteId: number) => Promise<boolean>;
  /** Przypnij/odepnij (wspólnie dla zespołu). Brak = bez przycisku. */
  onPin?: (noteId: number, pinned: boolean) => Promise<boolean>;
  /** Odpowiedź na notatkę główną. Brak = bez przycisku „Odpowiedz”. */
  onReply?: (parentId: number, content: string) => Promise<boolean>;
  currentUserId?: number;
  canModerate?: boolean;
  readOnly?: boolean;
  focusedNoteId?: number | null;
  /** Wstrzykiwany zegar (harness, testy). */
  now?: Date;
  /** Pusty stan, gdy kandydat nie ma żadnej notatki w tym zakresie. */
  emptyText?: string;
  /** Lista jednej rekrutacji (dok osoby): bez filtra i plakietki rekrutacji. */
  hideRecruitment?: boolean;
  /** Zakładka „Automat”: wpisy systemowe widoczne od razu, bez przełącznika. */
  includeSystem?: boolean;
  /** Co z której notatki trafiło do karty rekomendacji (profil kandydata). */
  cardLinks?: ReadonlyMap<number, CandidateCardNoteLink>;
  onOpenCard?: (link: CandidateCardNoteLink) => void;
}) {
  const notes = useMemo(
    () =>
      (Array.isArray(rawNotes) ? rawNotes : []).filter(
        (t: any) => t.type === "note" && t.parent_note_id == null,
      ),
    [rawNotes],
  );
  const { jobTitleById } = useRecruitmentOptions(recruitments);

  const [systemToggled, setShowSystem] = useState(false);
  const showSystem = includeSystem || systemToggled;
  const [recruitmentFilter, setRecruitmentFilter] =
    useState<NoteRecruitmentFilter>("all");
  const systemCount = systemNoteCount(notes);
  const options = useMemo(
    () =>
      noteRecruitmentOptions(notes, { showSystem }, (id) => jobTitleById.get(id)),
    [notes, showSystem, jobTitleById],
  );
  // Wybrana rekrutacja zniknęła z listy (np. po usunięciu notatki) → wszystkie.
  const effectiveFilter: NoteRecruitmentFilter = options.some(
    (o) => o.value === recruitmentFilter,
  )
    ? recruitmentFilter
    : "all";
  const shown = useMemo(
    () => visibleNotes(notes, { recruitment: effectiveFilter, showSystem }),
    [notes, effectiveFilter, showSystem],
  );

  // Link z powiadomienia (`?note=<id>`) — także odpowiedzi: pokaż jej wątek,
  // nawet gdy leży za filtrem albo jest notatką systemową.
  const focusedThread =
    focusedNoteId != null
      ? notes.find((n: any) => threadContainsNote(n, focusedNoteId))
      : undefined;
  const focusedHidden =
    focusedThread != null && !shown.some((n: any) => n.id === focusedThread.id);
  const listed = focusedHidden ? [focusedThread, ...shown] : shown;
  const handledNoteFocusRef = useRef<number | null>(null);
  useEffect(() => {
    if (focusedThread == null || focusedNoteId == null) return;
    if (handledNoteFocusRef.current === focusedNoteId) return;
    const el = document.querySelector(`[data-note-id="${focusedNoteId}"]`);
    if (!(el instanceof HTMLElement)) return;
    handledNoteFocusRef.current = focusedNoteId;
    el.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [focusedNoteId, focusedThread]);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set());
  const [replyTo, setReplyTo] = useState<number | null>(null);
  const [replyText, setReplyText] = useState("");

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
  const clock = now ?? new Date();

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

  const toggleExpanded = (id: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const renderBody = (n: any) => {
    const text = unwrapNoteContent(n.content_rendered ?? n.content);
    const long = isLongNote(text);
    const open = expanded.has(Number(n.id)) || Number(n.id) === focusedNoteId;
    // Zwinięta: pierwsze linie Z TEKSTEM (bez pustych akapitów z Traffita),
    // inaczej podgląd bywał samym wierszem wzmianek i „…”.
    const shownText = long && !open ? collapsedNotePreview(text) : text;
    return (
      <>
        <p
          className={cn(
            "mt-1 whitespace-pre-line break-words text-sm text-foreground",
            long && !open && "line-clamp-4",
          )}
        >
          {renderWithMentions(shownText, usersByEmail)}
        </p>
        {long ? (
          <button
            type="button"
            onClick={() => toggleExpanded(Number(n.id))}
            aria-expanded={open}
            className="mt-0.5 text-xs font-medium text-primary hover:underline"
          >
            {open ? "Pokaż mniej" : "Pokaż więcej"}
          </button>
        ) : null}
      </>
    );
  };

  const renderEditor = (n: any) => {
    const isBusy = busyId != null && busyId === n.id;
    return (
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
    );
  };

  const renderCardLink = (n: any) => {
    const link = cardLinks?.get(Number(n.id));
    if (!link) return null;
    const summary = noteLinkSummary(link);
    return (
      <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
        <ClipboardList className="h-3.5 w-3.5 shrink-0" aria-hidden />
        {summary ? <span>{summary}.</span> : null}
        {onOpenCard ? (
          <button
            type="button"
            onClick={() => onOpenCard(link)}
            className="font-medium text-primary hover:underline"
          >
            Karta rekomendacji z tej rozmowy
          </button>
        ) : null}
      </p>
    );
  };

  const iconButton =
    "inline-flex items-center justify-center rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground hit-area";

  const renderActions = (n: any, { isReply }: { isReply: boolean }) => {
    const editable = canModifyNote(n);
    const pinned = n.pinned_at != null;
    return (
      <span className="ml-auto inline-flex shrink-0 items-center gap-0.5">
        {!isReply && !n.is_system && onPin && !readOnly ? (
          <button
            type="button"
            onClick={async () => {
              setBusyId(n.id);
              await onPin(n.id, !pinned);
              setBusyId(null);
            }}
            disabled={busyId === n.id}
            className={cn(iconButton, pinned && "text-primary")}
            title={pinned ? "Odepnij notatkę (dla całego zespołu)" : "Przypnij notatkę (dla całego zespołu)"}
            aria-label={pinned ? "Odepnij notatkę" : "Przypnij notatkę"}
            aria-pressed={pinned}
          >
            {pinned ? <PinOff className="h-3.5 w-3.5" /> : <Pin className="h-3.5 w-3.5" />}
          </button>
        ) : null}
        {!isReply && !n.is_system && onReply && !readOnly ? (
          <button
            type="button"
            onClick={() => {
              setReplyTo(replyTo === n.id ? null : n.id);
              setReplyText("");
            }}
            className={iconButton}
            title="Odpowiedz na notatkę"
            aria-label="Odpowiedz na notatkę"
          >
            <Reply className="h-3.5 w-3.5" />
          </button>
        ) : null}
        {editable ? (
          <>
            <button
              type="button"
              onClick={() => {
                setEditingId(n.id);
                setEditText(unwrapNoteContent(n.content));
              }}
              className={iconButton}
              title={isReply ? "Edytuj odpowiedź" : "Edytuj notatkę"}
              aria-label={isReply ? "Edytuj odpowiedź" : "Edytuj notatkę"}
            >
              <PencilLine className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setConfirmDeleteId(n.id)}
              className={cn(iconButton, "hover:bg-destructive/10 hover:text-destructive")}
              title={isReply ? "Usuń odpowiedź" : "Usuń notatkę"}
              aria-label={isReply ? "Usuń odpowiedź" : "Usuń notatkę"}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </>
        ) : null}
      </span>
    );
  };

  const metaLine = (n: any, jobTitle?: string | null) => (
    <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">
      <span className="font-medium text-foreground">
        {n.author_name ?? (n.is_system ? "System" : "Import z Traffita")}
      </span>
      <span aria-hidden="true">·</span>
      <time dateTime={n.created_at ?? n.timestamp ?? undefined} className="tabular-nums">
        {noteDateLabel(n.created_at ?? n.timestamp, clock, formatRelativeTime)}
      </time>
      {jobTitle ? (
        <span className="inline-flex max-w-56 items-center gap-1 truncate rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
          <Target className="h-3 w-3 shrink-0" />
          <span className="truncate">{jobTitle}</span>
        </span>
      ) : null}
      {noteTypeLabel(n.note_type) ? (
        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[11px]">
          {noteTypeLabel(n.note_type)}
        </span>
      ) : null}
      {n.is_system ? (
        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[11px]">
          systemowa
        </span>
      ) : null}
    </span>
  );

  return (
    <div className="space-y-2">
      {notes.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {options.length > 2 && !hideRecruitment ? (
            <label className="flex min-w-0 items-center gap-1.5 text-muted-foreground">
              <Target className="h-3.5 w-3.5 shrink-0" />
              <span className="sr-only">Filtr rekrutacji</span>
              <select
                className="max-w-72 truncate rounded-lg border border-border bg-card px-2 py-1 text-xs text-foreground"
                value={String(effectiveFilter)}
                onChange={(e) => setRecruitmentFilter(parseRecruitmentFilter(e.target.value))}
                aria-label="Pokaż notatki z rekrutacji"
              >
                {options.map((o) => (
                  <option key={String(o.value)} value={String(o.value)}>
                    {o.label} ({o.count})
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {systemCount > 0 && !includeSystem ? (
            <label className="ml-auto inline-flex cursor-pointer items-center gap-1.5 text-muted-foreground">
              <input
                type="checkbox"
                className="h-3.5 w-3.5 rounded border-border"
                checked={showSystem}
                onChange={(e) => setShowSystem(e.target.checked)}
              />
              Pokaż systemowe ({systemCount})
            </label>
          ) : null}
        </div>
      ) : null}

      {listed.length === 0 ? (
        <div className="py-6 text-center text-sm text-muted-foreground">
          {notes.length === 0 ? emptyText : "Brak notatek dla wybranych filtrów."}
        </div>
      ) : (
        listed.map((n: any, i: number) => {
          const isEditing = editingId != null && editingId === n.id;
          const jobTitle = hideRecruitment
            ? null
            : n.job_title ?? jobTitleById.get(Number(n.job_id));
          const replies: any[] = Array.isArray(n.replies) ? n.replies : [];
          const pinned = n.pinned_at != null;
          return (
            <article
              key={n.id ?? i}
              data-note-id={n.id ?? undefined}
              aria-label={pinned ? "Przypięta notatka" : "Notatka"}
              className={cn(
                "rounded-lg border border-border bg-background/40 px-3 py-2",
                pinned && "border-primary/40 bg-primary/5",
                n.is_system && "opacity-80",
                focusedNoteId != null &&
                  Number(n.id) === focusedNoteId &&
                  "border-primary ring-2 ring-primary/30",
              )}
            >
              <div className="flex items-start gap-2 text-xs text-muted-foreground">
                {pinned ? (
                  <Pin
                    className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary"
                    aria-label={
                      n.pinned_by_name ? `Przypięta przez: ${n.pinned_by_name}` : "Przypięta"
                    }
                  />
                ) : null}
                {metaLine(n, jobTitle)}
                {!isEditing ? renderActions(n, { isReply: false }) : null}
              </div>
              {isEditing ? renderEditor(n) : renderBody(n)}
              {!isEditing ? renderCardLink(n) : null}

              {replies.length > 0 || replyTo === n.id ? (
                <div className="mt-2 space-y-1.5 border-l-2 border-border pl-3">
                  {replies.map((r: any) => {
                    const replyEditing = editingId != null && editingId === r.id;
                    return (
                      <div
                        key={r.id}
                        data-note-id={r.id}
                        className={cn(
                          "rounded-md",
                          focusedNoteId != null &&
                            Number(r.id) === focusedNoteId &&
                            "ring-2 ring-primary/30",
                        )}
                      >
                        <div className="flex items-start gap-2 text-xs text-muted-foreground">
                          {metaLine(r)}
                          {!replyEditing ? renderActions(r, { isReply: true }) : null}
                        </div>
                        {replyEditing ? renderEditor(r) : renderBody(r)}
                      </div>
                    );
                  })}
                  {replyTo === n.id ? (
                    <div className="space-y-1.5">
                      <MentionTextarea
                        value={replyText}
                        onChange={setReplyText}
                        scope={
                          n.job_id != null
                            ? { kind: "job", jobId: Number(n.job_id) }
                            : { kind: "global" }
                        }
                        placeholder="Odpowiedź… (@email aby oznaczyć osobę)"
                        rows={2}
                        ariaLabel="Treść odpowiedzi"
                      />
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setReplyTo(null);
                            setReplyText("");
                          }}
                        >
                          Anuluj
                        </Button>
                        <Button
                          size="sm"
                          variant="primary"
                          loading={busyId === n.id}
                          disabled={!replyText.trim() || busyId === n.id}
                          onClick={async () => {
                            if (!onReply) return;
                            setBusyId(n.id);
                            const ok = await onReply(n.id, replyText.trim());
                            setBusyId(null);
                            if (ok) {
                              setReplyTo(null);
                              setReplyText("");
                            }
                          }}
                        >
                          <Reply className="h-3.5 w-3.5" />
                          Odpowiedz
                        </Button>
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </article>
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
        description="Tej operacji nie można cofnąć. Notatka zostanie trwale usunięta razem z odpowiedziami."
        confirmLabel="Usuń"
        onConfirm={() => void confirmDelete()}
      />
    </div>
  );
}
