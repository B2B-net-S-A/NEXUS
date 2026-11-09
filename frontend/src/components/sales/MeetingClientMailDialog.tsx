"use client";

import { X } from "lucide-react";
import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useClientMailDraft, useSendClientMail, type ClientMailDraft } from "@/lib/api/sales";
import { formatDateTimePl } from "@/lib/date-pl";
import { resolveViewState } from "@/lib/view-state";

import { initialRecipients, newRequestId, parseAddresses, riskyFragments } from "./client-mail";

const TITLE = "Podsumowanie dla klienta";

const MAILBOX_NOTICE: Record<Exclude<ClientMailDraft["mailbox"], "ok">, string> = {
  missing: "Podłącz skrzynkę Outlook w Sprzedaży, żeby wysłać mail ze swojego adresu.",
  no_send_scope: "Połącz skrzynkę Outlook ponownie: brakuje zgody na wysyłkę maili.",
};

interface MeetingClientMailDialogProps {
  /** Spotkanie z Outlooka, przy którym leży transkrypt. */
  activityId: number;
  /** Karta szansy, z której wysyłamy (dla spotkania przypiętego tylko do firmy). */
  opportunityId: number;
  onClose: () => void;
}

interface FormProps extends MeetingClientMailDialogProps {
  draft: ClientMailDraft;
}

function MailForm({ activityId, opportunityId, draft, onClose }: FormProps) {
  const send = useSendClientMail();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError, showSuccess } = useToast();
  const [requestId] = useState(newRequestId);
  const [to, setTo] = useState<string[]>(() => initialRecipients(draft));
  const [adding, setAdding] = useState("");
  const [addError, setAddError] = useState<string | null>(null);
  const [subject, setSubject] = useState(draft.subject);
  const [body, setBody] = useState(draft.body);

  const blocked = draft.recipients.filter((recipient) => recipient.blocked);
  const names = new Map(draft.recipients.map((recipient) => [recipient.address, recipient.name]));
  const risky = riskyFragments(`${subject}\n${body}`);
  const mailboxReady = draft.mailbox === "ok";
  const canSend = mailboxReady && to.length > 0 && subject.trim() !== "" && body.trim() !== "" && !send.isPending;

  const addAddresses = () => {
    const { valid, invalid } = parseAddresses(adding);
    const blockedHit = valid.filter((address) => blocked.some((recipient) => recipient.address === address));
    if (invalid.length > 0 || blockedHit.length > 0) {
      setAddError(
        invalid.length > 0
          ? `To nie jest adres: ${invalid.join(", ")}`
          : `Ten adres jest w bazie kandydatów: ${blockedHit.join(", ")}`,
      );
      return;
    }
    setAddError(null);
    setTo((current) => [...current, ...valid.filter((address) => !current.includes(address))]);
    setAdding("");
  };

  const submit = async () => {
    const ok = await askConfirm({
      title: "Wysłać mail do klienta?",
      description: `Mail wyjdzie z Twojej skrzynki${draft.sender_address ? ` ${draft.sender_address}` : ""} do: ${to.join(", ")}. Wysłanego maila nie da się cofnąć.`,
      confirmLabel: "Wyślij",
    });
    if (!ok) return;
    send.mutate(
      {
        activityId,
        subject: subject.trim(),
        body: body.trim(),
        to,
        request_id: requestId,
        opportunity_id: opportunityId,
      },
      {
        onSuccess: () => {
          showSuccess("Wysłano podsumowanie. Mail jest w historii szansy.");
          onClose();
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się wysłać maila.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => !open && onClose()}
      title={TITLE}
      description="Przeczytaj i popraw treść przed wysyłką: model mógł coś pominąć albo przekręcić."
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button disabled={!canSend} onClick={() => void submit()}>
            {send.isPending ? "Wysyłanie…" : "Wyślij"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {!mailboxReady && (
          <p role="alert" className="rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground">
            {MAILBOX_NOTICE[draft.mailbox as Exclude<ClientMailDraft["mailbox"], "ok">]}
          </p>
        )}
        {draft.sent_at && (
          <p className="rounded-md border border-info/20 bg-info-muted px-3 py-2 text-sm text-info-muted-foreground">
            Podsumowanie tego spotkania wyszło już {formatDateTimePl(draft.sent_at)}. Kolejna wysyłka to nowy mail.
          </p>
        )}
        <div className="space-y-1.5">
          <Label htmlFor="client-mail-to">Do</Label>
          {to.length > 0 ? (
            <ul className="flex flex-wrap gap-1.5" aria-label="Adresaci">
              {to.map((address) => (
                <li
                  key={address}
                  className="flex items-center gap-1 rounded-full border border-border bg-muted/40 py-0.5 pl-2.5 pr-1 text-xs"
                  title={address}
                >
                  <span className="max-w-[16rem] truncate">{names.get(address) ?? address}</span>
                  <button
                    type="button"
                    aria-label={`Usuń ${address}`}
                    className="rounded-full p-0.5 text-muted-foreground hover:text-foreground"
                    onClick={() => setTo((current) => current.filter((item) => item !== address))}
                  >
                    <X className="h-3 w-3" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">
              Nie znamy uczestników spoza firmy. Wpisz adres klienta.
            </p>
          )}
          <div className="flex gap-2">
            <Input
              id="client-mail-to"
              value={adding}
              placeholder="Dodaj adres"
              onChange={(event) => {
                setAdding(event.target.value);
                setAddError(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addAddresses();
                }
              }}
            />
            <Button variant="outline" disabled={!adding.trim()} onClick={addAddresses}>
              Dodaj
            </Button>
          </div>
          {addError && <p className="text-xs text-destructive">{addError}</p>}
          {blocked.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Pominięci, bo są w bazie kandydatów: {blocked.map((recipient) => recipient.name ?? recipient.address).join(", ")}.
            </p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="client-mail-subject">Temat</Label>
          <Input id="client-mail-subject" value={subject} maxLength={300} onChange={(event) => setSubject(event.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="client-mail-body">Treść</Label>
          {draft.model_failed && (
            <p className="text-xs text-muted-foreground">Szkic nie powstał. Napisz treść ręcznie, wysyłka działa tak samo.</p>
          )}
          <Textarea
            id="client-mail-body"
            value={body}
            rows={9}
            maxLength={20000}
            className="max-h-[40dvh]"
            onChange={(event) => setBody(event.target.value)}
          />
          <p className="text-xs text-muted-foreground">Stopka z Outlooka dołączy się sama.</p>
        </div>
        {risky.length > 0 && (
          <p role="status" className="rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground">
            Sprawdź przed wysyłką, czy klient ma to zobaczyć: {risky.join(", ")}.
          </p>
        )}
      </div>
      {confirmDialog}
    </AppModal>
  );
}

/** Okno maila do klienta po spotkaniu: szkic z transkryptu, adresaci spoza firmy, wysyłka z własnej skrzynki. */
export function MeetingClientMailDialog(props: MeetingClientMailDialogProps) {
  const draft = useClientMailDraft(props.activityId);
  const state = resolveViewState({
    isLoading: draft.isLoading,
    error: draft.error,
    isSuccess: draft.isSuccess,
    isEmpty: false,
  });
  if (draft.data) return <MailForm {...props} draft={draft.data} />;
  return (
    <AppModal open onOpenChange={(open) => !open && props.onClose()} title={TITLE} size="lg">
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Przygotowuję szkic z transkryptu…</p>
      ) : (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          onRetry={() => void draft.refetch()}
        />
      )}
    </AppModal>
  );
}
