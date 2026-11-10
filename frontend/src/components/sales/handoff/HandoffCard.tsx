"use client";

import Link from "next/link";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import { useConfirmHandoff, type Handoff, type HandoffVerdict } from "@/lib/api/sales-handoffs";
import { formatDayMonthPl } from "@/lib/date-pl";

import { telHref } from "../my-day";
import { WhoWeKnow } from "../MyDayPrepCard";
import { TalkingPoints } from "../signals/TalkingPoints";
import { bookerStatus, confirmMailHref, handoffWhen, mailAddress } from "./helpers";
import { TermPanel } from "./TermPanel";
import { VerdictPanel } from "./VerdictPanel";

export type HandoffPanel = "verdict" | "term" | null;

interface HandoffCardProps {
  handoff: Handoff;
  /** Prowadzący daje werdykt; osoba, która umówiła, widzi stan i ustawia termin. */
  viewer: "host" | "booker";
  canEdit: boolean;
  panel: HandoffPanel;
  onPanel: (panel: HandoffPanel) => void;
  onVerdict?: (kind: HandoffVerdict) => void;
  /** „Umów ponownie” po spotkaniu, które się nie odbyło. */
  onRebook?: () => void;
  /** Na karcie szansy: bez punktów do rozmowy, „Kogo znamy” i odnośnika do szansy, bo są obok. */
  embedded?: boolean;
}

const ANSWERS: { key: "service" | "problem" | "decision_maker" | "timing"; label: string }[] = [
  { key: "service", label: "Usługa" },
  { key: "problem", label: "Problem" },
  { key: "decision_maker", label: "Kto decyduje" },
  { key: "timing", label: "Kiedy" },
];

function FromCall({ handoff }: { handoff: Handoff }) {
  const filled = ANSWERS.filter((answer) => handoff[answer.key]);
  return (
    <div className="border-t border-border pt-3">
      <h3 className="text-sm font-semibold text-foreground">Z rozmowy</h3>
      {filled.length === 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">Bez odpowiedzi z rozmowy. Dopytaj osobę, która umówiła spotkanie.</p>
      ) : (
        <dl className="mt-1 space-y-1 text-xs leading-snug">
          {filled.map((answer) => (
            <div key={answer.key}>
              <dt className="inline text-muted-foreground">{answer.label}: </dt>
              <dd className="inline text-foreground">{handoff[answer.key]}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function ContactLine({ handoff }: { handoff: Handoff }) {
  const contact = handoff.contact;
  if (!contact) return <p className="text-xs text-muted-foreground">Bez osoby po stronie firmy.</p>;
  const reachable = !contact.do_not_contact;
  return (
    <p className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-xs">
      <span className="font-medium text-foreground">{contact.name}</span>
      {contact.title && <span className="text-muted-foreground">{contact.title}</span>}
      {contact.do_not_contact && <Badge variant="neutral" size="sm">Nie kontaktować</Badge>}
      {reachable && contact.phone && (
        <a href={telHref(contact.phone)} className="tabular-nums text-primary hover:underline">
          {contact.phone}
        </a>
      )}
      {reachable && mailAddress(contact.email) && (
        <a href={`mailto:${mailAddress(contact.email)}`} className="truncate text-primary hover:underline">
          {contact.email}
        </a>
      )}
    </p>
  );
}

/** Dzień przed spotkaniem: telefon albo mail do klienta robi człowiek, NEXUS tylko to zapisuje. */
function ConfirmBlock({ handoff }: { handoff: Handoff }) {
  const confirm = useConfirmHandoff();
  const { showError, showSuccess } = useToast();
  const mail = confirmMailHref(handoff);
  const phone = handoff.contact && !handoff.contact.do_not_contact ? handoff.contact.phone : null;
  return (
    <div className="space-y-2 rounded-md border border-border bg-muted/30 p-2" data-testid="confirm-block">
      <p className="text-xs font-medium text-foreground">Potwierdź termin u klienta</p>
      <p className="text-xs leading-snug text-muted-foreground">
        Zadzwoń albo napisz, a potem zaznacz, że klient potwierdził. NEXUS niczego do klienta nie wysyła.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {phone && (
          <Button size="sm" variant="outline" className="h-7" asChild>
            <a href={telHref(phone)}>Zadzwoń</a>
          </Button>
        )}
        {mail && (
          <Button size="sm" variant="outline" className="h-7" asChild>
            <a href={mail}>Napisz</a>
          </Button>
        )}
        <Button
          size="sm"
          className="ml-auto h-7"
          loading={confirm.isPending}
          onClick={() =>
            confirm.mutate(handoff.opportunity.id, {
              onSuccess: () => showSuccess("Zapisano: termin potwierdzony."),
              onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać potwierdzenia.")),
            })
          }
        >
          Klient potwierdził
        </Button>
      </div>
    </div>
  );
}

/**
 * Karta przekazanego spotkania: odpowiedzi od osoby, która je umówiła, punkty do rozmowy
 * z researchu i „Kogo znamy”, a pod spodem to, co jest teraz do zrobienia: termin,
 * potwierdzenie u klienta albo werdykt.
 */
export function HandoffCard({
  handoff,
  viewer,
  canEdit,
  panel,
  onPanel,
  onVerdict,
  onRebook,
  embedded = false,
}: HandoffCardProps) {
  const pending = handoff.phase !== "done";
  const acting = canEdit && pending;
  const isHost = viewer === "host";
  const showVerdict = acting && isHost && (panel === "verdict" || (panel === null && handoff.phase === "verdict"));
  const showTerm = acting && !handoff.from_calendar && (panel === "term" || (panel === null && handoff.phase === "no_term"));
  const canRebook = canEdit && viewer === "booker" && handoff.verdict === "no_show" && handoff.status === "open";
  return (
    <Card className="space-y-3 p-4" data-testid="handoff-card">
      <div>
        <p className="text-xs text-muted-foreground">
          {isHost ? "Przekazane do Ciebie" : "Umówione przez Ciebie"} · {handoff.stage_name}
        </p>
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="truncate text-base font-semibold text-foreground">
            {embedded ? (
              "Przekazane spotkanie"
            ) : (
              <Link href={`/sales/opportunities/${handoff.opportunity.id}`} className="hover:underline">
                {handoff.company.name}
              </Link>
            )}
          </h2>
          <span className="shrink-0 text-sm font-semibold tabular-nums text-primary">
            {handoffWhen(handoff.meeting_at)}
          </span>
        </div>
        <p className="text-xs text-muted-foreground">
          {isHost
            ? `Umówione przez: ${handoff.booked_by?.name ?? "brak osoby"}`
            : `Prowadzi: ${handoff.host?.name ?? "brak prowadzącego"}`}
          {handoff.booked_at ? `, ${formatDayMonthPl(handoff.booked_at)}` : ""}
        </p>
        <div className="mt-1 flex flex-wrap gap-1">
          {handoff.clash && pending && <Badge variant="warning" size="sm">Kolizja z innym spotkaniem</Badge>}
          {handoff.confirmed_at && pending && <Badge variant="success" size="sm">Termin potwierdzony</Badge>}
          {handoff.from_calendar && <Badge variant="neutral" size="sm">Termin z kalendarza</Badge>}
          {!pending && <Badge variant="neutral" size="sm">{bookerStatus(handoff)}</Badge>}
        </div>
      </div>
      <ContactLine handoff={handoff} />
      <FromCall handoff={handoff} />
      {!embedded && <TalkingPoints companyId={handoff.company.id} className="border-t border-border pt-3" />}
      {!embedded && <WhoWeKnow companyId={handoff.company.id} companyName={handoff.company.name} />}
      {acting && isHost && handoff.phase === "confirm" && panel === null && <ConfirmBlock handoff={handoff} />}
      {showTerm && <TermPanel handoff={handoff} onDone={() => onPanel(null)} />}
      {showVerdict && <VerdictPanel handoff={handoff} onSaved={(kind) => onVerdict?.(kind)} />}
      <div className="flex flex-wrap items-center gap-1 border-t border-border pt-3">
        {acting && !handoff.from_calendar && !showTerm && (
          <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => onPanel("term")}>
            {handoff.meeting_at ? "Zmień termin" : "Ustaw termin"}
          </Button>
        )}
        {acting && isHost && !showVerdict && (
          <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => onPanel("verdict")}>
            Daj werdykt
          </Button>
        )}
        {canRebook && (
          <Button size="sm" className="h-7" onClick={onRebook}>
            Umów ponownie
          </Button>
        )}
        {!embedded && (
          <Button size="sm" variant="outline" className="ml-auto h-7" asChild>
            <Link href={`/sales/opportunities/${handoff.opportunity.id}`}>Otwórz szansę</Link>
          </Button>
        )}
      </div>
    </Card>
  );
}
