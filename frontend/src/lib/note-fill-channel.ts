/**
 * Jedna notatka wypełnia formularz screeningu (D3, 14.10.2026).
 *
 * Pole notatki w doku osoby i formularz screeningu żyją w różnych gałęziach
 * drzewa panelu. Formularz pary, który może przyjąć notatkę (otwarty,
 * edytowalny, odczyt z notatki włączony), rejestruje tu odbiorcę; dok pyta,
 * czy odbiorca jest, i po zwykłym zapisie notatki przekazuje mu jej numer
 * i treść. Formularz czyta notatkę tą samą trasą co „Wklej tekst” i przy
 * „Zapisz” odsyła `note_import.note_id` — serwer nie zakłada drugiej notatki.
 */

import { useSyncExternalStore } from "react";

export interface SavedNoteForFill {
  noteId: number;
  text: string;
}

/** Odbiorca w formularzu; odrzucenie obietnicy = formularz nie przyjął notatki. */
export type NoteFillReceiver = (note: SavedNoteForFill) => Promise<void>;

export interface NoteFillChannel {
  /** Formularz osoby rejestruje odbiorcę; zwraca wyrejestrowanie. */
  register: (candidateId: number, receiver: NoteFillReceiver) => () => void;
  /** Czy formularz tej osoby czeka na notatkę. */
  has: (candidateId: number) => boolean;
  /** Dok: przekaż zapisaną notatkę. `false` = nikt jej nie przyjął. */
  send: (candidateId: number, note: SavedNoteForFill) => Promise<boolean>;
  subscribe: (listener: () => void) => () => void;
}

export function createNoteFillChannel(): NoteFillChannel {
  const receivers = new Map<number, NoteFillReceiver>();
  const listeners = new Set<() => void>();
  const emit = () => listeners.forEach((listener) => listener());

  return {
    register(candidateId, receiver) {
      receivers.set(candidateId, receiver);
      emit();
      return () => {
        // Drugi formularz tej samej osoby mógł się już zarejestrować — nie
        // zdejmuj cudzego odbiorcy.
        if (receivers.get(candidateId) === receiver) {
          receivers.delete(candidateId);
          emit();
        }
      };
    },
    has: (candidateId) => receivers.has(candidateId),
    async send(candidateId, note) {
      const receiver = receivers.get(candidateId);
      if (!receiver) return false;
      await receiver(note);
      return true;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

const noopSubscribe = () => () => undefined;

/** Dok: czy pokazać „Zapisz notatkę i wypełnij formularz”. */
export function useNoteFillAvailable(
  channel: NoteFillChannel | null | undefined,
  candidateId: number | null | undefined,
): boolean {
  return useSyncExternalStore(
    channel ? channel.subscribe : noopSubscribe,
    () => (channel != null && candidateId != null ? channel.has(candidateId) : false),
    () => false,
  );
}
