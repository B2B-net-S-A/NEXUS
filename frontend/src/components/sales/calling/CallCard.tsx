"use client";

import {
  CalendarClock,
  Copy,
  ExternalLink,
  Mail,
  Pencil,
  Phone,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { ACTIVITY_KIND_LABELS, useCreateActivity, type Ref } from "@/lib/api/sales";
import {
  useCallCard,
  useEditRecord,
  useReportDuplicate,
  useSaveOutcome,
  type CallbackReason,
  type CallCard as CallCardData,
  type CallHistoryEntry,
  type CrmOpportunity,
  type EarlierCall,
  type QueueItem,
  type QueueOutcome,
} from "@/lib/api/sales-calling";
import { formatDayMonthPl } from "@/lib/date-pl";
import { dialablePhone, formatPhone } from "@/lib/phone-format";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { BookMeetingDialog } from "../handoff/BookMeetingForm";
import { TalkingPoints } from "../signals/TalkingPoints";
import { CallHook } from "./CallHook";
import {
  DATE_PRESETS,
  isDated,
  itemTitle,
  changedFields,
  KEYED_OUTCOMES,
  KEYS_RANGE,
  outcomeForKey,
  outcomeButtonLabel,
  outcomeKey,
  outcomeLabel,
  plusDaysIso,
  reasonByline,
  weekdayOf,
  type DatedOutcome,
} from "./calling";

const MEETING_SUBJECT = "Spotkanie kwalifikujące";

/** Pole tekstowe albo otwarte okno: klawisz wyniku jest wtedy zwykłym znakiem. */
function typingTarget(target: EventTarget | null): boolean {
  if (typeof document !== "undefined" && document.querySelector("[role=dialog], [role=alertdialog]")) return true;
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

export interface MeetingStage {
  pipelineId: number;
  stageId: number;
}

interface CallCardProps {
  item: QueueItem;
  /** „3 z 14”: miejsce pozycji na liście. */
  position: string;
  today: string;
  nextCompany: string | null;
  canEdit: boolean;
  /** Etap „Spotkanie kwalifikujące”; `null`, dopóki lejek się nie wczytał. */
  meetingStage: MeetingStage | null;
  onSaved: () => void;
}

function historyLine(entry: CallHistoryEntry): string {
  const kind = entry.kind === "email" && entry.direction === "in" ? "Mail od klienta" : ACTIVITY_KIND_LABELS[entry.kind];
  return [weekdayOf(entry.at), kind, entry.subject].filter(Boolean).join(" · ");
}

function History({ entries, attempts }: { entries: CallHistoryEntry[]; attempts: number }) {
  return (
    <section className="border-t border-border pt-2.5">
      <h3 className="text-sm font-semibold text-foreground">Co już było</h3>
      {entries.length === 0 ? (
        <p className="mt-0.5 text-xs leading-snug text-muted-foreground">
          {attempts > 0 ? "Brak wpisów w historii firmy." : "Pierwsza rozmowa: w NEXUSIE nie ma wcześniejszych kontaktów z tą firmą."}
        </p>
      ) : (
        <ul className="mt-0.5 space-y-0.5">
          {entries.map((entry, index) => (
            <li key={index} className="truncate text-xs leading-snug text-muted-foreground" title={entry.subject ?? undefined}>
              {historyLine(entry)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Script({ item, card }: { item: QueueItem; card: CallCardData }) {
  return (
    <section className="space-y-1.5 border-t border-border pt-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-foreground">Do rozmowy</h3>
        {card.script && (
          <Badge variant="neutral" size="sm">
            Skrypt kampanii
          </Badge>
        )}
      </div>
      {card.script ? (
        <p className="whitespace-pre-line text-xs leading-snug text-muted-foreground">{card.script}</p>
      ) : (
        <p className="text-xs leading-snug text-muted-foreground">
          {item.campaign
            ? "Ta kampania nie ma jeszcze skryptu. Dopiszesz go pod przyciskiem „Kampanie”."
            : "Pozycja spoza kampanii: bez skryptu."}
        </p>
      )}
      <TalkingPoints companyId={card.company.id} />
    </section>
  );
}

function OutcomeKey({ outcome, inverted = false }: { outcome: QueueOutcome; inverted?: boolean }) {
  const key = outcomeKey(outcome);
  if (!key) return null;
  return (
    <kbd
      aria-hidden
      className={cn(
        "rounded border px-1 text-[10px] font-medium leading-4",
        inverted ? "border-primary-foreground/40 text-primary-foreground" : "border-border bg-muted text-muted-foreground",
      )}
    >
      {key}
    </kbd>
  );
}

interface OutcomeFormProps extends Omit<CallCardProps, "position"> {
  card: CallCardData;
}

function OutcomeForm({ item, card, today, nextCompany, canEdit, meetingStage, onSaved }: OutcomeFormProps) {
  const save = useSaveOutcome();
  const createActivity = useCreateActivity();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [note, setNote] = useState("");
  const [dated, setDated] = useState<DatedOutcome | null>(null);
  const [customDate, setCustomDate] = useState("");
  const [meetingAt, setMeetingAt] = useState("");
  const [booking, setBooking] = useState(false);
  // Szansa już założona, a zapis wyniku się nie udał: ponowienie nie zakłada drugiej.
  const [booked, setBooked] = useState<number | null>(null);

  const isMeetingItem = item.section === "meetings";
  const isCampaignRecord = item.campaign !== null;
  const blocked = !canEdit || !card.can_save;
  const pending = save.isPending || createActivity.isPending;
  const person = item.person_name ?? item.company.name;

  const send = (
    outcome: QueueOutcome,
    extra: { callback_on?: string; opportunity_id?: number; never?: boolean } = {},
  ) => {
    // Obietnica zamiast `onSuccess` przy `mutate`: tamte wywołania giną, gdy karta
    // zniknie z ekranu, zanim odświeży się kolejka, a wtedy lista nie przeszłaby dalej.
    save
      .mutateAsync({ item, outcome, note: note.trim() || undefined, ...extra })
      .then(() => {
        showSuccess(`Zapisano: ${outcomeLabel(outcome)}.`);
        onSaved();
      })
      .catch((error: unknown) => showError(apiErrorMessage(error, "Nie udało się zapisać wyniku rozmowy.")));
  };

  const choose = (outcome: QueueOutcome) => {
    if (isDated(outcome)) {
      setDated((current) => (current === outcome ? null : outcome));
      setCustomDate("");
      return;
    }
    send(outcome);
  };

  const bookMeeting = () => {
    if (!isCampaignRecord) return send("meeting_booked");
    if (booked !== null) return send("meeting_booked", { opportunity_id: booked });
    setBooking(true);
  };

  const object = async () => {
    const ok = await askConfirm({
      title: "Nie kontaktować",
      description: `${person}: sprzeciw wobec kontaktu. Zapiszemy go przy tej osobie, numer przestanie być klikalny, a rekord zniknie z kolejki.`,
      confirmLabel: "Zapisz sprzeciw",
      variant: "destructive",
    });
    if (ok) send("do_not_contact");
  };

  const saveMeetingDate = () => {
    if (!meetingAt || item.opportunity_id === null) return;
    createActivity
      .mutateAsync({
        kind: "meeting",
        opportunity_id: item.opportunity_id,
        subject: MEETING_SUBJECT,
        occurred_at: new Date(meetingAt).toISOString(),
      })
      .then(() => {
        showSuccess("Zapisano termin spotkania.");
        onSaved();
      })
      .catch((error: unknown) => showError(apiErrorMessage(error, "Nie udało się zapisać terminu spotkania.")));
  };

  const company: Ref = card.company;
  const meetingBlocked = card.client_refusal !== null || (isCampaignRecord && meetingStage === null);

  // Klawisze wyników: ten sam wynik co przycisk. Ref, bo nasłuch zakładamy raz na kartę.
  const press = useRef<(outcome: QueueOutcome) => void>(() => undefined);
  press.current = (outcome) => {
    if (blocked || pending) return;
    if (outcome === "meeting_booked") {
      if (!isMeetingItem && !meetingBlocked) bookMeeting();
      return;
    }
    choose(outcome);
  };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (typingTarget(event.target)) return;
      if (event.key === "Escape") {
        setDated(null);
        return;
      }
      const outcome = outcomeForKey(event);
      if (!outcome) return;
      event.preventDefault();
      press.current(outcome);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <section className="space-y-2 border-t border-border pt-2.5">
      <h3 className="text-sm font-semibold text-foreground">Wynik rozmowy</h3>
      {isMeetingItem && (
        <div className="flex flex-wrap items-center gap-1.5">
          <Input
            type="datetime-local"
            aria-label="Termin spotkania"
            className="h-8 w-[13.5rem] text-xs"
            value={meetingAt}
            disabled={blocked}
            onChange={(event) => setMeetingAt(event.target.value)}
          />
          <Button size="sm" className="h-8" disabled={blocked || !meetingAt || pending} onClick={saveMeetingDate}>
            <CalendarClock className="mr-1.5 h-3.5 w-3.5" aria-hidden /> Zapisz termin
          </Button>
        </div>
      )}
      {/* Po „Oddzwonić…” ta sama notatka to powód przy przypomnieniu (pole niżej). */}
      {dated !== "call_back" && (
        <Input
          aria-label="Notatka z rozmowy"
          placeholder="Co ustaliliście? (opcjonalnie)"
          className="h-8 text-xs"
          value={note}
          maxLength={5000}
          disabled={blocked}
          onChange={(event) => setNote(event.target.value)}
        />
      )}
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-muted-foreground">
          Klawisze {KEYS_RANGE} zapisują wynik, potem od razu następna osoba.
        </span>
      </div>
      <div data-tour="sales.calling.outcomes" className="grid grid-cols-2 gap-1.5">
        {KEYED_OUTCOMES.map((outcome) => {
          if (outcome === "meeting_booked") {
            if (isMeetingItem) return null;
            return (
              <Button
                key={outcome}
                size="sm"
                className="h-8 justify-start gap-1.5 px-2"
                data-tour="sales.calling.book"
                disabled={blocked || pending || meetingBlocked}
                title={card.client_refusal ?? undefined}
                onClick={bookMeeting}
              >
                <OutcomeKey outcome={outcome} inverted />
                <span className="min-w-0 truncate">{outcomeLabel(outcome)}</span>
              </Button>
            );
          }
          return (
            <Button
              key={outcome}
              size="sm"
              variant={dated === outcome ? "primary" : "outline"}
              className="h-8 min-w-0 justify-start gap-1.5 px-2"
              disabled={blocked || pending}
              aria-expanded={isDated(outcome) ? dated === outcome : undefined}
              aria-keyshortcuts={outcomeKey(outcome) ?? undefined}
              onClick={() => choose(outcome)}
            >
              <OutcomeKey outcome={outcome} inverted={dated === outcome} />
              <span className="min-w-0 truncate" title={outcomeLabel(outcome)}>
                {outcomeButtonLabel(outcome)}
                {isDated(outcome) && "…"}
              </span>
            </Button>
          );
        })}
        <Button
          size="sm"
          variant="ghost"
          className="h-8 justify-start px-2.5 text-destructive hover:bg-destructive/10 hover:text-destructive"
          disabled={blocked || pending}
          onClick={() => void object()}
        >
          {outcomeLabel("do_not_contact")}
        </Button>
      </div>
      {/* Zgłoszenie dzwoniących 23.11.2026 (decyzja Artura): powód opcjonalny, ale na wierzchu. */}
      {dated === "call_back" && (
        <div className="space-y-1">
          <Label htmlFor="callback-reason" className="text-xs font-medium text-foreground">
            Po co oddzwaniamy?
          </Label>
          <Textarea
            id="callback-reason"
            autoFocus
            rows={2}
            className="text-xs"
            placeholder="np. prosi o telefon po rozmowie z zarządem"
            value={note}
            maxLength={5000}
            onChange={(event) => setNote(event.target.value)}
          />
          <p className="text-[11px] text-muted-foreground">
            Zobaczysz to w Przypomnieniach, w „Moim dniu” i na górze karty w dniu telefonu.
          </p>
        </div>
      )}
      {dated && (
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={`${outcomeLabel(dated)}: kiedy`}>
          {DATE_PRESETS[dated].map((preset) => (
            <Button
              key={preset.label}
              size="sm"
              variant="outline"
              className="h-7 px-2"
              disabled={pending}
              onClick={() =>
                preset.days === null
                  ? send(dated, { never: true })
                  : send(dated, { callback_on: plusDaysIso(today, preset.days) })
              }
            >
              {preset.label}
            </Button>
          ))}
          <Input
            type="date"
            aria-label="Inna data"
            className="h-7 w-[8.75rem] text-xs"
            min={today}
            value={customDate}
            onChange={(event) => setCustomDate(event.target.value)}
          />
          <Button
            size="sm"
            className="h-7 px-2"
            disabled={!customDate || pending}
            onClick={() => send(dated, { callback_on: customDate })}
          >
            Zapisz
          </Button>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        {blocked
          ? "Wynik rozmowy zapisuje osoba z uprawnieniem „Sprzedaż: edycja”."
          : nextCompany
            ? `Po zapisie od razu następna: ${nextCompany.replace(/\.$/, "")}.`
            : "To ostatnia pozycja na liście."}
      </p>
      {confirmDialog}
      {/* Decyzja Artura 11.11.2026: ten sam formularz „Umów spotkanie” co w „Moim dniu”; szansę zakłada u prowadzącego. */}
      {booking && meetingStage && (
        <BookMeetingDialog
          company={company}
          contactId={card.contact_id ?? undefined}
          service={card.service ?? undefined}
          // Lista dzwoniących 13.11.2026: treść zaproszenia i adres klienta do poprawienia.
          invite={{ email: card.email }}
          onClose={() => setBooking(false)}
          onSaved={(handoff) => {
            setBooked(handoff.opportunity.id);
            send("meeting_booked", { opportunity_id: handoff.opportunity.id });
          }}
        />
      )}
    </section>
  );
}

/**
 * Numer do wybrania na telefonie (decyzja Artura 12.11.2026): dzwonimy z telefonu, nie z NEXUSA,
 * więc zamiast linku `tel:` jest duży numer i „Kopiuj numer”.
 */
function PhoneNumber({ phone }: { phone: string }) {
  const { showError, showSuccess } = useToast();
  const copy = () => {
    const dialable = dialablePhone(phone);
    void navigator.clipboard
      ?.writeText(dialable)
      .then(() => showSuccess(`Skopiowano numer ${dialable}.`))
      .catch(() => showError("Nie udało się skopiować numeru. Zaznacz go i skopiuj ręcznie."));
  };
  return (
    <div className="flex flex-1 items-center gap-2">
      <span className="flex select-all items-center gap-1.5 text-lg font-semibold tabular-nums tracking-wide text-foreground">
        <Phone className="h-4 w-4 text-muted-foreground" aria-hidden />
        {formatPhone(phone)}
      </span>
      <Button size="sm" variant="outline" className="h-8" onClick={copy}>
        <Copy className="mr-1.5 h-3.5 w-3.5" aria-hidden /> Kopiuj numer
      </Button>
    </div>
  );
}

function CopyEmail({ email }: { email: string }) {
  const { showError, showSuccess } = useToast();
  const copy = () => {
    void navigator.clipboard
      ?.writeText(email)
      .then(() => showSuccess(`Skopiowano adres ${email}.`))
      .catch(() =>
        showError(
          "Nie udało się skopiować adresu. Zaznacz go i skopiuj ręcznie.",
        ),
      );
  };
  return (
    <span className="flex min-w-0 items-center gap-1.5 text-xs text-foreground">
      <Mail
        className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
        aria-hidden
      />
      <span className="min-w-0 select-all truncate">{email}</span>
      <Button
        size="sm"
        variant="ghost"
        className="h-6 shrink-0 px-1.5 text-xs"
        onClick={copy}
        aria-label={`Kopiuj adres ${email}`}
      >
        <Copy className="mr-1 h-3 w-3" aria-hidden /> Kopiuj
      </Button>
    </span>
  );
}

interface ContactEditorProps {
  item: QueueItem;
  card: CallCardData;
  onDone: () => void;
}

/** Edycja danych osoby z karty (lista dzwoniących 13.11.2026): rekord i kontakt w kartotece. */
function ContactEditor({ item, card, onDone }: ContactEditorProps) {
  const edit = useEditRecord();
  const { showError, showSuccess } = useToast();
  const [personName, setPersonName] = useState(item.person_name ?? "");
  const [personTitle, setPersonTitle] = useState(item.person_title ?? "");
  const [phone, setPhone] = useState(item.phone ?? "");
  const [email, setEmail] = useState(card.email ?? "");
  const [note, setNote] = useState(card.note ?? "");
  if (item.record_id === null) return null;
  const recordId = item.record_id;
  const save = () => {
    // Tylko zmienione pola: niezmieniony numer nie może trafić do kontaktu w kartotece.
    const changed = changedFields(
      { person_name: item.person_name, person_title: item.person_title, phone: item.phone, email: card.email, note: card.note },
      { person_name: personName, person_title: personTitle, phone, email, note },
    );
    if (Object.keys(changed).length === 0) {
      onDone();
      return;
    }
    edit
      .mutateAsync({ record_id: recordId, ...changed })
      .then(() => {
        showSuccess("Zapisano dane kontaktowe.");
        onDone();
      })
      .catch((error: unknown) =>
        showError(
          apiErrorMessage(error, "Nie udało się zapisać danych kontaktowych."),
        ),
      );
  };
  return (
    <section
      className="space-y-1.5 rounded-md border border-border p-2"
      aria-label="Edycja danych kontaktowych"
    >
      <div className="grid grid-cols-2 gap-1.5">
        <Input
          aria-label="Imię i nazwisko"
          placeholder="Imię i nazwisko"
          className="h-8 text-xs"
          value={personName}
          maxLength={255}
          onChange={(event) => setPersonName(event.target.value)}
        />
        <Input
          aria-label="Stanowisko"
          placeholder="Stanowisko"
          className="h-8 text-xs"
          value={personTitle}
          maxLength={255}
          onChange={(event) => setPersonTitle(event.target.value)}
        />
        <Input
          aria-label="Telefon"
          placeholder="Telefon"
          className="h-8 text-xs"
          value={phone}
          maxLength={60}
          onChange={(event) => setPhone(event.target.value)}
        />
        <Input
          type="email"
          aria-label="Adres e-mail"
          placeholder="Adres e-mail"
          className="h-8 text-xs"
          value={email}
          maxLength={255}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <Textarea
        aria-label="Uwagi o firmie"
        placeholder="Uwagi o firmie"
        rows={2}
        className="text-xs"
        value={note}
        maxLength={5000}
        onChange={(event) => setNote(event.target.value)}
      />
      <div className="flex justify-end gap-1.5">
        <Button
          size="sm"
          variant="ghost"
          className="h-7"
          onClick={onDone}
          disabled={edit.isPending}
        >
          Anuluj
        </Button>
        <Button
          size="sm"
          className="h-7"
          onClick={save}
          loading={edit.isPending}
        >
          Zapisz dane
        </Button>
      </div>
    </section>
  );
}

/** „To duplikat” (zgłoszenie dzwoniących 23.11.2026): przykład, którego bramki nie złapały. */
function ReportDuplicateButton({ recordId, companyName }: { recordId: number; companyName: string }) {
  const report = useReportDuplicate();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError, showSuccess } = useToast();
  const click = async () => {
    const ok = await askConfirm({
      title: "To duplikat",
      description: `${companyName}: zapiszemy zgłoszenie przy firmie i sprawdzimy, czemu bramka go nie złapała. Rekord zostaje na liście, wynik zapisujesz jak zwykle.`,
      confirmLabel: "Zgłoś duplikat",
    });
    if (!ok) return;
    report
      .mutateAsync({ record_id: recordId })
      .then((result) =>
        showSuccess(result.created ? "Zgłoszono duplikat. Dziękujemy." : "Ten duplikat jest już zgłoszony."),
      )
      .catch((error: unknown) => showError(apiErrorMessage(error, "Nie udało się zgłosić duplikatu.")));
  };
  return (
    <>
      <Button
        size="sm"
        variant="ghost"
        className="h-6 shrink-0 px-1.5 text-xs text-muted-foreground"
        disabled={report.isPending}
        onClick={() => void click()}
      >
        To duplikat
      </Button>
      {confirmDialog}
    </>
  );
}

function InCrmNote({ opportunity }: { opportunity: CrmOpportunity }) {
  return (
    <div
      role="note"
      className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5 rounded-md border border-warning/25 bg-warning-muted px-2.5 py-1.5 text-xs text-warning-muted-foreground"
    >
      <p className="min-w-0">
        <span className="font-medium">Ta firma jest już w CRM:</span> szansa „{opportunity.title}”, etap{" "}
        {opportunity.stage_name}, od {formatDayMonthPl(opportunity.created_at)}
        {opportunity.owner_name ? `, prowadzi ${opportunity.owner_name}` : ""}. Z kolejki dzwoni się przez szansę.
      </p>
      <Button size="sm" variant="outline" className="h-7 shrink-0" asChild>
        <Link href={`/sales/opportunities/${opportunity.id}`}>Otwórz szansę</Link>
      </Button>
    </div>
  );
}

function EarlierCallsNote({ calls }: { calls: EarlierCall[] }) {
  return (
    <div
      role="note"
      className="rounded-md border border-warning/25 bg-warning-muted px-2.5 py-1.5 text-xs text-warning-muted-foreground"
    >
      <p className="font-medium">Pod ten numer już dzwoniono:</p>
      <ul className="mt-0.5 space-y-0.5">
        {calls.map((call) => (
          <li key={call.record_id}>
            {call.label}
            {call.company.name ? ` · ${call.company.name}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Zgłoszenie dzwoniących 23.11.2026: po co oddzwaniamy, nad numerem. */
function CallbackReasonNote({ reason }: { reason: CallbackReason }) {
  return (
    <div role="note" className="rounded-md border border-primary/30 bg-primary/5 px-2.5 py-1.5 text-xs text-foreground">
      <p>
        <span className="font-semibold">Oddzwaniasz, bo: </span>
        {reason.text}
      </p>
      <p className="mt-0.5 text-muted-foreground">{reasonByline(reason)}</p>
    </div>
  );
}

/** Karta wybranej pozycji: kto, haczyk z bota, co już było, skrypt, punkty z researchu i wynik jednym kliknięciem. */
export function CallCard(props: CallCardProps) {
  const { item, position } = props;
  const query = useCallCard(item);
  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: false,
  });
  const card = query.data;
  const callable =
    Boolean(item.phone) && card !== undefined && !card.do_not_contact;
  const [editing, setEditing] = useState(false);
  const canEditContact =
    props.canEdit &&
    item.record_id !== null &&
    card !== undefined &&
    card.can_save &&
    !card.do_not_contact;

  return (
    <Card className="space-y-2.5 p-3.5" aria-label={`Rozmowa: ${item.company.name}`}>
      <div>
        <p className="truncate text-xs text-muted-foreground">{itemTitle(item)}</p>
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="min-w-0 truncate text-base font-semibold text-foreground">
            <Link href={`/sales/companies/${item.company.id}`} className="hover:underline" title={item.company.name}>
              {item.company.name}
            </Link>
          </h2>
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{position}</span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <p className="min-w-0 truncate text-xs text-muted-foreground">
            {[item.person_name, item.person_title]
              .filter(Boolean)
              .join(" · ") || "Bez wskazanej osoby"}
          </p>
          {canEditContact && !editing && (
            <Button
              size="sm"
              variant="ghost"
              className="h-6 shrink-0 px-1.5 text-xs"
              onClick={() => setEditing(true)}
            >
              <Pencil className="mr-1 h-3 w-3" aria-hidden /> Edytuj dane
            </Button>
          )}
          {props.canEdit && item.record_id !== null && !editing && (
            <ReportDuplicateButton recordId={item.record_id} companyName={item.company.name} />
          )}
        </div>
        {card?.email && !card.do_not_contact && (
          <CopyEmail email={card.email} />
        )}
        {/* Lista dzwoniących 13.11.2026: „Uwagi o firmie” z Excela stoją pod danymi firmy. */}
        {card?.note && !editing && (
          <p className="mt-1 whitespace-pre-line rounded-md bg-muted/50 px-2 py-1 text-xs leading-snug text-foreground">
            <span className="font-medium">Uwagi: </span>
            {card.note}
          </p>
        )}
      </div>
      {editing && card && (
        <ContactEditor
          item={item}
          card={card}
          onDone={() => setEditing(false)}
        />
      )}
      {/* Zgłoszenie dzwoniących 17.11.2026: powtórka z innej listy i firma już w CRM, nad numerem. */}
      {card?.crm_opportunity && <InCrmNote opportunity={card.crm_opportunity} />}
      {card?.earlier_calls && card.earlier_calls.length > 0 && <EarlierCallsNote calls={card.earlier_calls} />}
      {item.callback_reason && <CallbackReasonNote reason={item.callback_reason} />}
      <CallHook companyId={item.company.id} />
      <div className="flex flex-wrap items-center gap-2">
        {card?.do_not_contact ? (
          <Badge variant="danger">Nie kontaktować</Badge>
        ) : callable && item.phone ? (
          <PhoneNumber phone={item.phone} />
        ) : (
          <span className="text-xs tabular-nums text-muted-foreground">{item.phone ? formatPhone(item.phone) : "Brak numeru telefonu"}</span>
        )}
        {card?.linkedin_url && (
          <Button size="sm" variant="outline" className="h-8" asChild>
            <a href={card.linkedin_url} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="mr-1.5 h-3.5 w-3.5" aria-hidden /> LinkedIn
            </a>
          </Button>
        )}
        {item.opportunity_id !== null && (
          <Button size="sm" variant="outline" className="h-8" asChild>
            <Link href={`/sales/opportunities/${item.opportunity_id}`}>Otwórz szansę</Link>
          </Button>
        )}
      </div>
      {state === "loading" && <p className="text-xs text-muted-foreground">Wczytywanie karty…</p>}
      {state !== "loading" && (state !== "ready" || !card) && (
        <QueryStateNotice
          state={state === "ready" || state === "empty" ? "error" : state}
          onRetry={() => void query.refetch()}
        />
      )}
      {state === "ready" && card && (
        <>
          {card.client_refusal && (
            <p role="note" className="rounded-md border border-warning/25 bg-warning-muted px-2.5 py-1.5 text-xs text-warning-muted-foreground">
              {card.client_refusal}
            </p>
          )}
          {card.contact_source && (
            <p className="text-xs leading-snug text-muted-foreground">
              Skąd kontakt: {card.contact_source}
            </p>
          )}
          <History entries={card.history} attempts={item.attempts} />
          <Script item={item} card={card} />
          <OutcomeForm {...props} card={card} />
        </>
      )}
    </Card>
  );
}
