"use client";

// Mail powitalny konsultanta (etap 3, O6) — karta w zakładce „Wejście”
// kontraktu. Treść składa pakiet klienta; wysyła opiekun po podglądzie.

import { useState } from "react";
import { Mail } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useSendWelcomeMail,
  useSetWelcomeMailSwitch,
  useWelcomeMail,
  type WelcomeMailSent,
  type WelcomeMailState,
} from "@/lib/api/client-onboarding";
import { resolveViewState } from "@/lib/view-state";

const MAX_SUBJECT = 200;
const MAX_BODY = 5000;

const DELIVERY_NOTE: Record<WelcomeMailSent["delivery"], string | null> = {
  sent: null,
  simulated: "Tryb symulacji Microsoft 365 — mail nie wyszedł do konsultanta.",
  uncertain:
    "Nie wiadomo, czy mail wyszedł (Microsoft 365 odpowiedział błędem). Sprawdź „Wysłane” w administracja@, zanim napiszesz do konsultanta ponownie.",
};

function shortDate(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return date.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", timeZone: "Europe/Warsaw" });
}

/** Dlaczego „Wyślij” jest nieaktywne — jedno zdanie zamiast szarego przycisku bez słowa. */
export function sendBlocker(state: WelcomeMailState): string | null {
  if (!state.enabled) {
    return state.can_toggle
      ? "Wysyłka maili powitalnych jest wyłączona. To mail do osoby spoza firmy — włącz ją przełącznikiem niżej, gdy pierwsza wysyłka jest uzgodniona."
      : "Wysyłka maili powitalnych jest jeszcze wyłączona — włącza ją administrator. Podgląd działa.";
  }
  if (!state.mailbox_ready) return "Skrzynka administracja@ nie jest ustawiona, więc mail nie ma nadawcy.";
  if (!state.transport_ready) {
    return "Wysyłka ze skrzynki administracja@ nie działa (Microsoft 365 dla „Ludzi” jest wyłączony albo brak poświadczeń) — zgłoś to administratorowi.";
  }
  if (!state.is_sender) {
    return "Mail wysyła opiekun konsultanta: Delivery Lead, Talent Community Manager albo administrator.";
  }
  const blocking = state.issues.find((issue) => issue.blocking);
  return blocking ? blocking.message : null;
}

function SendDialog({
  contractId,
  state,
  onClose,
}: {
  contractId: number;
  state: WelcomeMailState;
  onClose: () => void;
}) {
  const draft = state.draft;
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const send = useSendWelcomeMail(contractId);
  const [subject, setSubject] = useState(draft?.subject ?? "");
  const [body, setBody] = useState(draft?.body ?? "");
  const [error, setError] = useState<string | null>(null);
  const blocker = sendBlocker(state);
  const empty = !subject.trim() || !body.trim();

  const submit = async () => {
    if (!draft?.recipient_email) return;
    const ok = await askConfirm({
      title: "Wysłać mail powitalny?",
      description: `Mail trafi do ${draft.recipient_email} ze skrzynki administracja@. Wysłanego maila nie da się cofnąć.`,
      confirmLabel: "Wyślij",
    });
    if (!ok) return;
    setError(null);
    send.mutate(
      { subject: subject.trim(), body: body.trim() },
      {
        onSuccess: () => {
          showToast("Mail powitalny wysłany", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się wysłać maila.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Mail powitalny — podgląd"
      description={
        draft?.recipient_email
          ? `Do: ${draft.recipient_name ? `${draft.recipient_name} · ` : ""}${draft.recipient_email} · od: administracja@ (odpowiedzi trafią do Spraw)`
          : "Kontrakt nie ma adresu e-mail konsultanta."
      }
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            onClick={() => void submit()}
            disabled={!state.can_send || empty || send.isPending}
          >
            {send.isPending ? "Wysyłanie…" : "Wyślij"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <FormField label="Temat" htmlFor="welcome-subject">
          <Input
            id="welcome-subject"
            maxLength={MAX_SUBJECT}
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
          />
        </FormField>
        <FormField
          label="Treść"
          htmlFor="welcome-body"
          description="Treść złożona z pakietu klienta. Popraw ją, jeśli trzeba — wysyłasz dokładnie to, co widzisz."
        >
          <Textarea
            id="welcome-body"
            rows={14}
            maxLength={MAX_BODY}
            className="max-h-[50dvh]"
            value={body}
            onChange={(event) => setBody(event.target.value)}
          />
        </FormField>
        {blocker ? <p className="text-sm text-muted-foreground">{blocker}</p> : null}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
      {confirmDialog}
    </AppModal>
  );
}

function SwitchRow({ enabled }: { enabled: boolean }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const toggle = useSetWelcomeMailSwitch();
  const flip = async (next: boolean) => {
    if (next) {
      const ok = await askConfirm({
        title: "Włączyć wysyłkę maili powitalnych?",
        description:
          "Opiekunowie zaczną wysyłać maile do konsultantów — osób spoza firmy — ze skrzynki administracja@. Każdy mail wychodzi dopiero po podglądzie i kliknięciu „Wyślij”.",
        confirmLabel: "Włącz",
      });
      if (!ok) return;
    }
    toggle.mutate(next, {
      onSuccess: () => showToast(next ? "Wysyłka włączona" : "Wysyłka wyłączona", "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zmienić ustawienia."), "error"),
    });
  };
  return (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">
      <Switch checked={enabled} disabled={toggle.isPending} onCheckedChange={(next) => void flip(next)} />
      Wysyłka maili powitalnych (dla wszystkich kontraktów)
      {confirmDialog}
    </label>
  );
}

/** Karta „Mail powitalny” w zakładce „Wejście” kontraktu (makieta M6). */
export function WelcomeMailCard({ contractId }: { contractId: number }) {
  const query = useWelcomeMail(contractId);
  const [open, setOpen] = useState(false);
  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  // Wyłączony moduł albo brak dostępu do kontraktu: karta znika, zakładka
  // „Wejście” mówi sama, czego brakuje.
  if (state === "forbidden" || state === "not_found") return null;
  const data = query.data;

  return (
    <section className="space-y-2 rounded-lg border border-border bg-card p-3" aria-label="Mail powitalny">
      <div className="flex items-center gap-2">
        <h3 className="text-[13px] font-semibold text-foreground">Mail powitalny</h3>
        {data?.sent ? (
          <StatusDot
            tone={data.sent.delivery === "sent" ? "success" : "warning"}
            className="ml-auto"
          >
            {data.sent.delivery === "simulated" ? "symulacja" : "wysłany"}{" "}
            {shortDate(data.sent.sent_at)}
          </StatusDot>
        ) : data ? (
          <StatusDot tone="neutral" className="ml-auto">
            nie wysłany
          </StatusDot>
        ) : null}
      </div>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Składanie maila…</p>
      ) : state === "error" || !data ? (
        <QueryStateNotice state="error" onRetry={() => void query.refetch()} />
      ) : data.sent ? (
        <>
          <div className="max-h-64 overflow-y-auto whitespace-pre-line rounded-md bg-muted/40 p-2 text-sm">
            {data.sent.body}
          </div>
          {DELIVERY_NOTE[data.sent.delivery] ? (
            <p className="text-xs text-foreground">{DELIVERY_NOTE[data.sent.delivery]}</p>
          ) : null}
          <p className="text-xs text-muted-foreground">
            Do: {data.sent.recipient_email}
            {data.sent.sent_by_name ? ` · wysłane przez: ${data.sent.sent_by_name}` : ""} · odpowiedzi
            trafiają do Spraw (administracja@)
          </p>
        </>
      ) : (
        <>
          {data.draft ? (
            <div className="line-clamp-6 whitespace-pre-line rounded-md bg-muted/40 p-2 text-sm">
              {data.draft.body}
            </div>
          ) : null}
          {data.issues.length > 0 ? (
            <ul className="space-y-0.5 text-xs" aria-label="Braki w mailu">
              {data.issues.map((issue) => (
                <li
                  key={issue.code}
                  className={issue.blocking ? "text-destructive" : "text-muted-foreground"}
                >
                  {issue.message}
                </li>
              ))}
            </ul>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant={data.can_send ? "primary" : "outline"} onClick={() => setOpen(true)}>
              <Mail className="h-4 w-4" aria-hidden />
              {data.can_send ? "Podgląd i wysyłka" : "Podgląd"}
            </Button>
            {sendBlocker(data) ? (
              <p className="min-w-0 flex-1 text-xs text-muted-foreground">{sendBlocker(data)}</p>
            ) : null}
          </div>
          {data.can_toggle ? <SwitchRow enabled={data.enabled} /> : null}
        </>
      )}
      {open && data && !data.sent ? (
        <SendDialog contractId={contractId} state={data} onClose={() => setOpen(false)} />
      ) : null}
    </section>
  );
}
