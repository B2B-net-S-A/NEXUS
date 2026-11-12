"use client";

import { CalendarClock, Copy, ExternalLink, Phone } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { ACTIVITY_KIND_LABELS, useCreateActivity, type Ref } from "@/lib/api/sales";
import {
  useCallCard,
  useSaveOutcome,
  type CallCard as CallCardData,
  type CallHistoryEntry,
  type QueueItem,
  type QueueOutcome,
} from "@/lib/api/sales-calling";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { BookMeetingDialog } from "../handoff/BookMeetingForm";
import { TalkingPoints } from "../signals/TalkingPoints";
import { CallHook } from "./CallHook";
import {
  DATE_PRESETS,
  isDated,
  itemTitle,
  KEYED_OUTCOMES,
  outcomeForKey,
  outcomeButtonLabel,
  outcomeKey,
  outcomeLabel,
  plusDaysIso,
  weekdayOf,
  type DatedOutcome,
} from "./calling";

const MEETING_SUBJECT = "Spotkanie kwalifikujące";

/** Pole tekstowe albo otwarte okno: klawisz 1–7 jest wtedy zwykłym znakiem. */
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

  // Klawisze 1–7: ten sam wynik co przycisk. Ref, bo nasłuch zakładamy raz na kartę.
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
      <Input
        aria-label="Notatka z rozmowy"
        placeholder="Co ustaliliście? (opcjonalnie)"
        className="h-8 text-xs"
        value={note}
        maxLength={5000}
        disabled={blocked}
        onChange={(event) => setNote(event.target.value)}
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-muted-foreground">Klawisze 1–7 zapisują wynik, potem od razu następna osoba.</span>
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
          ? canEdit
            ? "Ta pozycja jest w kolejce innej osoby: wynik zapisze ona albo administrator."
            : "Wynik rozmowy zapisuje osoba z uprawnieniem „Sprzedaż: edycja”."
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
    void navigator.clipboard
      ?.writeText(phone)
      .then(() => showSuccess(`Skopiowano numer ${phone}.`))
      .catch(() => showError("Nie udało się skopiować numeru. Zaznacz go i skopiuj ręcznie."));
  };
  return (
    <div className="flex flex-1 items-center gap-2">
      <span className="flex select-all items-center gap-1.5 text-lg font-semibold tabular-nums tracking-wide text-foreground">
        <Phone className="h-4 w-4 text-muted-foreground" aria-hidden />
        {phone}
      </span>
      <Button size="sm" variant="outline" className="h-8" onClick={copy}>
        <Copy className="mr-1.5 h-3.5 w-3.5" aria-hidden /> Kopiuj numer
      </Button>
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
  const callable = Boolean(item.phone) && card !== undefined && !card.do_not_contact;

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
        <p className="truncate text-xs text-muted-foreground">
          {[item.person_name, item.person_title].filter(Boolean).join(" · ") || "Bez wskazanej osoby"}
          {card?.email && ` · ${card.email}`}
        </p>
      </div>
      <CallHook companyId={item.company.id} />
      <div className="flex flex-wrap items-center gap-2">
        {card?.do_not_contact ? (
          <Badge variant="danger">Nie kontaktować</Badge>
        ) : callable && item.phone ? (
          <PhoneNumber phone={item.phone} />
        ) : (
          <span className="text-xs tabular-nums text-muted-foreground">{item.phone ?? "Brak numeru telefonu"}</span>
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
          {(card.contact_source || card.note) && (
            <p className="text-xs leading-snug text-muted-foreground">
              {card.contact_source && <span>Skąd kontakt: {card.contact_source}</span>}
              {card.contact_source && card.note && " · "}
              {card.note}
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
