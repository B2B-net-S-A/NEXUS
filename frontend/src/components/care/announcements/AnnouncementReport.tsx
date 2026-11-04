"use client";

import { useState } from "react";
import Link from "next/link";

import { AppModal } from "@/components/ds/AppModal";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useAnnouncementStep,
  useReturnAnnouncement,
  type AnnouncementDetail,
  type AnnouncementSettings,
} from "@/lib/api/care-announcements";
import { formatDateTimePl } from "@/lib/date-pl";

import { RecipientsDialog } from "./RecipientsDialog";
import { KIND_LABELS, plural, statusView } from "./announcement-format";

const NOTE_MAX = 500;

function ReturnDialog({
  announcement,
  onClose,
}: {
  announcement: AnnouncementDetail;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const giveBack = useReturnAnnouncement();
  const [note, setNote] = useState("");
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Zwróć do poprawy"
      description="Autor dostanie powiadomienie z Twoją uwagą, a komunikat wróci do szkicu."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            loading={giveBack.isPending}
            onClick={() =>
              giveBack.mutate(
                { id: announcement.id, note: note.trim() || null },
                {
                  onSuccess: () => {
                    showToast("Komunikat wrócił do autora", "success");
                    onClose();
                  },
                  onError: (error) =>
                    showToast(apiErrorMessage(error, "Nie udało się zwrócić komunikatu."), "error"),
                },
              )
            }
          >
            Zwróć
          </Button>
        </>
      }
    >
      <FormField label="Uwaga dla autora" htmlFor="announcement-return-note">
        <Textarea
          id="announcement-return-note"
          rows={3}
          maxLength={NOTE_MAX}
          value={note}
          placeholder="np. dopisz termin i adres do faktur"
          onChange={(event) => setNote(event.target.value)}
        />
      </FormField>
    </AppModal>
  );
}

interface AnnouncementReportProps {
  announcement: AnnouncementDetail;
  settings: AnnouncementSettings;
  onEdit: () => void;
}

/** Karta komunikatu (M8): stan, zatwierdzenie, wysyłka i raport. */
export function AnnouncementReport({ announcement, settings, onEdit }: AnnouncementReportProps) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const approve = useAnnouncementStep("approve");
  const cancel = useAnnouncementStep("cancel");
  const retry = useAnnouncementStep("retry-failed");
  const [returning, setReturning] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const view = statusView(announcement);
  const { counts } = announcement;
  const simulated = announcement.recipients.some((row) => row.simulated);
  // „Niepewny” nie wraca do kolejki sam (mail mógł wyjść) — do sprawdzenia w skrzynce.
  const uncertain = announcement.recipients.filter((row) => row.status === "uncertain");
  const busy = approve.isPending || cancel.isPending || retry.isPending;

  const runApprove = async () => {
    const confirmed = await askConfirm({
      title: `Zatwierdzić komunikat do ${plural(announcement.recipient_count, "osoby", "osób", "osób")}?`,
      description: `Kolejka zacznie wysyłać z administracja@ (${settings.rate_per_minute} maili na minutę). Każdy dostanie osobny mail.`,
      confirmLabel: "Zatwierdź i wyślij",
    });
    if (!confirmed) return;
    approve.mutate(announcement.id, {
      onSuccess: () => showToast("Komunikat zatwierdzony — kolejka wysyła", "success"),
      onError: (error) =>
        showToast(apiErrorMessage(error, "Nie udało się zatwierdzić komunikatu."), "error"),
    });
  };

  const runCancel = async () => {
    const queued = announcement.status === "queued";
    const confirmed = await askConfirm({
      title: queued ? "Zatrzymać wysyłkę?" : "Anulować komunikat?",
      description: queued
        ? "Osoby, do których mail jeszcze nie wyszedł, już go nie dostaną. Wysłanych nie da się cofnąć."
        : "Komunikat zostanie na liście jako anulowany. Nikt go nie dostanie.",
      confirmLabel: queued ? "Zatrzymaj wysyłkę" : "Anuluj komunikat",
      cancelLabel: "Wróć",
      variant: "destructive",
    });
    if (!confirmed) return;
    cancel.mutate(announcement.id, {
      onSuccess: () => showToast(queued ? "Wysyłka zatrzymana" : "Komunikat anulowany", "success"),
      onError: (error) =>
        showToast(apiErrorMessage(error, "Nie udało się anulować komunikatu."), "error"),
    });
  };

  const runRetry = async () => {
    const confirmed = await askConfirm({
      title: "Wysłać ponownie do nieudanych?",
      description: `${plural(counts.failed, "osoba z błędem wysyłki wróci", "osoby z błędem wysyłki wrócą", "osób z błędem wysyłki wróci")} do kolejki. Osoby „niepewne” nie dostaną drugiego maila — sprawdź je w skrzynce.`,
      confirmLabel: "Wyślij ponownie",
      cancelLabel: "Wróć",
    });
    if (!confirmed) return;
    retry.mutate(announcement.id, {
      onSuccess: () => showToast("Nieudane wróciły do kolejki wysyłki", "success"),
      onError: (error) =>
        showToast(apiErrorMessage(error, "Nie udało się wysłać ponownie."), "error"),
    });
  };

  const approval =
    announcement.approver !== null
      ? `${announcement.approver.name} · ${formatDateTimePl(announcement.approved_at)}`
      : announcement.status === "pending"
        ? "czeka na head back office albo administratora"
        : announcement.requires_approval
          ? "—"
          : `do ${settings.approval_threshold} osób — bez zatwierdzenia`;
  const sending = announcement.send_started_at
    ? `${formatDateTimePl(announcement.send_started_at)}${
        announcement.send_finished_at ? `–${formatDateTimePl(announcement.send_finished_at).slice(11)}` : " · trwa"
      } z ${settings.sender ?? "administracja@"}`
    : announcement.status === "queued"
      ? "w kolejce"
      : "—";
  const started = announcement.status === "queued" || announcement.status === "sent";

  return (
    <section
      aria-labelledby={`announcement-${announcement.id}-title`}
      className="space-y-3 rounded-lg border border-border bg-card p-3"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 id={`announcement-${announcement.id}-title`} className="text-sm font-semibold">
          {announcement.subject}
        </h3>
        <StatusDot tone={view.tone}>{view.label}</StatusDot>
      </div>

      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Rodzaj</dt>
        <dd>{KIND_LABELS[announcement.kind]}</dd>
        <dt className="text-muted-foreground">Do kogo</dt>
        <dd>
          {announcement.audience_label}
          {announcement.recipient_count ? ` · ${announcement.recipient_count}` : ""}
        </dd>
        <dt className="text-muted-foreground">Autor</dt>
        <dd>{announcement.author?.name ?? "—"}</dd>
        <dt className="text-muted-foreground">Zatwierdził</dt>
        <dd>{approval}</dd>
        {started ? (
          <>
            <dt className="text-muted-foreground">Wysyłka</dt>
            <dd>{sending}</dd>
            <dt className="text-muted-foreground">Wysłane</dt>
            <dd>
              {counts.sent}
              {simulated ? " · symulacja, nic nie wyszło" : ""}
            </dd>
            {counts.failed + counts.uncertain ? (
              <>
                <dt className="text-muted-foreground">Błędy</dt>
                <dd>
                  {counts.failed + counts.uncertain}
                  {counts.uncertain ? ` · ${counts.uncertain} niepewne — sprawdź w skrzynce` : ""}
                </dd>
              </>
            ) : null}
            <dt className="text-muted-foreground">Odbite</dt>
            <dd>
              {counts.bounced}
              {counts.bounced ? " · opiekun dostał powiadomienie: popraw e-mail" : ""}
            </dd>
          </>
        ) : null}
        <dt className="text-muted-foreground">Wypisani wcześniej</dt>
        <dd>{counts.excluded_opted_out ? `${counts.excluded_opted_out} · nie dostali` : "0"}</dd>
        <dt className="text-muted-foreground">Bez adresu</dt>
        <dd>{counts.excluded_no_email}</dd>
        {started ? (
          <>
            <dt className="text-muted-foreground">Nowe wypisy</dt>
            <dd>{counts.unsubscribed}</dd>
            <dt className="text-muted-foreground">Odpowiedzi</dt>
            <dd>
              {announcement.replies.reply
                ? `${plural(announcement.replies.reply, "sprawa", "sprawy", "spraw")} w administracja@`
                : "0"}
            </dd>
          </>
        ) : null}
      </dl>

      {uncertain.length ? (
        <div className="space-y-1 text-sm">
          <p id={`announcement-${announcement.id}-uncertain`} className="font-medium">
            Sprawdź ręcznie w skrzynce administracja@
          </p>
          <ul
            aria-labelledby={`announcement-${announcement.id}-uncertain`}
            className="space-y-0.5 text-muted-foreground"
          >
            {uncertain.slice(0, 10).map((row) => (
              <li key={row.candidate_id} className="truncate">
                {row.name}
                {row.email ? ` · ${row.email}` : ""}
              </li>
            ))}
          </ul>
          {uncertain.length > 10 ? (
            <p className="text-xs text-muted-foreground">
              …i {uncertain.length - 10} więcej — pełna lista w „Pokaż listę”.
            </p>
          ) : null}
        </div>
      ) : null}

      {announcement.reply_cases.some((reply) => reply.kind === "reply") ? (
        <ul className="space-y-0.5 text-sm" aria-label="Odpowiedzi w Sprawach">
          {announcement.reply_cases
            .filter((reply) => reply.kind === "reply")
            .slice(0, 5)
            .map((reply) => (
              <li key={reply.case_id} className="truncate">
                <Link href={`/people/cases/${reply.case_id}`} className="hover:underline">
                  {reply.title}
                </Link>
              </li>
            ))}
        </ul>
      ) : null}

      {started ? (
        <p className="text-xs text-muted-foreground">
          NEXUS nie śledzi otwarć maili. Raport mówi tylko, co wyszło, co wróciło i kto odpisał.
        </p>
      ) : null}
      {announcement.status === "pending" && announcement.can_approve && !settings.sending_enabled ? (
        <p className="text-xs text-muted-foreground">
          Wysyłka do konsultantów jest wyłączona — zatwierdzić można po jej włączeniu przez administratora.
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {announcement.can_approve ? (
          <>
            <Button
              size="sm"
              disabled={busy || !settings.sending_enabled}
              loading={approve.isPending}
              onClick={() => void runApprove()}
            >
              Zatwierdź
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => setReturning(true)}>
              Zwróć do poprawy
            </Button>
          </>
        ) : null}
        {announcement.can_edit ? (
          <Button size="sm" variant="outline" onClick={onEdit}>
            Edytuj
          </Button>
        ) : null}
        {announcement.recipients.length ? (
          <Button size="sm" variant="ghost" onClick={() => setListOpen(true)}>
            Pokaż listę
          </Button>
        ) : null}
        {announcement.can_retry_failed ? (
          <Button
            size="sm"
            variant="outline"
            disabled={busy || !settings.sending_enabled}
            loading={retry.isPending}
            onClick={() => void runRetry()}
          >
            Wyślij ponownie do nieudanych
          </Button>
        ) : null}
        {announcement.can_cancel && announcement.status !== "draft" ? (
          <Button size="sm" variant="quiet" disabled={busy} onClick={() => void runCancel()}>
            {announcement.status === "queued" ? "Zatrzymaj wysyłkę" : "Anuluj"}
          </Button>
        ) : null}
      </div>

      {returning ? <ReturnDialog announcement={announcement} onClose={() => setReturning(false)} /> : null}
      <RecipientsDialog
        open={listOpen}
        onClose={() => setListOpen(false)}
        title={`Odbiorcy · ${announcement.subject}`}
        rows={announcement.recipients}
      />
      {confirmDialog}
    </section>
  );
}
