"use client";

/**
 * Notatki kandydata w JEDNEJ rekrutacji (dok osoby na Tablicy, panel osoby,
 * warsztaty kroków) — ta sama lista co w zakładce „Historia” profilu:
 * odpowiedzi pod notatką, przypięte pierwsze, notatki automatów schowane za
 * „Pokaż systemowe (N)”. Do 29.09.2026 trzy ekrany rekrutacji miały własne,
 * uproszczone listy bez odpowiedzi.
 *
 * Wołający trzyma zapytanie (`GET /api/notes?candidate_id=&job_id=`), stan
 * ładowania i awarii — tu trafia wyłącznie udany odczyt.
 */

import { useMemo } from "react";

import { useAuthStore, hasRole } from "@/store/auth";
import { NotesList } from "./Notes";
import { useNoteActions } from "./useNoteActions";

/* eslint-disable @typescript-eslint/no-explicit-any -- notatki z luźno typowanego endpointu */

export function JobNotesList({
  candidateId,
  notes,
  readOnly,
  emptyText = "Brak notatek dla tej rekrutacji.",
}: {
  candidateId: number;
  /** `items` z `GET /api/notes` (notatki główne z `replies`). */
  notes: readonly any[];
  readOnly: boolean;
  emptyText?: string;
}) {
  const currentUser = useAuthStore((s) => s.user);
  const { editNote, pinNote, replyToNote, deleteNote } = useNoteActions(
    candidateId,
    readOnly,
  );
  const items = useMemo(
    () => notes.map((n: any) => ({ ...n, type: "note", timestamp: n.created_at })),
    [notes],
  );
  return (
    <NotesList
      notes={items}
      onEdit={editNote}
      onDelete={deleteNote}
      onPin={pinNote}
      onReply={replyToNote}
      currentUserId={currentUser?.id}
      canModerate={hasRole(currentUser, "admin")}
      readOnly={readOnly}
      emptyText={emptyText}
      hideRecruitment
    />
  );
}
