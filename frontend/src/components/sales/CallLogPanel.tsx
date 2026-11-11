"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { CALL_OUTCOME_LABELS, useLogCall, type CallOutcome } from "@/lib/api/sales";

import type { CallPerson } from "./CallLogDialogs";
import { SalesSelect } from "./SalesSelect";
import { outcomePreset } from "./step";

const dayHint = (days: number): string =>
  days === 1 ? "jutro" : days === 7 ? "za tydzień" : days === 30 ? "za miesiąc" : `za ${days} dni`;

const OUTCOMES: Exclude<CallOutcome, "do_not_contact">[] = [
  "connected",
  "no_answer",
  "call_back",
  "wants_offer",
  "not_now",
];

interface CallLogPanelProps {
  opportunityId: number;
  people: readonly CallPerson[];
  initialPerson: string;
  onSaved: (outcome: CallOutcome, person: CallPerson | null) => void;
  onClose: () => void;
}

/** Rozwinięty zapis rozmowy pod paskiem kroku: kliknięcie wyniku zapisuje go od razu. */
export function CallLogPanel({ opportunityId, people, initialPerson, onSaved, onClose }: CallLogPanelProps) {
  const log = useLogCall();
  const { showError } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [value, setValue] = useState(initialPerson);
  const [note, setNote] = useState("");
  const person = people.find((item) => item.value === value) ?? null;

  const save = (outcome: CallOutcome) => {
    log.mutate(
      {
        opportunity_id: opportunityId,
        outcome,
        person_key: person?.person_key,
        contact_id: person?.contact_id,
        note: note.trim() || undefined,
      },
      {
        onSuccess: () => onSaved(outcome, person),
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać rozmowy.")),
      },
    );
  };

  const object = async () => {
    if (!person) return;
    const ok = await askConfirm({
      title: "Nie kontaktować",
      description: `${person.name} nie życzy sobie kontaktu. Sprzeciw zapiszemy przy tej osobie, a jej numer przestanie być klikalny.`,
      confirmLabel: "Zapisz sprzeciw",
      variant: "destructive",
    });
    if (ok) save("do_not_contact");
  };

  return (
    <Card className="space-y-2 p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-foreground">Zapis rozmowy</h2>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Zwiń
        </Button>
      </div>
      <div className="grid gap-2 sm:grid-cols-[23rem_minmax(0,1fr)]">
        <SalesSelect
          ariaLabel="Z kim była rozmowa"
          value={value}
          onValueChange={setValue}
          options={people.map(({ value: option, label }) => ({ value: option, label }))}
          anyLabel="Bez wskazania osoby"
        />
        <Input
          aria-label="Notatka z rozmowy"
          placeholder="Co ustaliliście? (opcjonalnie)"
          value={note}
          maxLength={5000}
          onChange={(event) => setNote(event.target.value)}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {OUTCOMES.map((outcome) => (
          <Button
            key={outcome}
            size="sm"
            variant="outline"
            className="h-auto flex-col items-start gap-0 py-1"
            aria-label={CALL_OUTCOME_LABELS[outcome]}
            disabled={log.isPending}
            onClick={() => save(outcome)}
          >
            <span>{CALL_OUTCOME_LABELS[outcome]}</span>
            {/* Decyzja Artura 11.11.2026: krok z podpowiedzi zapisuje się razem z wynikiem, bez okna „Co dalej”. */}
            <span className="text-[10px] font-normal text-muted-foreground">
              {`${outcomePreset(outcome).what.toLowerCase()}, ${dayHint(outcomePreset(outcome).days)}`}
            </span>
          </Button>
        ))}
        <Button
          size="sm"
          variant="outline"
          className="ml-auto text-destructive hover:bg-destructive/10 hover:text-destructive"
          disabled={!person || log.isPending}
          title={person ? undefined : "Wybierz osobę, której dotyczy sprzeciw"}
          onClick={() => void object()}
        >
          {CALL_OUTCOME_LABELS.do_not_contact}
        </Button>
      </div>
      {confirmDialog}
    </Card>
  );
}
