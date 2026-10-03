"use client";

/**
 * Akcje na notatkach kandydata (edycja, przypięcie, odpowiedź, usunięcie) —
 * wspólne dla zakładki „Historia” profilu i list notatek w rekrutacji, żeby
 * notatka zachowywała się tak samo wszędzie, gdzie ją widać.
 *
 * Każda akcja zwraca `true` po sukcesie (lista wychodzi wtedy z edycji
 * i czyści pole odpowiedzi); błąd = toast po polsku i `false`.
 */

import { useQueryClient } from "@tanstack/react-query";

import api, { extractErrorMsg } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";

export function useNoteActions(candidateId: number, readOnly: boolean) {
  const queryClient = useQueryClient();
  const { showError } = useToast();

  // Prefiks klucza notatek łapie też listy jednej rekrutacji
  // (`[...notes(candidateId), jobId]`) i przypięte (`pinned_only`).
  const invalidateNotes = () => {
    queryClient.invalidateQueries({
      queryKey: candidateQueryKeys.timelineRoot(candidateId),
    });
    queryClient.invalidateQueries({
      queryKey: candidateQueryKeys.notes(candidateId),
    });
    // Notatka-karta zmienia kartę rekomendacji, a z nią ustalenia w profilu.
    queryClient.invalidateQueries({
      queryKey: candidateQueryKeys.cardOverviewRoot(candidateId),
    });
  };

  // PATCH re-parsuje @wzmianki.
  const editNote = async (noteId: number, content: string) => {
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

  // Przypięcie jest wspólne dla zespołu (0399) — każdy z prawem zapisu notatek.
  const pinNote = async (noteId: number, pinned: boolean) => {
    if (readOnly) return false;
    try {
      if (pinned) await api.post(`/api/notes/${noteId}/pin`);
      else await api.delete(`/api/notes/${noteId}/pin`);
      invalidateNotes();
      return true;
    } catch (e) {
      showError(
        extractErrorMsg(e) ||
          (pinned ? "Nie udało się przypiąć notatki" : "Nie udało się odpiąć notatki"),
      );
      return false;
    }
  };

  // Odpowiedź dziedziczy kandydata i rekrutację notatki głównej (serwer).
  const replyToNote = async (parentId: number, content: string) => {
    if (readOnly) return false;
    try {
      await api.post("/api/notes", {
        parent_note_id: parentId,
        content,
        note_type: "general",
      });
      invalidateNotes();
      return true;
    } catch (e) {
      showError(extractErrorMsg(e) || "Nie udało się dodać odpowiedzi");
      return false;
    }
  };

  // Backend kaskaduje NoteMention i odpowiedzi; 403 gdy nie autor i nie admin.
  const deleteNote = async (noteId: number) => {
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

  return { invalidateNotes, editNote, pinNote, replyToNote, deleteNote };
}
