"use client";

/**
 * Pytania z rozmowy u klienta w panelu osoby, gdy rozmowy nie ma
 * w kalendarzu NEXUSA (20.10.2026).
 *
 * Sekcja „Rozmowa u klienta” (`DockInterviewCycle`) istnieje tylko przy
 * rozmowie albo wniosku o terminy — para przesunięta na „Rozmowa u klienta”
 * bez terminu nie miała w panelu nic, a pytania lądowały w notatkach (88 z 99
 * par w 30 dniach). Ten blok daje „Pytania z rozmowy” zawsze, a podpowiedź
 * pod notatką przenosi do tego okna pytania wpisane w notatkę.
 */

export function DockClientInterviewQuestions({
  readOnly,
  onOpen,
}: {
  readOnly: boolean;
  onOpen: () => void;
}) {
  return (
    <div
      data-testid="dock-client-interview-questions"
      className="space-y-2 rounded-md border border-warning/40 bg-warning-muted/40 px-3 py-2 text-xs"
    >
      <p className="font-semibold text-foreground">Rozmowa u klienta</p>
      <p className="text-muted-foreground">
        Rozmowy nie ma w kalendarzu NEXUSA. Po rozmowie zapisz, o co pytał klient — pytania
        trafią do prepu następnych kandydatów u tego klienta.
      </p>
      {readOnly ? null : (
        <button
          type="button"
          onClick={onOpen}
          className="h-8 rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
        >
          Pytania z rozmowy
        </button>
      )}
    </div>
  );
}

export function ClientQuestionsNoteHint({
  count,
  onSave,
  onDismiss,
}: {
  /** Ile pytań udało się wyjąć z notatki (0 = okno startuje z pustą listą). */
  count: number;
  onSave: () => void;
  onDismiss: () => void;
}) {
  return (
    <div
      role="status"
      data-testid="client-questions-note-hint"
      className="mx-3 mb-2 space-y-2 rounded-md border border-info/40 bg-info-muted px-3 py-2 text-xs text-info-muted-foreground"
    >
      <p className="font-semibold">To wygląda na pytania klienta</p>
      <p>
        Zapisz je jako pytania z rozmowy
        {count > 0 ? ` (${count})` : ""} — trafią do prepu kolejnych kandydatów u tego klienta.
        Notatka zostaje.
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onSave}
          className="h-8 rounded-md bg-primary px-3 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
        >
          Zapisz jako pytania z rozmowy
        </button>
        <button
          type="button"
          onClick={onDismiss}
          className="h-8 rounded-md border border-border bg-card px-3 text-xs font-semibold text-foreground hover:bg-muted"
        >
          Tylko notatka
        </button>
      </div>
    </div>
  );
}
