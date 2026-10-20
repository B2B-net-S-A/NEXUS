"use client";

import { useQueryClient } from "@tanstack/react-query";

import { DebriefDialog } from "@/components/calendar/cycle/DebriefDialog";
import { invalidateAfterPipelineMove } from "@/lib/pipeline-move-invalidation";

/**
 * Bramka „telefon po rozmowie u klienta” na tablicy rekrutacji (pipeline v4,
 * decyzja Artura 23.09.2026). Serwer odmawia ruchu z „Rozmowy u klienta” na
 * „Umowę”/„Zatrudnionego” (409 `DEBRIEF_REQUIRED`), dopóki debrief najnowszej
 * odbytej rozmowy nie ma pytań klienta albo jawnego „klient nie zadawał
 * pytań”. To okno zbiera ten debrief; po zapisie `onSaved` ponawia ruch.
 *
 * Rozmowa ZAPLANOWANA też blokuje ruch (`interview_pending` w odmowie). Wtedy
 * okno (`DebriefDialog`, termin czyta z `GET …/events/{id}`) mówi, od kiedy
 * debrief będzie dostępny, i nie pozwala zapisać — debrief to zapis telefonu
 * po rozmowie, której jeszcze nie było.
 *
 * Debrief zapisuje się pod wydarzeniem rozmowy (`eventId`); `jobId` służy
 * odświeżeniu tablicy (odznaka „Debrief ✓” na karcie) i panelu osoby —
 * ta sama lista co po każdym ruchu (`invalidateAfterPipelineMove`).
 *
 * `eventId = null` (20.10.2026): para była w „Rozmowie z klientem”, ale
 * rozmowy nie ma w kalendarzu NEXUSA — okno pyta, kiedy była, i zapisuje
 * pytania pary (`candidateId`, `jobId`).
 */
export function DebriefRequiredDialog({
  open,
  onOpenChange,
  eventId,
  candidateId,
  candidateName,
  jobId,
  initialQuestions,
  submitLabel = "Zapisz i przenieś dalej",
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  eventId: number | null;
  candidateId: number;
  candidateName: string;
  jobId: number;
  /** Pytania dołożone przy otwarciu — podpowiedź z notatki. */
  initialQuestions?: string[];
  /** Panel osoby zapisuje bez ruchu karty — „Zapisz pytania”. */
  submitLabel?: string;
  onSaved: () => void;
}) {
  const qc = useQueryClient();
  return (
    <DebriefDialog
      open={open}
      onOpenChange={onOpenChange}
      eventId={eventId}
      pair={{ candidateId, jobId }}
      initialQuestions={initialQuestions}
      title={eventId == null ? "Pytania z rozmowy u klienta" : "Telefon po rozmowie — pytania klienta"}
      description={candidateName}
      submitLabel={submitLabel}
      onSaved={() => {
        invalidateAfterPipelineMove(qc, jobId);
        onSaved();
      }}
      intro={
        <p data-testid="debrief-required-intro">
          Zanim kandydat pójdzie dalej, zadzwoń do niego po rozmowie u klienta
          i zapisz, o co pytał klient. Te pytania trafią do prepu następnych
          kandydatów u tego klienta i do profilu Championa rekrutacji.
        </p>
      }
    />
  );
}
