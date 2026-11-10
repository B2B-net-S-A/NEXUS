"use client";

import Link from "next/link";
import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useOpportunities,
  useSalesCompany,
  useSalesContacts,
  type DuplicateCompany,
  type Ref,
} from "@/lib/api/sales";
import {
  useBookMeeting,
  useCompanyIdentity,
  useHandoffForm,
  type BookMeetingInput,
  type Handoff,
} from "@/lib/api/sales-handoffs";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { useAuthStore } from "@/store/auth";

import { duplicatesFromError } from "../CompanyFormDialog";
import { SalesSelect } from "../SalesSelect";
import { CompanyIdentityHints } from "./CompanyIdentityHints";
import { DEFAULT_DURATION, DURATIONS, fieldsFromTerm, handoffWhen, termFromFields } from "./helpers";
import { HostCalendar } from "./HostCalendar";

const NEW_PERSON = "new";
/** Etapy, z których własną szansę przekazuje się zamiast zakładać drugą. */
const REUSABLE_STAGES = ["lead", "qualifying-meeting"];
const DURATION_OPTIONS = DURATIONS.map((minutes) => ({ value: String(minutes), label: `${minutes} min` }));
const HEADING = "text-xs font-medium uppercase tracking-wide text-muted-foreground";

export interface BookMeetingFormProps {
  /** Firma znana z miejsca wywołania (karta firmy, wynik rozmowy): nie wybieramy jej drugi raz. */
  company?: Ref;
  /** Istniejąca szansa: przekazanie jej prowadzącemu albo ponowne umówienie po „Nie odbyło się”. */
  opportunity?: { id: number; name: string; company: Ref };
  /** Dotychczasowe przekazanie tej szansy: odpowiedzi i prowadzący wracają do pól. */
  handoff?: Handoff;
  /** Osoba, z którą rozmawiano (kontakt firmy). */
  contactId?: number;
  /** Usługa z kontekstu, np. z kampanii. */
  service?: string;
  onSaved: (handoff: Handoff) => void;
  onCancel: () => void;
}

const text = (value: string): string | null => value.trim() || null;

/**
 * „Umów spotkanie”: jeden formularz zamiast terminu wpisanego w opis szansy. Zapis zakłada
 * szansę „Spotkanie kwalifikujące” u prowadzącego, osobę zapisuje jako kontakt firmy,
 * a umawiającego zostawia jako autora szansy. Formularz podpowiada i nie blokuje:
 * wystarczy firma i prowadzący. Samodzielny komponent: działa w oknie i w panelu.
 */
export function BookMeetingForm({
  company,
  opportunity,
  handoff,
  contactId,
  service: initialService,
  onSaved,
  onCancel,
}: BookMeetingFormProps) {
  const user = useAuthStore((state) => state.user);
  const fixedCompany = opportunity?.company ?? company ?? null;
  const [picked, setPicked] = useState<Ref | null>(fixedCompany);
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [domain, setDomain] = useState<string | null>(null);
  const [person, setPerson] = useState<string | null>(
    contactId ? String(contactId) : handoff?.contact ? String(handoff.contact.id) : null,
  );
  const [personName, setPersonName] = useState("");
  const [personTitle, setPersonTitle] = useState("");
  const [personEmail, setPersonEmail] = useState("");
  const [personPhone, setPersonPhone] = useState("");
  const [host, setHost] = useState<string | null>(handoff?.host ? String(handoff.host.id) : null);
  const [term, setTerm] = useState(() => fieldsFromTerm(null));
  const [minutes, setMinutes] = useState<number>(handoff?.duration_minutes ?? DEFAULT_DURATION);
  const [service, setService] = useState(handoff?.service ?? initialService ?? "");
  const [problem, setProblem] = useState(handoff?.problem ?? "");
  const [decisionMaker, setDecisionMaker] = useState(handoff?.decision_maker ?? "");
  const [timing, setTiming] = useState(handoff?.timing ?? "");
  const [reuse, setReuse] = useState(true);
  const [duplicates, setDuplicates] = useState<DuplicateCompany[]>([]);
  const [error, setError] = useState<string | null>(null);

  const form = useHandoffForm();
  const book = useBookMeeting();
  const { showSuccess } = useToast();
  const typedName = useDebouncedValue(name, 300);
  const typedEmail = useDebouncedValue(personEmail, 300);
  const typedWebsite = useDebouncedValue(website, 300);
  const identity = useCompanyIdentity({
    name: picked ? "" : typedName,
    email: typedEmail,
    website: picked ? "" : typedWebsite,
  });
  const card = useSalesCompany(picked?.id ?? 0);
  const contacts = useSalesContacts(picked?.id ?? null, "", picked !== null);
  const openOpportunities = useOpportunities(
    { company_id: picked?.id ?? null, status: "open" },
    picked !== null && !opportunity,
  );

  const people = contacts.data?.items ?? [];
  const personValue = person ?? (people[0] ? String(people[0].id) : NEW_PERSON);
  const newPerson = picked === null || personValue === NEW_PERSON;
  const hosts = form.data?.hosts ?? [];
  const hostValue = host ?? (form.data?.default_host_id != null ? String(form.data.default_host_id) : "");
  const hostName = hosts.find((item) => String(item.id) === hostValue)?.name ?? "";
  const mine = (openOpportunities.data?.items ?? []).find(
    (item) => item.owner?.id === user?.id && REUSABLE_STAGES.includes(item.stage.key),
  );
  const needsDomain = picked === null || (card.isSuccess && !card.data.domain);
  const domainValue = domain ?? identity.data?.domain ?? "";
  const start = termFromFields(term.day, term.time);
  const halfTerm = Boolean(term.day || term.time) && !start;
  const canSave = (picked !== null || name.trim() !== "") && hostValue !== "";

  const pick = (next: Ref | null) => {
    setPicked(next);
    setPerson(null);
    setDuplicates([]);
    setError(null);
  };

  const submit = (allowDuplicate: boolean) => {
    const payload: BookMeetingInput = {
      host_user_id: Number(hostValue),
      meeting_at: start,
      duration_minutes: minutes,
      service: text(service),
      problem: text(problem),
      decision_maker: text(decisionMaker),
      timing: text(timing),
    };
    if (opportunity) payload.opportunity_id = opportunity.id;
    else if (picked && mine && reuse) payload.opportunity_id = mine.id;
    else if (picked) payload.company_id = picked.id;
    else {
      payload.new_company = {
        name: name.trim(),
        website_url: text(website),
        domain: text(domainValue),
        allow_duplicate: allowDuplicate,
      };
    }
    if (picked && needsDomain && domainValue.trim()) payload.company_domain = domainValue.trim();
    if (!newPerson) payload.contact_id = Number(personValue);
    else if (personName.trim()) {
      payload.new_contact = {
        full_name: personName.trim(),
        title: text(personTitle),
        email: text(personEmail),
        phone: text(personPhone),
      };
    }
    setError(null);
    book.mutate(payload, {
      onSuccess: (saved) => {
        showSuccess(
          saved.meeting_at
            ? `Umówiono: ${saved.company.name}, ${handoffWhen(saved.meeting_at)}. Prowadzi ${saved.host?.name ?? "prowadzący"}.`
            : `Zapisano spotkanie bez terminu: ${saved.company.name}.`,
        );
        onSaved(saved);
      },
      onError: (failure) => {
        const found = duplicatesFromError(failure);
        if (found.length) setDuplicates(found);
        else setError(apiErrorMessage(failure, "Nie udało się umówić spotkania."));
      },
    });
  };

  return (
    <div className="space-y-4" data-testid="book-meeting-form">
      <section className="space-y-2">
        <h3 className={HEADING}>Firma</h3>
        {picked ? (
          <div className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm">
            <span className="min-w-0 truncate font-medium">{picked.name}</span>
            {!fixedCompany && (
              <button type="button" className="shrink-0 text-xs text-primary hover:underline" onClick={() => pick(null)}>
                Zmień
              </button>
            )}
          </div>
        ) : (
          <>
            <Input
              aria-label="Nazwa firmy"
              placeholder="Nazwa firmy"
              autoFocus
              value={name}
              maxLength={500}
              onChange={(event) => {
                setName(event.target.value);
                setDuplicates([]);
              }}
            />
            <CompanyIdentityHints
              matches={identity.data?.matches ?? []}
              onPick={(match) => pick({ id: match.id, name: match.name })}
            />
          </>
        )}
        {opportunity && <p className="text-xs text-muted-foreground">Szansa: {opportunity.name}</p>}
        {!opportunity && mine && (
          <label className="flex items-start gap-2 text-xs text-muted-foreground">
            <Checkbox
              className="mt-0.5"
              checked={reuse}
              onCheckedChange={(checked) => setReuse(checked === true)}
              aria-label="Przekaż moją szansę zamiast zakładać nową"
            />
            <span>
              Masz już w tej firmie szansę „{mine.title}” ({mine.stage.name}). Przekaż ją prowadzącemu zamiast
              zakładać drugą.
            </span>
          </label>
        )}
        {needsDomain && (
          <div className="grid gap-2 sm:grid-cols-2">
            {picked === null && (
              <div className="space-y-1">
                <Label htmlFor="book-meeting-www">Strona www</Label>
                <Input
                  id="book-meeting-www"
                  placeholder="firma.pl"
                  value={website}
                  maxLength={500}
                  onChange={(event) => setWebsite(event.target.value)}
                />
              </div>
            )}
            <div className="space-y-1">
              <Label htmlFor="book-meeting-domain">Domena poczty</Label>
              <Input
                id="book-meeting-domain"
                placeholder="z adresu strony albo maila osoby"
                value={domainValue}
                maxLength={255}
                onChange={(event) => setDomain(event.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Po domenie NEXUS dopasuje do firmy pocztę, kalendarz i punkty do rozmowy.
              </p>
            </div>
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h3 className={HEADING}>Osoba, z którą jest spotkanie</h3>
        {picked !== null && people.length > 0 && (
          <SalesSelect
            ariaLabel="Osoba"
            value={personValue}
            onValueChange={setPerson}
            options={[
              ...people.map((item) => ({
                value: String(item.id),
                label: item.title ? `${item.full_name} · ${item.title}` : item.full_name,
              })),
              { value: NEW_PERSON, label: "Nowa osoba" },
            ]}
          />
        )}
        {newPerson && (
          <div className="grid gap-2 sm:grid-cols-2">
            <Input
              aria-label="Imię i nazwisko"
              placeholder="Imię i nazwisko"
              value={personName}
              maxLength={255}
              onChange={(event) => setPersonName(event.target.value)}
            />
            <Input
              aria-label="Stanowisko"
              placeholder="Stanowisko"
              value={personTitle}
              maxLength={255}
              onChange={(event) => setPersonTitle(event.target.value)}
            />
            <Input
              aria-label="E-mail"
              placeholder="E-mail"
              type="email"
              value={personEmail}
              maxLength={255}
              onChange={(event) => setPersonEmail(event.target.value)}
            />
            <Input
              aria-label="Telefon"
              placeholder="Telefon"
              value={personPhone}
              maxLength={60}
              onChange={(event) => setPersonPhone(event.target.value)}
            />
          </div>
        )}
        {newPerson && <p className="text-xs text-muted-foreground">Osoba zapisze się jako kontakt firmy.</p>}
      </section>

      <section className="space-y-2">
        <h3 className={HEADING}>Termin u prowadzącego</h3>
        <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_9.5rem_7rem_7rem]">
          <SalesSelect
            ariaLabel="Prowadzący"
            value={hostValue}
            onValueChange={setHost}
            options={hosts.map((item) => ({ value: String(item.id), label: item.name }))}
            anyLabel="Wybierz prowadzącego"
          />
          <Input
            aria-label="Dzień spotkania"
            type="date"
            value={term.day}
            onChange={(event) => setTerm((current) => ({ ...current, day: event.target.value }))}
          />
          <Input
            aria-label="Godzina spotkania"
            type="time"
            step={900}
            value={term.time}
            onChange={(event) => setTerm((current) => ({ ...current, time: event.target.value }))}
          />
          <SalesSelect
            ariaLabel="Czas trwania"
            value={String(minutes)}
            onValueChange={(value) => setMinutes(Number(value))}
            options={DURATION_OPTIONS}
          />
        </div>
        <HostCalendar
          hostId={hostValue ? Number(hostValue) : null}
          hostName={hostName}
          day={term.day}
          time={term.time}
          minutes={minutes}
          onPickTime={(time) => setTerm((current) => ({ ...current, time }))}
        />
        {halfTerm && (
          <p className="text-xs text-muted-foreground">
            Wpisz dzień i godzinę. Bez nich spotkanie zapisze się bez terminu i prowadzący zobaczy je osobno.
          </p>
        )}
      </section>

      <section className="space-y-2">
        <h3 className={HEADING}>Dla prowadzącego</h3>
        <div className="grid gap-2 sm:grid-cols-2">
          <Input
            aria-label="Usługa"
            placeholder="Usługa, np. automatyzacje"
            value={service}
            maxLength={120}
            onChange={(event) => setService(event.target.value)}
          />
          <Input
            aria-label="Problem"
            placeholder="Problem: z czym przyszli"
            value={problem}
            maxLength={1000}
            onChange={(event) => setProblem(event.target.value)}
          />
          <Input
            aria-label="Kto decyduje"
            placeholder="Kto decyduje"
            value={decisionMaker}
            maxLength={1000}
            onChange={(event) => setDecisionMaker(event.target.value)}
          />
          <Input
            aria-label="Kiedy"
            placeholder="Kiedy: na kiedy tego potrzebują"
            value={timing}
            maxLength={1000}
            onChange={(event) => setTiming(event.target.value)}
          />
        </div>
      </section>

      {duplicates.length > 0 && (
        <div role="alert" className="rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
          <p className="font-medium text-foreground">Karta o tej nazwie już jest w kartotece sprzedaży.</p>
          <ul className="mt-1 space-y-1">
            {duplicates.map((duplicate) => (
              <li key={duplicate.id} className="flex flex-wrap items-baseline gap-2">
                <Link
                  className="text-primary hover:underline"
                  href={`/sales/companies/${duplicate.id}`}
                  target="_blank"
                >
                  {duplicate.name}
                </Link>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7"
                  onClick={() => pick({ id: duplicate.id, name: duplicate.name })}
                >
                  Użyj tej karty
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {error && (
        <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm">
          {error}
        </p>
      )}

      <div className="space-y-2 border-t border-border pt-3">
        <p className="text-xs leading-snug text-muted-foreground">
          Zapis: szansa „Spotkanie kwalifikujące” u prowadzącego, spotkanie przy szansie, Ty jako źródło.
          Zaproszenie do klienta wysyła się z Outlooka jak dotąd; NEXUS sam niczego nie wysyła.
        </p>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={book.isPending}>
            Anuluj
          </Button>
          {duplicates.length > 0 ? (
            <Button onClick={() => submit(true)} loading={book.isPending}>
              Załóż nową kartę mimo to
            </Button>
          ) : (
            <Button onClick={() => submit(false)} disabled={!canSave} loading={book.isPending}>
              {start ? `Umów ${handoffWhen(start)}` : "Zapisz bez terminu"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

interface BookMeetingDialogProps extends Omit<BookMeetingFormProps, "onSaved" | "onCancel"> {
  onClose: () => void;
  onSaved?: (handoff: Handoff) => void;
}

/** Formularz „Umów spotkanie” w oknie. */
export function BookMeetingDialog({ onClose, onSaved, ...form }: BookMeetingDialogProps) {
  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title={form.handoff ? "Umów ponownie" : "Umów spotkanie"}
      description="Jedna karta zamiast terminu w opisie szansy: firma, osoba, termin i trzy odpowiedzi dla prowadzącego."
      size="lg"
    >
      <BookMeetingForm
        {...form}
        onCancel={onClose}
        onSaved={(saved) => {
          onSaved?.(saved);
          onClose();
        }}
      />
    </AppModal>
  );
}
