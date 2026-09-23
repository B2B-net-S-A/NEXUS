"use client";

import { useQueryClient } from "@tanstack/react-query";

import { DebriefDialog } from "@/components/calendar/cycle/DebriefDialog";

/**
 * Bramka „telefon po rozmowie u klienta” na tablicy rekrutacji (pipeline v4,
 * decyzja Artura 23.09.2026). Serwer odmawia ruchu z „Rozmowy u klienta” na
 * „Umowę”/„Zatrudnionego” (409 `DEBRIEF_REQUIRED`), dopóki debrief najnowszej
 * odbytej rozmowy nie ma pytań klienta albo jawnego „klient nie zadawał
 * pytań”. To okno zbiera ten debrief; po zapisie `onSaved` ponawia ruch.
 *
 * Debrief zapisuje się pod wydarzeniem rozmowy (`eventId`); `jobId` służy
 * odświeżeniu tablicy (odznaka „Debrief ✓” na karcie) — oba klucze kanbana,
 * jak po każdym ruchu.
 */
export function DebriefRequiredDialog({
  open,
  onOpenChange,
  eventId,
  candidateName,
  jobId,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  eventId: number;
  candidateName: string;
  jobId: number;
  onSaved: () => void;
}) {
  const qc = useQueryClient();
  return (
    <DebriefDialog
      open={open}
      onOpenChange={onOpenChange}
      eventId={eventId}
      title="Telefon po rozmowie — pytania klienta"
      description={candidateName}
      submitLabel="Zapisz i przenieś dalej"
      onSaved={() => {
        qc.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
        qc.invalidateQueries({ queryKey: ["kanban", jobId] });
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
