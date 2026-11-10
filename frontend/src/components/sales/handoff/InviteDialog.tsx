"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useInviteDraft, useSendInvite, type Handoff, type InviteDraft } from "@/lib/api/sales-handoffs";
import { resolveViewState } from "@/lib/view-state";

import { newRequestId, parseAddresses } from "../client-mail";
import { handoffWhen } from "./helpers";

const TITLE = "Wyślij zaproszenie";

const MAILBOX_NOTICE: Record<Exclude<InviteDraft["mailbox"], "ok">, string> = {
  missing: "Podłącz skrzynkę Outlook w Sprzedaży, żeby wysłać zaproszenie. Bez niej wyślij je z Outlooka jak dotąd.",
  no_calendar_scope: "Połącz skrzynkę Outlook ponownie: brakuje zgody na kalendarz.",
};

function InviteForm({ handoff, draft, onClose }: { handoff: Handoff; draft: InviteDraft; onClose: () => void }) {
  const send = useSendInvite();
  const { showSuccess } = useToast();
  // Jeden klucz na otwarcie okna: drugi klik nie wyśle drugiego zaproszenia.
  const [requestId] = useState(newRequestId);
  const [subject, setSubject] = useState(draft.subject);
  const [to, setTo] = useState(
    draft.recipients
      .filter((recipient) => !recipient.blocked)
      .map((recipient) => recipient.address)
      .join(", "),
  );
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const addresses = parseAddresses(to);
  const blocked = draft.recipients.filter((recipient) => recipient.blocked);
  const ready = draft.mailbox === "ok";
  const canSend = ready && subject.trim() !== "" && addresses.valid.length > 0 && addresses.invalid.length === 0;

  const submit = async () => {
    setError(null);
    try {
      await send.mutateAsync({
        opportunity_id: handoff.opportunity.id,
        subject: subject.trim(),
        to: addresses.valid,
        message: message.trim() || null,
        request_id: requestId,
      });
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się wysłać zaproszenia."));
      return;
    }
    showSuccess("Zaproszenie wysłane. Spotkanie jest w Twoim kalendarzu Outlook.");
    onClose();
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title={TITLE}
      description={`${handoff.company.name}, ${handoffWhen(draft.meeting_at)}, ${draft.duration_minutes} min. Spotkanie Teams wyjdzie z Twojej skrzynki Outlook.`}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={send.isPending}>
            Anuluj
          </Button>
          <Button disabled={!canSend} loading={send.isPending} onClick={() => void submit()}>
            Wyślij zaproszenie
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {!ready && (
          <p role="alert" className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
            {MAILBOX_NOTICE[draft.mailbox as Exclude<InviteDraft["mailbox"], "ok">]}
          </p>
        )}
        <div className="space-y-1">
          <Label htmlFor="handoff-invite-subject">Temat</Label>
          <Input
            id="handoff-invite-subject"
            value={subject}
            maxLength={255}
            onChange={(event) => setSubject(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="handoff-invite-to">Do</Label>
          <Input
            id="handoff-invite-to"
            value={to}
            placeholder="adres klienta, kolejne po przecinku"
            onChange={(event) => setTo(event.target.value)}
          />
          {addresses.invalid.length > 0 && (
            <p className="text-xs text-destructive">To nie jest adres: {addresses.invalid.join(", ")}</p>
          )}
          {blocked.map((recipient) => (
            <p key={recipient.address} className="text-xs text-muted-foreground">
              {recipient.address} jest w bazie kandydatów. Ze Sprzedaży nie zapraszamy kandydatów.
            </p>
          ))}
          {addresses.valid.length === 0 && addresses.invalid.length === 0 && (
            <p className="text-xs text-muted-foreground">Wpisz adres osoby z firmy klienta.</p>
          )}
        </div>
        <div className="space-y-1">
          <Label htmlFor="handoff-invite-message">Dopisek do zaproszenia (opcjonalnie)</Label>
          <Textarea
            id="handoff-invite-message"
            rows={3}
            value={message}
            maxLength={5000}
            onChange={(event) => setMessage(event.target.value)}
          />
        </div>
        {error && (
          <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm">
            {error}
          </p>
        )}
      </div>
    </AppModal>
  );
}

/**
 * Zaproszenie na przekazane spotkanie: wysyła je prowadzący, ze swojej skrzynki i po
 * swoim kliknięciu. Okno najpierw pyta serwer o stan skrzynki, temat i adresata.
 */
export function InviteDialog({ handoff, onClose }: { handoff: Handoff; onClose: () => void }) {
  const draft = useInviteDraft(handoff.opportunity.id);
  if (draft.data) return <InviteForm handoff={handoff} draft={draft.data} onClose={onClose} />;
  const state = resolveViewState({
    isLoading: draft.isLoading,
    error: draft.error,
    isSuccess: draft.isSuccess,
    isEmpty: !draft.data,
  });
  return (
    <AppModal open onOpenChange={(open) => !open && onClose()} title={TITLE}>
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
