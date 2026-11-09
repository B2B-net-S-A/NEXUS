"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TruncatedText } from "@/components/ds/TruncatedText";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  SERVICE_LINE_LABELS,
  useCreateOpportunityFromMeeting,
  useCreateSalesContact,
  useMeetingDraft,
  type Meeting,
  type MeetingDraft,
  type ServiceLine,
} from "@/lib/api/sales";
import { apiErrorMessage } from "@/lib/api-error";
import { resolveViewState } from "@/lib/view-state";

import { meetingWhen, shortCompanyName } from "./meeting-helpers";
import { SalesSelect } from "./SalesSelect";

const TITLE = "Załóż szansę ze spotkania";
const DESCRIPTION = "Spotkanie od razu przypnie się do nowej szansy.";
const SERVICE_OPTIONS = Object.entries(SERVICE_LINE_LABELS).map(([value, label]) => ({ value, label }));

type Person = MeetingDraft["people"][number];

interface DraftFormProps {
  meeting: Pick<Meeting, "id">;
  draft: MeetingDraft;
  onClose: () => void;
}

function personLabel(person: Person): string {
  return person.title ? `${person.name} · ${person.title}` : person.name;
}

function DraftForm({ meeting, draft, onClose }: DraftFormProps) {
  const create = useCreateOpportunityFromMeeting();
  const createContact = useCreateSalesContact();
  const { showError, showSuccess } = useToast();
  const attendeesKnown = draft.attendees_known;
  const [title, setTitle] = useState(draft.suggested_title);
  const [serviceLine, setServiceLine] = useState("");
  const [people, setPeople] = useState<Person[]>(
    attendeesKnown ? draft.people.filter((person) => person.attended) : draft.people,
  );
  const [picked, setPicked] = useState<number[]>(
    draft.people.filter((person) => person.attended).map((person) => person.id),
  );
  const [newContact, setNewContact] = useState<string | null>(null);

  const toggle = (id: number, checked: boolean) =>
    setPicked((current) => (checked ? [...current, id] : current.filter((item) => item !== id)));

  const addContact = () => {
    const name = newContact?.trim();
    if (!name) return;
    createContact.mutate(
      { company_id: draft.company.id, full_name: name },
      {
        onSuccess: (contact) => {
          setPeople((current) => [
            ...current,
            { id: contact.id, name: contact.full_name, title: contact.title, attended: false },
          ]);
          setPicked((current) => [...current, contact.id]);
          setNewContact(null);
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się dodać kontaktu.")),
      },
    );
  };

  const submit = () => {
    create.mutate(
      {
        activityId: meeting.id,
        title: title.trim(),
        service_line: serviceLine as ServiceLine,
        contact_ids: picked,
      },
      {
        onSuccess: (created) => {
          showSuccess(`Założono szansę: ${created.title}`);
          onClose();
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się założyć szansy.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title={TITLE}
      description={DESCRIPTION}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button disabled={!title.trim() || !serviceLine || create.isPending} onClick={submit}>
            Załóż szansę
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label>Firma</Label>
          <p className="flex min-h-9 items-center text-sm" title="Spotkanie zostaje przy firmie, do której jest przypisane.">
            {shortCompanyName(draft.company.name)}
          </p>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <Label>Data spotkania</Label>
            <p className="flex h-9 items-center text-sm tabular-nums">
              {meetingWhen(draft.occurred_at)}
              {draft.duration_minutes ? (
                <span className="ml-1.5 text-muted-foreground">{draft.duration_minutes} min</span>
              ) : null}
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="meeting-opportunity-service">
              Usługa <span className="text-destructive">*</span>
            </Label>
            <SalesSelect
              id="meeting-opportunity-service"
              value={serviceLine}
              onValueChange={setServiceLine}
              options={SERVICE_OPTIONS}
              anyLabel="Wybierz usługę"
            />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="meeting-opportunity-title">Nazwa szansy</Label>
          <Input
            id="meeting-opportunity-title"
            autoFocus
            maxLength={255}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <Label>{attendeesKnown ? "Uczestnicy spotkania" : "Kto był na spotkaniu"}</Label>
          {!attendeesKnown && (
            <p className="text-sm text-muted-foreground">
              {people.length > 0 ? "Nie wiemy, kto był na spotkaniu. Zaznacz osoby z firmy." : "Firma nie ma kontaktów."}
            </p>
          )}
          {people.length > 0 && (
            <ul className="max-h-[132px] space-y-1.5 overflow-y-auto">
              {people.map((person) => (
                <li key={person.id} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    id={`meeting-person-${person.id}`}
                    aria-label={personLabel(person)}
                    checked={picked.includes(person.id)}
                    onCheckedChange={(checked) => toggle(person.id, checked === true)}
                  />
                  <label htmlFor={`meeting-person-${person.id}`} className="min-w-0 flex-1">
                    <TruncatedText className="max-w-full">{personLabel(person)}</TruncatedText>
                  </label>
                </li>
              ))}
            </ul>
          )}
          {!attendeesKnown &&
            (newContact === null ? (
              <Button type="button" size="sm" variant="outline" onClick={() => setNewContact("")}>
                Dodaj kontakt
              </Button>
            ) : (
              <div className="flex gap-2">
                <Input
                  aria-label="Imię i nazwisko nowego kontaktu"
                  placeholder="Imię i nazwisko"
                  className="h-8"
                  autoFocus
                  value={newContact}
                  onChange={(event) => setNewContact(event.target.value)}
                />
                <Button
                  type="button"
                  size="sm"
                  disabled={!newContact.trim() || createContact.isPending}
                  onClick={addContact}
                >
                  Dodaj
                </Button>
              </div>
            ))}
        </div>
      </div>
    </AppModal>
  );
}

interface CreateOpportunityFromMeetingDialogProps {
  meeting: Pick<Meeting, "id">;
  onClose: () => void;
}

/** Okno „Załóż szansę”: najpierw podpowiedzi z API, potem formularz. */
export function CreateOpportunityFromMeetingDialog({ meeting, onClose }: CreateOpportunityFromMeetingDialogProps) {
  const draft = useMeetingDraft(meeting.id);
  const state = resolveViewState({
    isLoading: draft.isLoading,
    error: draft.error,
    isSuccess: draft.isSuccess,
    isEmpty: !draft.data,
  });
  if (draft.data) return <DraftForm meeting={meeting} draft={draft.data} onClose={onClose} />;
  return (
    <AppModal open onOpenChange={(open) => !open && onClose()} title={TITLE} description={DESCRIPTION}>
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie…</p>
      ) : (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          onRetry={() => void draft.refetch()}
        />
      )}
    </AppModal>
  );
}
