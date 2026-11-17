"use client";

import Link from "next/link";
import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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
  useSendBookingMail,
  type BookMeetingInput,
  type Handoff,
} from "@/lib/api/sales-handoffs";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { useAuthStore } from "@/store/auth";

import { newRequestId, parseAddresses } from "../client-mail";
import { duplicatesFromError } from "../CompanyFormDialog";
import { SalesSelect } from "../SalesSelect";
import { CompanyIdentityHints } from "./CompanyIdentityHints";
import {
  bookingMailBody,
  bookingMailSubject,
  DEFAULT_DURATION,
  DURATIONS,
  fieldsFromTerm,
  handoffWhen,
  termFromFields,
} from "./helpers";
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
  /**
   * Mail do klienta z kolejki dzwonienia (prośba dzwoniących 17.11.2026): adres, tytuł
   * i treść do poprawienia. Po zapisie wychodzi ze skrzynki osoby, która umawia, do
   * klienta z kopią do prowadzącego. Adres i treść zostają też podpowiedzią do okna
   * „Wyślij zaproszenie” prowadzącego (spotkanie Teams wysyła dalej on).
   */
  invite?: { email: string | null };
  /** Spotkanie zapisane, zanim wyjdzie mail: okno wie, że zamknięcie nie może go zgubić. */
  onBooked?: (handoff: Handoff) => void;
  onSaved: (handoff: Handoff) => void;
  onCancel: () => void;
}

const text = (value: string): string | null => value.trim() || null;

/** Podpowiedź treści zaproszenia Teams dla prowadzącego (13.11.2026); mail do klienta ma własną. */
export function inviteTemplate(service?: string): string {
  const topic = service?.trim() ? ` w sprawie: ${service.trim()}` : "";
  return `Dzień dobry,\n\nzgodnie z naszą rozmową telefoniczną przesyłam zaproszenie na spotkanie${topic}.\n\nPozdrawiam`;
}

const MAILBOX_NOTICE = {
  missing: "Twoja skrzynka Outlook nie jest podłączona w Sprzedaży: spotkanie się zapisze, mail nie wyjdzie.",
  no_send_scope: "Połącz skrzynkę Outlook ponownie (pasek „Outlook” nad zakładkami): brakuje zgody na wysyłkę.",
} as const;

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
  invite,
  onBooked,
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
  const [inviteTo, setInviteTo] = useState(invite?.email ?? "");
  // Tytuł i treść idą za terminem i prowadzącym, dopóki dzwoniący ich nie poprawi.
  const [mailSubject, setMailSubject] = useState<string | null>(null);
  const [mailBody, setMailBody] = useState<string | null>(null);
  const [mailOn, setMailOn] = useState(true);
  // Jeden klucz na otwarcie okna: drugi klik nie wyśle drugiego maila.
  const [mailRequestId] = useState(newRequestId);
  const [unsent, setUnsent] = useState<{ handoff: Handoff; error: string } | null>(null);
  const [duplicates, setDuplicates] = useState<DuplicateCompany[]>([]);
  const [error, setError] = useState<string | null>(null);

  const form = useHandoffForm();
  // Z kolejki dzwonienia listy odświeża zapis wyniku przy zamknięciu (patrz `useBookMeeting`).
  const book = useBookMeeting({ refresh: !invite });
  const sendMail = useSendBookingMail();
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
  const hostRow = hosts.find((item) => String(item.id) === hostValue);
  const hostName = hostRow?.name ?? "";
  const mine = (openOpportunities.data?.items ?? []).find(
    (item) => item.owner?.id === user?.id && REUSABLE_STAGES.includes(item.stage.key),
  );
  const needsDomain = picked === null || (card.isSuccess && !card.data.domain);
  const domainValue = domain ?? identity.data?.domain ?? "";
  const start = termFromFields(term.day, term.time);
  const halfTerm = Boolean(term.day || term.time) && !start;
  const mailbox = form.data?.mailbox ?? "missing";
  const subjectValue = mailSubject ?? bookingMailSubject(start);
  const bodyValue = mailBody ?? bookingMailBody({ start, minutes, service, hostName });
  const mailTo = parseAddresses(inviteTo);
  const mailReady =
    mailbox === "ok" && mailTo.valid.length > 0 && mailTo.invalid.length === 0 && subjectValue.trim() !== "";
  const willMail = Boolean(invite) && mailOn && mailReady;
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
    if (invite) {
      payload.invite_to = text(inviteTo);
      payload.invite_message = inviteTemplate(service);
    }
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
        onBooked?.(saved);
        if (willMail) {
          void mail(saved);
          return;
        }
        showSuccess(booked(saved));
        onSaved(saved);
      },
      onError: (failure) => {
        const found = duplicatesFromError(failure);
        if (found.length) setDuplicates(found);
        else setError(apiErrorMessage(failure, "Nie udało się umówić spotkania."));
      },
    });
  };

  const mail = async (saved: Handoff, requestId: string = mailRequestId) => {
    try {
      await sendMail.mutateAsync({
        opportunity_id: saved.opportunity.id,
        to: mailTo.valid,
        subject: subjectValue.trim(),
        message: bodyValue.trim(),
        cc_host: true,
        request_id: requestId,
      });
    } catch (failure) {
      setUnsent({ handoff: saved, error: apiErrorMessage(failure, "Mail nie wyszedł.") });
      return;
    }
    setUnsent(null);
    showSuccess(`${booked(saved)} Mail wyszedł do klienta, kopia do prowadzącego.`);
    onSaved(saved);
  };

  if (unsent) {
    return (
      <div className="space-y-4" data-testid="book-meeting-unsent">
        <div role="alert" className="rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
          <p className="font-medium text-foreground">
            Spotkanie zapisane: {unsent.handoff.company.name}, {handoffWhen(unsent.handoff.meeting_at)}.
          </p>
          <p className="mt-1 text-foreground">Mail do klienta nie wyszedł. {unsent.error}</p>
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" disabled={sendMail.isPending} onClick={() => onSaved(unsent.handoff)}>
            Zamknij bez maila
          </Button>
          <Button
            loading={sendMail.isPending}
            // Nowy klucz: poprzednia próba nic nie wysłała albo serwer sam zatrzyma ponowienie.
            onClick={() => void mail(unsent.handoff, newRequestId())}
          >
            Wyślij ponownie
          </Button>
        </div>
      </div>
    );
  }

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

      {invite && (
        <section className="space-y-2" data-testid="booking-mail">
          <div className="flex items-center justify-between gap-2">
            <h3 className={HEADING}>Mail do klienta</h3>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <Checkbox
                checked={mailOn && mailbox === "ok"}
                disabled={mailbox !== "ok"}
                onCheckedChange={(checked) => setMailOn(checked === true)}
                aria-label="Wyślij mail po zapisie"
              />
              Wyślij po zapisie
            </label>
          </div>
          {mailbox !== "ok" ? (
            <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-foreground">
              {MAILBOX_NOTICE[mailbox]}
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">
              Od: {form.data?.mailbox_address ?? "Twoja skrzynka"} · DW: {hostName || "prowadzący"}
              {hostRow?.email ? ` <${hostRow.email}>` : ""}
            </p>
          )}
          <div className="grid gap-2 sm:grid-cols-2">
            <Input
              type="email"
              aria-label="Adres e-mail klienta"
              placeholder="Adres e-mail klienta"
              value={inviteTo}
              maxLength={255}
              onChange={(event) => setInviteTo(event.target.value)}
            />
            <Input
              aria-label="Tytuł maila"
              placeholder="Tytuł maila"
              value={subjectValue}
              maxLength={255}
              onChange={(event) => setMailSubject(event.target.value)}
            />
          </div>
          <Textarea
            aria-label="Treść maila"
            rows={5}
            value={bodyValue}
            maxLength={5000}
            onChange={(event) => setMailBody(event.target.value)}
          />
          {mailTo.invalid.length > 0 && (
            <p className="text-xs text-destructive">Niepoprawny adres: {mailTo.invalid.join(", ")}</p>
          )}
          {mailbox === "ok" && mailOn && mailTo.valid.length === 0 && mailTo.invalid.length === 0 && (
            <p className="text-xs text-muted-foreground">Wpisz adres klienta: bez niego mail nie wyjdzie.</p>
          )}
          <p className="text-xs leading-snug text-muted-foreground">
            Stopkę doklei Outlook. Mail ląduje w Wysłanych i na osi szansy. Zaproszenie w Teams wysyła dalej
            prowadzący, z tym adresem w podpowiedzi.
          </p>
        </section>
      )}

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
          Zapis: szansa „Spotkanie kwalifikujące” u prowadzącego, spotkanie przy szansie, Ty jako źródło.{" "}
          {willMail
            ? "Po zapisie mail wyjdzie z Twojej skrzynki do klienta, z kopią do prowadzącego."
            : "Ten formularz niczego nie wysyła: zaproszenie do klienta wyśle prowadzący ze swojej skrzynki."}
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
            <Button
              data-tour={invite ? "sales.calling.booking-mail" : undefined}
              onClick={() => submit(false)}
              disabled={!canSave}
              loading={book.isPending || sendMail.isPending}
            >
              {start ? `Umów ${handoffWhen(start)}` : "Zapisz bez terminu"}
              {willMail ? " i wyślij mail" : ""}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

function booked(saved: Handoff): string {
  return saved.meeting_at
    ? `Umówiono: ${saved.company.name}, ${handoffWhen(saved.meeting_at)}. Prowadzi ${saved.host?.name ?? "prowadzący"}.`
    : `Zapisano spotkanie bez terminu: ${saved.company.name}.`;
}

interface BookMeetingDialogProps extends Omit<BookMeetingFormProps, "onSaved" | "onCancel"> {
  onClose: () => void;
  onSaved?: (handoff: Handoff) => void;
}

/** Formularz „Umów spotkanie” w oknie. */
export function BookMeetingDialog({ onClose, onSaved, ...form }: BookMeetingDialogProps) {
  // Zapisane spotkanie bez wysłanego maila: zamknięcie okna to „Zamknij bez maila”,
  // inaczej wynik rozmowy w kolejce by się nie zapisał.
  const [booked, setBooked] = useState<Handoff | null>(null);
  const close = () => {
    if (booked) onSaved?.(booked);
    onClose();
  };
  return (
    <AppModal
      open
      onOpenChange={(open) => !open && close()}
      title={form.handoff ? "Umów ponownie" : "Umów spotkanie"}
      description="Jedna karta zamiast terminu w opisie szansy: firma, osoba, termin i trzy odpowiedzi dla prowadzącego."
      size="lg"
    >
      <BookMeetingForm
        {...form}
        onBooked={setBooked}
        onCancel={close}
        onSaved={(saved) => {
          onSaved?.(saved);
          onClose();
        }}
      />
    </AppModal>
  );
}
