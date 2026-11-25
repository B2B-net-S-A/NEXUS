"use client";

// „Przypomnij (n)” przy filtrze „Brak RCP”: podgląd treści i adresatów w potwierdzeniu,
// wysyłka od razu (bez powtórek tego samego dnia — pilnuje serwer). Kontrakty bez
// adresata nie znikają: lista pod filtrem „Brak RCP” pokazuje je Finansom.
import { StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Switch } from "@/components/ui/switch";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  FEEDBACK_EXTERNAL_OPTIONS,
  FEEDBACK_MODE_OPTIONS,
  recipientText,
  useReminderOverview,
  useReminderSwitch,
  useSendReminders,
  useSetFeedbackSettings,
  useSetReminderSwitch,
  type FeedbackSettings,
  type ReminderClient,
  type ReminderSendResult,
} from "@/lib/api/settlement-reminders";

import { monthLabel, shortDay } from "./format";

interface ReportRemindersProps {
  clientId: number;
  month: string;
}

function useClientReminders(clientId: number, month: string) {
  const query = useReminderOverview(month, clientId);
  const client: ReminderClient | null = query.data?.clients.find((c) => c.client_id === clientId) ?? null;
  return { query, client };
}

export function sendSummary(result: ReminderSendResult): string {
  const parts = [
    result.mails ? `maile: ${result.mails}` : null,
    result.bells ? `dzwonki opiekunów: ${result.bells}` : null,
    result.already_today ? `dziś już było: ${result.already_today}` : null,
    result.failed ? `nie wyszło: ${result.failed}` : null,
    result.without_recipient ? `bez adresata: ${result.without_recipient}` : null,
  ].filter(Boolean);
  return parts.length ? `Przypomnienia: ${parts.join(", ")}.` : "Nie było do kogo wysłać przypomnienia.";
}

function Preview({ client, address }: { client: ReminderClient; address: string | null }) {
  const reachable = client.rows.filter((r) => r.action !== "none");
  return (
    <div className="space-y-3 text-sm">
      {client.to_consultant > 0 ? (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Mail do konsultanta (z wsparcie@)</p>
          <div className="max-h-48 overflow-y-auto rounded-md border bg-muted/40 p-2 text-xs">
            <p className="font-medium">{client.mail.subject}</p>
            <p className="mt-1 whitespace-pre-wrap">{client.mail.text}</p>
          </div>
        </div>
      ) : null}
      {client.to_owner > 0 ? (
        <p className="text-xs text-muted-foreground">
          Opiekun albo Delivery Lead dostanie dzwonek z listą osób bez raportu{address ? ` i adresem ${address}` : ""}.
        </p>
      ) : null}
      <ul aria-label="Adresaci przypomnień" className="max-h-40 divide-y overflow-y-auto rounded-md border text-xs">
        {reachable.map((row) => (
          <li key={row.contract_id} className="flex flex-wrap justify-between gap-x-3 px-2 py-1">
            <span className="font-medium">{row.person}</span>
            <span className="text-muted-foreground">{recipientText(row)}</span>
          </li>
        ))}
      </ul>
      {client.without_recipient > 0 ? (
        <StatusDot tone="warning">Bez adresata: {client.without_recipient} (nikt nie dostanie przypomnienia)</StatusDot>
      ) : null}
      {client.automatic ? null : (
        <p className="text-xs text-muted-foreground">
          Klient nie ma reguł rozliczeń, więc automat 3., 5. i 7. dnia roboczego go pomija. Przypomnienie wyjdzie tylko z tego przycisku.
        </p>
      )}
    </div>
  );
}

export function ReportReminderButton({ clientId, month }: ReportRemindersProps) {
  const { query, client } = useClientReminders(clientId, month);
  const send = useSendReminders();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showSuccess, showError } = useToast();

  if (!query.isSuccess) return null;
  const data = query.data;
  const count = client ? client.to_consultant + client.to_owner : 0;
  const disabledReason = !data.enabled
    ? "Przypomnienia są wyłączone. Włącza je administrator w karcie „Start rozliczeń”."
    : count === 0
      ? "Nie ma do kogo wysłać przypomnienia."
      : undefined;

  async function remind() {
    if (!client) return;
    const ok = await askConfirm({
      title: `Przypomnieć o raporcie za ${monthLabel(month)} (${count})?`,
      description: "Wysyłka od razu. Kto dostał przypomnienie dziś, nie dostanie drugiego.",
      confirmLabel: "Przypomnij",
      extra: <Preview client={client} address={data.settlements_address} />,
    });
    if (!ok) return;
    try {
      const result = await send.mutateAsync({ clientId, month });
      showSuccess(sendSummary(result));
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się wysłać przypomnień."));
    }
  }

  return (
    <>
      {confirmDialog}
      <Button
        size="sm"
        variant="outline"
        disabled={disabledReason !== undefined || send.isPending}
        title={disabledReason}
        onClick={remind}
      >
        Przypomnij ({count})
      </Button>
    </>
  );
}

/** Pod filtrem „Brak RCP”: kto nie ma adresata i kiedy ostatnio przypominano. */
export function ReportReminderNotice({ clientId, month }: ReportRemindersProps) {
  const { query, client } = useClientReminders(clientId, month);
  if (!query.isSuccess || !client) return null;
  const nobody = client.rows.filter((r) => r.action === "none");
  if (nobody.length === 0 && !client.last_reminder_on) return null;
  return (
    <div className="space-y-1 rounded-xl border bg-card px-3 py-2 text-xs">
      {client.last_reminder_on ? (
        <p className="text-muted-foreground">Ostatnie przypomnienie: {shortDay(client.last_reminder_on)}</p>
      ) : null}
      {nobody.length > 0 ? (
        <StatusDot tone="warning">
          Bez adresata ({nobody.length}): {nobody.map((r) => r.person).join(", ")}. Brak opiekuna kontraktu i Delivery Leada klienta.
        </StatusDot>
      ) : null}
    </div>
  );
}

/** Karta „Start rozliczeń” (admin): włącznik automatu i przycisku. Domyślnie wyłączony. */
export function ReportReminderSwitch() {
  const state = useReminderSwitch(true);
  const save = useSetReminderSwitch();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError } = useToast();

  if (!state.isSuccess) return null;

  async function toggle(next: boolean) {
    const ok = await askConfirm({
      title: next ? "Włączyć przypomnienia o raportach godzin?" : "Wyłączyć przypomnienia o raportach godzin?",
      description: next
        ? "3., 5. i 7. dnia roboczego miesiąca NEXUS przypomni o brakującym RCP: konsultantom mailem (tylko przy panelu „Pilotaż” albo „Wszyscy”), opiekunom dzwonkiem. Finanse dostaną przycisk „Przypomnij”."
        : "Automat i przycisk „Przypomnij” przestaną wysyłać. Dziennik wysłanych zostaje.",
      confirmLabel: "Tak",
      cancelLabel: "Zostaw",
    });
    if (!ok) return;
    try {
      await save.mutateAsync(next);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać włącznika przypomnień."));
    }
  }

  return (
    <>
      {confirmDialog}
      <label className="flex items-center gap-2">
        <Switch checked={state.data.enabled} disabled={save.isPending} onCheckedChange={toggle} />
        Przypomnienia o raportach godzin
      </label>
    </>
  );
}

/**
 * Informacja zwrotna o wadach rozliczenia (karta „Start rozliczeń”, admin): tryb
 * i wysyłka poza firmę. Każda zmiana z potwierdzeniem; poza firmę = decyzja Artura.
 */
export function FeedbackSwitch() {
  const state = useReminderSwitch(true);
  const save = useSetFeedbackSettings();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const { showError } = useToast();

  const current = state.data?.feedback;
  if (!state.isSuccess || !current) return null;

  async function change(field: "mode" | "external", next: string) {
    if (!current || next === current[field]) return;
    const options = field === "mode" ? FEEDBACK_MODE_OPTIONS : FEEDBACK_EXTERNAL_OPTIONS;
    const option = options.find((o) => o.value === next);
    if (!option) return;
    const ok = await askConfirm({
      title:
        field === "mode"
          ? `Informacja zwrotna o wadach: ${option.label.toLowerCase()}?`
          : `Wysyłka poza firmę: ${option.label.toLowerCase()}?`,
      description: option.confirm,
      confirmLabel: "Tak",
      cancelLabel: "Zostaw",
    });
    if (!ok) return;
    try {
      await save.mutateAsync({ [field]: next } as Partial<FeedbackSettings>);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać informacji zwrotnej."));
    }
  }

  return (
    <>
      {confirmDialog}
      <span className="flex flex-wrap items-center gap-2">
        <span id="start-feedback-mode">Informacja zwrotna o wadach</span>
        <SegmentedRadio
          labelledBy="start-feedback-mode"
          size="sm"
          value={current.mode}
          disabled={save.isPending}
          options={FEEDBACK_MODE_OPTIONS.map(({ value, label }) => ({ value, label }))}
          onChange={(next) => void change("mode", next)}
        />
      </span>
      <span className="flex flex-wrap items-center gap-2">
        <span id="start-feedback-external">Poza firmę</span>
        <SegmentedRadio
          labelledBy="start-feedback-external"
          size="sm"
          value={current.external}
          disabled={save.isPending}
          options={FEEDBACK_EXTERNAL_OPTIONS.map(({ value, label }) => ({ value, label }))}
          onChange={(next) => void change("external", next)}
        />
      </span>
    </>
  );
}
