"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { FormRow } from "@/components/ds/FormGroup";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CALL_OUTCOME_LABELS,
  useCreateActivity,
  useOwnerCandidates,
  useUpdateOpportunity,
  type CallOutcome,
  type Ref,
} from "@/lib/api/sales";

import { outcomePreset } from "./step";
import { SalesSelect } from "./SalesSelect";

/** Osoba do wyboru w zapisie rozmowy: z mapy decyzyjnej albo z kontaktów. */
export interface CallPerson {
  value: string;
  label: string;
  name: string;
  person_key?: string;
  contact_id?: number;
}

const WHEN: { label: string; days: number }[] = [
  { label: "Jutro", days: 1 },
  { label: "Za 3 dni", days: 3 },
  { label: "Za tydzień", days: 7 },
  { label: "Za 2 tygodnie", days: 14 },
  { label: "Za miesiąc", days: 30 },
];

const MORNING_HOUR = 9;
const FORM_ROW = "sm:grid-cols-[7rem_minmax(0,1fr)] sm:gap-3 sm:py-2";

function plusDays(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Termin z pola daty: rano tego dnia w czasie użytkownika. */
function dueAtMorning(isoDay: string): string {
  const [year, month, day] = isoDay.split("-").map(Number);
  return new Date(year, month - 1, day, MORNING_HOUR).toISOString();
}

interface NextStepDialogProps {
  opportunityId: number;
  /** `null`: krok planowany bez rozmowy, przycisk „Zaplanuj”. */
  outcome: Exclude<CallOutcome, "do_not_contact"> | null;
  personName: string | null;
  onClose: () => void;
}

/** „Co dalej i kiedy”: wynik rozmowy jest już zapisany, okno dotyczy tylko kroku. */
export function NextStepDialog({ opportunityId, outcome, personName, onClose }: NextStepDialogProps) {
  const preset = outcome ? outcomePreset(outcome) : { what: "Zadzwonić", days: 1 };
  const create = useCreateActivity();
  const { showError, showSuccess } = useToast();
  const [what, setWhat] = useState(preset.what);
  const [days, setDays] = useState<number | null>(preset.days);
  const [date, setDate] = useState(plusDays(preset.days));

  const saved = outcome ? [CALL_OUTCOME_LABELS[outcome], personName].filter(Boolean).join(", ") : null;

  const save = () => {
    // Przypisania nie wysyłamy: backend daje zadanie opiekunowi szansy.
    create.mutate(
      { kind: "task", opportunity_id: opportunityId, subject: what.trim(), due_at: dueAtMorning(date) },
      {
        onSuccess: () => {
          showSuccess("Zapisano następny krok.");
          onClose();
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać kroku.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => !next && onClose()}
      title="Co dalej i kiedy"
      description={saved ? `Zapisano: ${saved}` : "Następny krok przy tej szansie"}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {outcome ? "Bez kroku" : "Anuluj"}
          </Button>
          <Button disabled={!what.trim() || !date} loading={create.isPending} onClick={save}>
            Zapisz krok
          </Button>
        </>
      }
    >
      <FormRow label="Co trzeba zrobić" htmlFor="sales-next-what" className={FORM_ROW}>
        <Input id="sales-next-what" value={what} maxLength={500} onChange={(event) => setWhat(event.target.value)} />
      </FormRow>
      <FormRow label="Kiedy" htmlFor="sales-next-date" className={FORM_ROW}>
        <div className="flex flex-wrap gap-1.5">
          {WHEN.map((item) => (
            <Button
              key={item.label}
              size="sm"
              variant={days === item.days ? "primary" : "outline"}
              onClick={() => {
                setDays(item.days);
                setDate(plusDays(item.days));
              }}
            >
              {item.label}
            </Button>
          ))}
        </div>
        <Input
          id="sales-next-date"
          type="date"
          value={date}
          min={plusDays(0)}
          onChange={(event) => {
            setDays(null);
            setDate(event.target.value);
          }}
        />
      </FormRow>
    </AppModal>
  );
}

interface ChangeOwnerDialogProps {
  opportunityId: number;
  owner: Ref | null;
  onClose: () => void;
}

export function ChangeOwnerDialog({ opportunityId, owner, onClose }: ChangeOwnerDialogProps) {
  const update = useUpdateOpportunity(opportunityId);
  const { showError, showSuccess } = useToast();
  const candidates = useOwnerCandidates();
  const options = (candidates.data ?? []).map((person) => ({ value: String(person.id), label: person.name }));
  const current = owner ? String(owner.id) : "";
  // Obecny opiekun bywa już poza listą (konto nieaktywne): pole ma go nadal pokazać.
  const choices =
    owner && !options.some((option) => option.value === current)
      ? [{ value: current, label: owner.name }, ...options]
      : options;
  const hasOtherPerson = choices.some((option) => option.value !== current);
  const [value, setValue] = useState(current);

  const save = () => {
    update.mutate(
      { owner_user_id: Number(value) },
      {
        onSuccess: () => {
          showSuccess("Zmieniono opiekuna.");
          onClose();
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zmienić opiekuna.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => !next && onClose()}
      title="Zmień opiekuna"
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button disabled={!candidates.isSuccess || !value || value === current} loading={update.isPending} onClick={save}>
            Zapisz
          </Button>
        </>
      }
    >
      {candidates.isError ? (
        <div role="alert" className="flex items-center justify-between gap-3 text-sm text-destructive">
          <span>{apiErrorMessage(candidates.error, "Nie udało się wczytać listy osób.")}</span>
          <Button size="sm" variant="outline" onClick={() => void candidates.refetch()}>
            Spróbuj ponownie
          </Button>
        </div>
      ) : !candidates.isSuccess ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : hasOtherPerson ? (
        <SalesSelect ariaLabel="Nowy opiekun" value={value} onValueChange={setValue} options={choices} />
      ) : (
        <p className="text-sm text-muted-foreground">Nie ma innej osoby z prawem edycji Sprzedaży.</p>
      )}
    </AppModal>
  );
}
