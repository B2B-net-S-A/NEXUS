"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { useSetHandoffTerm, type Handoff } from "@/lib/api/sales-handoffs";

import { SalesSelect } from "../SalesSelect";
import { DURATIONS, fieldsFromTerm, handoffWhen, termFromFields } from "./helpers";
import { HostCalendar } from "./HostCalendar";

const DURATION_OPTIONS = DURATIONS.map((minutes) => ({ value: String(minutes), label: `${minutes} min` }));

/** Ustawienie albo zmiana terminu przekazanego spotkania, z kalendarzem prowadzącego. */
export function TermPanel({ handoff, onDone }: { handoff: Handoff; onDone: () => void }) {
  const save = useSetHandoffTerm();
  const { showError, showSuccess } = useToast();
  const [term, setTerm] = useState(() => fieldsFromTerm(handoff.meeting_at));
  const [minutes, setMinutes] = useState(handoff.duration_minutes);
  const start = termFromFields(term.day, term.time);

  // Po zapisie panel bywa już odmontowany (spotkanie zmienia fazę), stąd `mutateAsync`.
  const submit = async () => {
    if (!start) return;
    try {
      await save.mutateAsync({ opportunity_id: handoff.opportunity.id, meeting_at: start, duration_minutes: minutes });
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać terminu."));
      return;
    }
    showSuccess(`Termin: ${handoffWhen(start)}.`);
    onDone();
  };

  return (
    <div className="space-y-2" data-testid="term-panel">
      <h3 className="text-sm font-semibold text-foreground">
        {handoff.meeting_at ? "Zmień termin" : "Ustaw termin"}
      </h3>
      <div className="grid grid-cols-[minmax(0,1fr)_6.5rem_6.5rem] gap-2">
        <Input
          aria-label="Dzień spotkania"
          type="date"
          className="h-8 text-xs"
          value={term.day}
          onChange={(event) => setTerm((current) => ({ ...current, day: event.target.value }))}
        />
        <Input
          aria-label="Godzina spotkania"
          type="time"
          step={900}
          className="h-8 text-xs"
          value={term.time}
          onChange={(event) => setTerm((current) => ({ ...current, time: event.target.value }))}
        />
        <SalesSelect
          ariaLabel="Czas trwania"
          className="h-8 text-xs"
          value={String(minutes)}
          onValueChange={(value) => setMinutes(Number(value))}
          options={DURATION_OPTIONS}
        />
      </div>
      <HostCalendar
        hostId={handoff.host?.id ?? null}
        hostName={handoff.host?.name ?? "prowadzący"}
        day={term.day}
        time={term.time}
        minutes={minutes}
        onPickTime={(time) => setTerm((current) => ({ ...current, time }))}
      />
      <div className="flex justify-end gap-1">
        <Button size="sm" variant="ghost" onClick={onDone}>
          Anuluj
        </Button>
        <Button size="sm" disabled={!start} loading={save.isPending} onClick={() => void submit()}>
          Zapisz termin
        </Button>
      </div>
    </div>
  );
}
