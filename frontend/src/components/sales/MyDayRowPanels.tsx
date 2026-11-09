"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CALL_OUTCOME_LABELS,
  useCompleteActivity,
  useCreateActivity,
  useCreateSalesContact,
  useLogCall,
  useLogCompanyCall,
  useUpdateActivity,
  useUpdateSalesContact,
  type CallOutcome,
  type MyDayRow,
} from "@/lib/api/sales";

import { dueAtMorning, plusDays } from "./CallLogDialogs";
import { personLabel } from "./my-day";
import { SalesSelect } from "./SalesSelect";
import { outcomePreset } from "./step";

const OUTCOMES: Exclude<CallOutcome, "do_not_contact">[] = [
  "connected",
  "no_answer",
  "call_back",
  "wants_offer",
  "not_now",
];

const WHEN = [
  { value: "1", label: "Jutro" },
  { value: "3", label: "Za 3 dni" },
  { value: "7", label: "Za tydzień" },
] as const;
type When = (typeof WHEN)[number]["value"];

const NEW_PERSON = "new";
const PANEL = "space-y-2 border-t border-border bg-muted/30 px-3 py-2 text-xs";
const MIN_PHONE_DIGITS = 7;

function SaveButtons({
  canSave,
  label = "Zapisz",
  pending,
  onSave,
  onCancel,
}: {
  canSave: boolean;
  label?: string;
  pending: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="ml-auto flex gap-1">
      <Button size="sm" variant="ghost" onClick={onCancel}>
        Anuluj
      </Button>
      <Button size="sm" disabled={!canSave} loading={pending} onClick={onSave}>
        {label}
      </Button>
    </div>
  );
}

function StepFields({
  what,
  when,
  onWhat,
  onWhen,
}: {
  what: string;
  when: When | null;
  onWhat: (value: string) => void;
  onWhen: (value: When) => void;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
      <Input
        className="h-8 min-w-40 flex-1 text-xs"
        placeholder="Co dalej, np. wysłać umowę"
        aria-label="Co dalej"
        value={what}
        maxLength={500}
        onChange={(event) => onWhat(event.target.value)}
      />
      <SegmentedRadio size="sm" label="Kiedy" options={WHEN} value={when} onChange={onWhen} />
    </div>
  );
}

/** Krok do zaplanowania: przy zaległym przekładamy to samo zadanie, nie dokładamy drugiego. */
export function PlanPanel({ row, onDone }: { row: MyDayRow; onDone: () => void }) {
  const reschedule = row.section === "overdue" && row.activity_id !== null;
  const create = useCreateActivity();
  const update = useUpdateActivity(row.activity_id ?? 0);
  const { showError, showSuccess } = useToast();
  const [what, setWhat] = useState(reschedule ? (row.subject ?? "") : "");
  const [when, setWhen] = useState<When | null>("3");
  const pending = create.isPending || update.isPending;

  const callbacks = {
    onSuccess: () => {
      showSuccess("Zapisano następny krok.");
      onDone();
    },
    onError: (error: unknown) => showError(apiErrorMessage(error, "Nie udało się zapisać kroku.")),
  };
  const save = () => {
    if (!when) return;
    const due_at = dueAtMorning(plusDays(Number(when)));
    const subject = what.trim();
    if (reschedule) update.mutate({ subject, due_at }, callbacks);
    else {
      create.mutate(
        {
          kind: "task",
          subject,
          due_at,
          opportunity_id: row.opportunity?.id ?? null,
          company_id: row.opportunity ? null : row.company.id,
        },
        callbacks,
      );
    }
  };
  return (
    <div className={PANEL}>
      <p className="font-medium text-foreground">Co dalej i kiedy</p>
      <div className="flex flex-wrap items-center gap-2">
        <StepFields what={what} when={when} onWhat={setWhat} onWhen={setWhen} />
        <SaveButtons canSave={what.trim() !== "" && when !== null} pending={pending} onSave={save} onCancel={onDone} />
      </div>
    </div>
  );
}

/** Zapis rozmowy w wierszu: wynik, potem krok; zaległe zadanie zamyka się razem z rozmową. */
export function CallPanel({ row, onDone }: { row: MyDayRow; onDone: () => void }) {
  const logOpportunity = useLogCall();
  const logCompany = useLogCompanyCall();
  const createStep = useCreateActivity();
  const complete = useCompleteActivity();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [outcome, setOutcome] = useState<CallOutcome | null>(null);
  const [what, setWhat] = useState("");
  const [when, setWhen] = useState<When | null>("3");
  const contactId = row.person?.id;
  const isPending = logOpportunity.isPending || logCompany.isPending || createStep.isPending;

  const choose = (next: Exclude<CallOutcome, "do_not_contact">) => {
    const preset = outcomePreset(next);
    setOutcome(next);
    setWhat(preset.what);
    setWhen(next === "not_now" ? null : "3");
  };

  const afterLog = () => {
    if (row.section === "overdue" && row.activity_id !== null) {
      complete.mutate(
        { id: row.activity_id },
        { onError: (error) => showError(apiErrorMessage(error, "Rozmowa zapisana, ale zadanie zostało otwarte.")) },
      );
    }
  };

  const saveStep = () => {
    if (!when || !what.trim()) {
      showSuccess("Zapisano rozmowę.");
      onDone();
      return;
    }
    createStep.mutate(
      {
        kind: "task",
        subject: what.trim(),
        due_at: dueAtMorning(plusDays(Number(when))),
        opportunity_id: row.opportunity?.id ?? null,
        company_id: row.opportunity ? null : row.company.id,
      },
      {
        onSuccess: () => {
          showSuccess("Zapisano rozmowę i następny krok.");
          onDone();
        },
        // Rozmowa już jest w historii: panel się zamyka, żeby drugi zapis jej nie zdublował.
        onError: (error) => {
          showError(apiErrorMessage(error, "Rozmowa zapisana, ale kroku nie udało się zapisać."));
          onDone();
        },
      },
    );
  };

  const log = (value: CallOutcome, then: () => void) => {
    const callbacks = {
      onSuccess: () => {
        afterLog();
        then();
      },
      onError: (error: unknown) => showError(apiErrorMessage(error, "Nie udało się zapisać rozmowy.")),
    };
    if (row.opportunity) {
      logOpportunity.mutate(
        { opportunity_id: row.opportunity.id, outcome: value, contact_id: contactId },
        callbacks,
      );
    } else {
      logCompany.mutate({ company_id: row.company.id, outcome: value, contact_id: contactId }, callbacks);
    }
  };

  const object = async () => {
    if (!row.person) return;
    const ok = await askConfirm({
      title: "Nie kontaktować",
      description: `${row.person.name} nie życzy sobie kontaktu. Sprzeciw zapiszemy przy tej osobie, a jej numer przestanie być klikalny.`,
      confirmLabel: "Zapisz sprzeciw",
      variant: "destructive",
    });
    if (!ok) return;
    log("do_not_contact", () => {
      showSuccess("Zapisano sprzeciw.");
      onDone();
    });
  };

  const save = () => {
    if (!outcome) return;
    log(outcome, saveStep);
  };

  return (
    <div className={PANEL}>
      <div className="flex flex-wrap gap-1" role="group" aria-label="Wynik rozmowy">
        {OUTCOMES.map((option) => (
          <Button
            key={option}
            size="sm"
            className="h-7 px-1.5"
            variant={outcome === option ? "primary" : "outline"}
            aria-pressed={outcome === option}
            onClick={() => choose(option)}
          >
            {CALL_OUTCOME_LABELS[option]}
          </Button>
        ))}
        <Button
          size="sm"
          variant="outline"
          className="ml-auto h-7 px-1.5 text-destructive hover:bg-destructive/10 hover:text-destructive"
          disabled={!row.person || isPending}
          onClick={() => void object()}
        >
          {CALL_OUTCOME_LABELS.do_not_contact}
        </Button>
      </div>
      <p className="font-medium text-foreground">Co dalej i kiedy</p>
      <div className="flex flex-wrap items-center gap-2">
        <StepFields what={what} when={when} onWhat={setWhat} onWhen={setWhen} />
        <SaveButtons canSave={outcome !== null} pending={isPending} onSave={save} onCancel={onDone} />
      </div>
      {confirmDialog}
    </div>
  );
}

/** Numer leży przy osobie, więc panel najpierw mówi, czyj to numer. Sprzeciw odcina osobę z listy. */
export function PhonePanel({ row, onDone }: { row: MyDayRow; onDone: () => void }) {
  const known = row.people_without_phone;
  const [person, setPerson] = useState(known[0] ? String(known[0].id) : NEW_PERSON);
  const [name, setName] = useState("");
  const [number, setNumber] = useState("");
  const isNew = person === NEW_PERSON;
  const update = useUpdateSalesContact(isNew ? 0 : Number(person));
  const create = useCreateSalesContact();
  const { showError, showSuccess } = useToast();
  const options = [
    ...known.map((item) => ({ value: String(item.id), label: personLabel(item) })),
    { value: NEW_PERSON, label: "Nowa osoba" },
  ];
  const digits = number.replace(/\D/g, "").length;
  const canSave = digits >= MIN_PHONE_DIGITS && (!isNew || name.trim() !== "");
  const pending = update.isPending || create.isPending;

  const callbacks = {
    onSuccess: () => {
      showSuccess("Zapisano numer.");
      onDone();
    },
    onError: (error: unknown) => showError(apiErrorMessage(error, "Nie udało się zapisać numeru.")),
  };
  const save = () => {
    if (isNew) {
      create.mutate({ company_id: row.company.id, full_name: name.trim(), mobile_phone: number.trim() }, callbacks);
    } else {
      update.mutate({ mobile_phone: number.trim() }, callbacks);
    }
  };

  return (
    <div className={PANEL}>
      <div className="flex flex-wrap items-center gap-2">
        {known.length > 0 && (
          <SalesSelect
            value={person}
            onValueChange={setPerson}
            options={options}
            ariaLabel="Czyj to numer"
            className="h-8 w-56 text-xs [&>span]:block [&>span]:truncate"
          />
        )}
        {isNew && (
          <Input
            className="h-8 w-44 text-xs"
            placeholder="Imię i nazwisko"
            aria-label="Imię i nazwisko"
            value={name}
            maxLength={255}
            onChange={(event) => setName(event.target.value)}
          />
        )}
        <Input
          className="h-8 w-40 text-xs"
          placeholder="Numer telefonu"
          aria-label="Numer telefonu"
          value={number}
          maxLength={60}
          onChange={(event) => setNumber(event.target.value)}
        />
        <SaveButtons canSave={canSave} label="Zapisz numer" pending={pending} onSave={save} onCancel={onDone} />
      </div>
    </div>
  );
}
