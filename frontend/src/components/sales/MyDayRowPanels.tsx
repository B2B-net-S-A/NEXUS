"use client";

import { useState, type KeyboardEvent } from "react";

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
  { value: "14", label: "Za 2 tyg." },
  { value: "30", label: "Za miesiąc" },
] as const;
type When = (typeof WHEN)[number]["value"];

/** Przycisk terminu, który odpowiada dniowi z pola daty; własna data żadnego nie zaznacza. */
const presetOf = (isoDay: string | null): When | null =>
  WHEN.find((item) => plusDays(Number(item.value)) === isoDay)?.value ?? null;

/** Termin kroku: dziś albo później (porównanie dni ISO jako tekstu). */
const isUpcoming = (isoDay: string | null): isoDay is string => isoDay !== null && isoDay >= plusDays(0);

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

/** Krok: co i kiedy. Termin z przycisku albo własna data z pola obok (prośba handlowca 12.11.2026). */
function StepFields({
  what,
  date,
  onWhat,
  onDate,
}: {
  what: string;
  date: string | null;
  onWhat: (value: string) => void;
  onDate: (value: string | null) => void;
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
      <SegmentedRadio
        size="sm"
        label="Kiedy"
        options={WHEN}
        value={presetOf(date)}
        onChange={(value) => onDate(plusDays(Number(value)))}
      />
      <Input
        type="date"
        className="h-8 w-36 text-xs"
        aria-label="Własna data"
        value={date ?? ""}
        min={plusDays(0)}
        onChange={(event) => onDate(event.target.value || null)}
      />
    </div>
  );
}

/** Krok do zaplanowania: przy zaległym przekładamy to samo zadanie, nie dokładamy drugiego. */
export function PlanPanel({ row, onDone }: { row: MyDayRow; onDone: () => void }) {
  const reschedule = row.section === "overdue" && row.activity_id !== null;
  const create = useCreateActivity();
  const update = useUpdateActivity(row.activity_id ?? 0);
  const { showError, showSuccess } = useToast();
  const [what, setWhat] = useState(reschedule ? (row.subject ?? "") : "Zadzwonić");
  const [date, setDate] = useState<string | null>(plusDays(3));
  const pending = create.isPending || update.isPending;

  const callbacks = {
    onSuccess: () => {
      showSuccess("Zapisano następny krok.");
      onDone();
    },
    onError: (error: unknown) => showError(apiErrorMessage(error, "Nie udało się zapisać kroku.")),
  };
  const save = () => {
    if (!isUpcoming(date)) return;
    const due_at = dueAtMorning(date);
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
        <StepFields what={what} date={date} onWhat={setWhat} onDate={setDate} />
        <SaveButtons canSave={what.trim() !== "" && isUpcoming(date)} pending={pending} onSave={save} onCancel={onDone} />
      </div>
    </div>
  );
}

const OUTCOME_KEYS: Record<Exclude<CallOutcome, "do_not_contact">, string> = {
  connected: "1",
  no_answer: "2",
  call_back: "3",
  wants_offer: "4",
  not_now: "5",
};

const whenLabel = (days: number): string =>
  days === 1 ? "jutro" : days === 7 ? "za tydzień" : days === 30 ? "za miesiąc" : `za ${days} dni`;

const dayLabel = (isoDay: string): string => {
  const preset = presetOf(isoDay);
  if (preset) return whenLabel(Number(preset));
  const [year, month, day] = isoDay.split("-");
  return `na ${day}.${month}.${year}`;
};

const typingTarget = (target: EventTarget | null): boolean =>
  target instanceof HTMLElement && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);

/**
 * Zapis rozmowy w wierszu (decyzja Artura 11.11.2026): klik w wynik zapisuje rozmowę i krok z podpowiedzi
 * wyniku, bez drugiego „Zapisz”. Inny krok niż podpowiedź: „Inny krok”. Klawisze 1–5 jak w kolejce.
 */
/** Komu i przy czym zapisujemy rozmowę: wiersz „Mojego dnia” albo karta firmy. */
export interface CallTarget {
  company: MyDayRow["company"];
  opportunity: MyDayRow["opportunity"];
  person: MyDayRow["person"];
  /** Zaległe zadanie, które zamyka się razem z zapisem rozmowy. */
  closesActivityId: number | null;
}

export function callTargetOf(row: MyDayRow): CallTarget {
  return {
    company: row.company,
    opportunity: row.opportunity,
    person: row.person,
    closesActivityId: row.section === "overdue" ? row.activity_id : null,
  };
}

export function CallPanel({ row, onDone, onBook }: { row: CallTarget; onDone: () => void; onBook?: () => void }) {
  const logOpportunity = useLogCall();
  const logCompany = useLogCompanyCall();
  const createStep = useCreateActivity();
  const complete = useCompleteActivity();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [note, setNote] = useState("");
  const [custom, setCustom] = useState(false);
  const [outcome, setOutcome] = useState<Exclude<CallOutcome, "do_not_contact"> | null>(null);
  const [what, setWhat] = useState("");
  const [date, setDate] = useState<string | null>(plusDays(3));
  const contactId = row.person?.id;
  const isPending = logOpportunity.isPending || logCompany.isPending || createStep.isPending;

  const afterLog = () => {
    if (row.closesActivityId !== null) {
      complete.mutate(
        { id: row.closesActivityId },
        { onError: (error) => showError(apiErrorMessage(error, "Rozmowa zapisana, ale zadanie zostało otwarte.")) },
      );
    }
  };

  const saveStep = (subject: string, isoDay: string | null) => {
    if (isoDay === null || !subject.trim()) {
      showSuccess("Zapisano rozmowę.");
      onDone();
      return;
    }
    createStep.mutate(
      {
        kind: "task",
        subject: subject.trim(),
        due_at: dueAtMorning(isoDay),
        opportunity_id: row.opportunity?.id ?? null,
        company_id: row.opportunity ? null : row.company.id,
      },
      {
        onSuccess: () => {
          showSuccess(`Zapisano rozmowę. Krok: ${subject.trim()}, ${dayLabel(isoDay)}.`);
          onDone();
        },
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
    const text = note.trim() || undefined;
    if (row.opportunity) {
      logOpportunity.mutate(
        { opportunity_id: row.opportunity.id, outcome: value, contact_id: contactId, note: text },
        callbacks,
      );
    } else {
      logCompany.mutate({ company_id: row.company.id, outcome: value, contact_id: contactId, note: text }, callbacks);
    }
  };

  const quick = (value: Exclude<CallOutcome, "do_not_contact">) => {
    if (isPending) return;
    if (custom) {
      const preset = outcomePreset(value);
      setOutcome(value);
      setWhat(preset.what);
      setDate(value === "not_now" ? null : plusDays(3));
      return;
    }
    const preset = outcomePreset(value);
    log(value, () => saveStep(preset.what, plusDays(preset.days)));
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

  const onKeyDown = (event: KeyboardEvent) => {
    if (custom || typingTarget(event.target)) return;
    const hit = OUTCOMES.find((option) => OUTCOME_KEYS[option] === event.key);
    if (hit) {
      event.preventDefault();
      quick(hit);
    }
  };

  return (
    <div className={PANEL} onKeyDown={onKeyDown}>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          className="h-8 min-w-48 flex-1 text-xs"
          placeholder="Co ustaliliście? (opcjonalnie)"
          aria-label="Notatka z rozmowy"
          value={note}
          maxLength={2000}
          onChange={(event) => setNote(event.target.value)}
        />
        <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => setCustom((value) => !value)}>
          {custom ? "Krok z podpowiedzi" : "Inny krok"}
        </Button>
        <Button size="sm" variant="ghost" className="h-7 px-2" onClick={onDone}>
          Anuluj
        </Button>
      </div>
      <div className="flex flex-wrap gap-1" role="group" aria-label="Wynik rozmowy">
        {OUTCOMES.map((option) => {
          const preset = outcomePreset(option);
          return (
            <Button
              key={option}
              size="sm"
              className="h-auto flex-col items-start gap-0 px-2 py-1"
              variant={custom && outcome === option ? "primary" : "outline"}
              aria-label={CALL_OUTCOME_LABELS[option]}
              aria-keyshortcuts={OUTCOME_KEYS[option]}
              disabled={isPending}
              onClick={() => quick(option)}
            >
              <span>
                <kbd className="mr-1 rounded border border-border px-1 text-[10px] text-muted-foreground">
                  {OUTCOME_KEYS[option]}
                </kbd>
                {CALL_OUTCOME_LABELS[option]}
              </span>
              {!custom && (
                <span className="text-[10px] font-normal text-muted-foreground">
                  {option === "not_now" ? "wrócić za miesiąc" : `krok ${whenLabel(preset.days)}`}
                </span>
              )}
            </Button>
          );
        })}
        {onBook && (
          <Button size="sm" variant="outline" className="h-auto px-2 py-1" disabled={isPending} onClick={onBook}>
            Umówione spotkanie
          </Button>
        )}
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
      {custom && (
        <div className="flex flex-wrap items-center gap-2">
          <StepFields what={what} date={date} onWhat={setWhat} onDate={setDate} />
          <SaveButtons
            canSave={outcome !== null && (date === null || isUpcoming(date))}
            pending={isPending}
            onSave={() => outcome && log(outcome, () => saveStep(what, date))}
            onCancel={onDone}
          />
        </div>
      )}
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
