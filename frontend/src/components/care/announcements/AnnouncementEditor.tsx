"use client";

import { useMemo, useRef, useState } from "react";
import { ArrowLeft, Check, Circle } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  audienceComplete,
  normalizeAudience,
  useAnnouncementStep,
  useAudienceOptions,
  useAudiencePreview,
  useCreateAnnouncement,
  useUpdateAnnouncement,
  type AnnouncementDetail,
  type AnnouncementDraft,
  type AnnouncementKind,
  type AnnouncementSettings,
  type Audience,
} from "@/lib/api/care-announcements";
import { formatDateTimePl } from "@/lib/date-pl";

import { AudiencePicker } from "./AudiencePicker";
import { RecipientsDialog } from "./RecipientsDialog";
import {
  KIND_HINTS,
  KIND_LABELS,
  PLACEHOLDERS,
  plural,
  sendBlocker,
  sendMinutes,
  unknownPlaceholders,
} from "./announcement-format";

const KINDS: AnnouncementKind[] = ["mandatory", "informational"];
const SUBJECT_MAX = 176;

function draftOf(announcement: AnnouncementDetail | null): AnnouncementDraft {
  return {
    kind: announcement?.kind ?? "mandatory",
    subject: announcement?.subject ?? "",
    body: announcement?.body ?? "Cześć {imię},\n\n\n\nW razie pytań odpisz na tę wiadomość albo napisz do swojej opiekunki lub opiekuna: {opiekun}.",
    audience: announcement?.audience ?? { group: "all" },
  };
}

function sameAudience(a: Audience, b: Audience): boolean {
  return JSON.stringify(normalizeAudience(a)) === JSON.stringify(normalizeAudience(b));
}

interface AnnouncementEditorProps {
  announcement: AnnouncementDetail | null;
  settings: AnnouncementSettings;
  onBack: () => void;
  /** Po pierwszym zapisie — adres dostaje id szkicu. */
  onCreated: (id: number) => void;
  /** Po wysłaniu do kolejki albo do zatwierdzenia. */
  onSubmitted: (id: number) => void;
}

/** „Nowy komunikat” (M7): grupa, rodzaj, temat i treść, próba do siebie, wysłanie. */
export function AnnouncementEditor({
  announcement,
  settings,
  onBack,
  onCreated,
  onSubmitted,
}: AnnouncementEditorProps) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [draft, setDraft] = useState<AnnouncementDraft>(() => draftOf(announcement));
  const [listOpen, setListOpen] = useState(false);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const options = useAudienceOptions();
  const preview = useAudiencePreview(draft.kind, draft.audience);
  const create = useCreateAnnouncement();
  const update = useUpdateAnnouncement();
  const testSend = useAnnouncementStep("test-send");
  const submit = useAnnouncementStep("submit");
  const cancel = useAnnouncementStep("cancel");

  const saved = announcement !== null;
  const contentDirty =
    !saved ||
    draft.kind !== announcement.kind ||
    draft.subject.trim() !== announcement.subject ||
    draft.body.trim() !== announcement.body;
  const audienceDirty = saved && !sameAudience(draft.audience, announcement.audience);
  const unknown = useMemo(() => unknownPlaceholders(draft.body), [draft.body]);
  const subjectTooLong = draft.subject.trim().length > SUBJECT_MAX;
  const formValid =
    draft.subject.trim().length >= 3 &&
    !subjectTooLong &&
    draft.body.trim().length > 0 &&
    unknown.length === 0 &&
    audienceComplete(draft.audience);
  const busy =
    create.isPending || update.isPending || testSend.isPending || submit.isPending || cancel.isPending;
  const willReceive = preview.data?.will_receive ?? 0;
  const requiresApproval = preview.data?.requires_approval ?? false;
  const transportReady = settings.transport === "simulate" || settings.transport === "live";
  const blocker = sendBlocker({
    saved,
    contentDirty,
    testCurrent: announcement?.test_current ?? false,
    willReceive,
    sendingEnabled: settings.sending_enabled,
    requiresApproval,
  });

  const fail = (fallback: string) => (error: unknown) =>
    showToast(apiErrorMessage(error, fallback), "error");

  /** Zapis szkicu; zwraca id albo `null`, gdy zapis się nie udał. */
  const save = async (): Promise<number | null> => {
    const payload: AnnouncementDraft = {
      ...draft,
      subject: draft.subject.trim(),
      body: draft.body.trim(),
    };
    try {
      if (!saved) {
        const created = await create.mutateAsync(payload);
        onCreated(created.id);
        return created.id;
      }
      if (contentDirty || audienceDirty) {
        await update.mutateAsync({ id: announcement.id, ...payload });
      }
      return announcement.id;
    } catch (error) {
      fail("Nie udało się zapisać szkicu.")(error);
      return null;
    }
  };

  const runTest = async () => {
    const id = await save();
    if (id === null) return;
    testSend.mutate(id, {
      onSuccess: () => showToast("Próba wysłana na Twój adres", "success"),
      onError: fail("Nie udało się wysłać próby."),
    });
  };

  const runSubmit = async () => {
    if (!announcement) return;
    const minutes = sendMinutes(willReceive, settings.rate_per_minute);
    const confirmed = await askConfirm(
      requiresApproval
        ? {
            title: `Wysłać do zatwierdzenia? (${plural(willReceive, "osoba", "osoby", "osób")})`,
            description:
              `Powyżej ${settings.approval_threshold} osób komunikat zatwierdza head back office albo administrator. Lista odbiorców zamrozi się teraz.`,
            confirmLabel: "Wyślij do zatwierdzenia",
          }
        : {
            title: `Wysłać komunikat do ${plural(willReceive, "osoby", "osób", "osób")}?`,
            description: `Każdy dostanie osobny mail z administracja@. Kolejka wysyła ${settings.rate_per_minute} maili na minutę — ok. ${minutes} min.`,
            confirmLabel: "Wyślij",
          },
    );
    if (!confirmed) return;
    if (audienceDirty && (await save()) === null) return;
    submit.mutate(announcement.id, {
      onSuccess: (detail) => {
        showToast(
          detail.status === "pending" ? "Wysłano do zatwierdzenia" : "Komunikat w kolejce wysyłki",
          "success",
        );
        onSubmitted(detail.id);
      },
      onError: fail("Nie udało się wysłać komunikatu."),
    });
  };

  const runCancel = async () => {
    if (!announcement) return;
    const confirmed = await askConfirm({
      title: "Anulować szkic?",
      description: "Komunikat zostanie na liście jako anulowany. Nikt go nie dostanie.",
      confirmLabel: "Anuluj szkic",
      cancelLabel: "Wróć",
      variant: "destructive",
    });
    if (!confirmed) return;
    cancel.mutate(announcement.id, {
      onSuccess: () => {
        showToast("Szkic anulowany", "success");
        onBack();
      },
      onError: fail("Nie udało się anulować szkicu."),
    });
  };

  const insertPlaceholder = (token: string) => {
    const field = bodyRef.current;
    const start = field?.selectionStart ?? draft.body.length;
    const end = field?.selectionEnd ?? draft.body.length;
    const body = `${draft.body.slice(0, start)}${token}${draft.body.slice(end)}`;
    setDraft({ ...draft, body });
    requestAnimationFrame(() => {
      field?.focus();
      field?.setSelectionRange(start + token.length, start + token.length);
    });
  };

  const testLine = !saved
    ? "Wysyłka próbna do mnie: jeszcze nie"
    : announcement.test_current && !contentDirty
      ? `Wysyłka próbna do mnie: ${formatDateTimePl(announcement.tested_at)}`
      : "Wysyłka próbna do mnie: potrzebna po zmianie treści";
  const tested = saved && announcement.test_current && !contentDirty;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onBack} aria-label="Wróć do listy komunikatów">
            <ArrowLeft className="h-4 w-4" aria-hidden />
            Komunikaty
          </Button>
          <h2 className="truncate text-base font-semibold">
            {saved ? "Szkic komunikatu" : "Nowy komunikat"}
          </h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {saved ? (
            <Button variant="quiet" size="sm" disabled={busy} onClick={runCancel}>
              Anuluj szkic
            </Button>
          ) : null}
          <Button
            variant="outline"
            size="sm"
            disabled={busy || !formValid}
            onClick={() => void save()}
          >
            Zapisz szkic
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={busy || !formValid || !transportReady}
            loading={testSend.isPending}
            onClick={() => void runTest()}
          >
            Wyślij próbnie do mnie
          </Button>
          <Button
            size="sm"
            disabled={busy || !formValid || blocker !== null || preview.isFetching}
            loading={submit.isPending}
            onClick={() => void runSubmit()}
          >
            {requiresApproval ? "Wyślij do zatwierdzenia" : "Wyślij"}
          </Button>
        </div>
      </div>

      {announcement?.return_note ? (
        <p role="status" className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          Zwrócony do poprawy: {announcement.return_note}
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="space-y-3">
          <FormField label="Do kogo">
            <AudiencePicker
              value={draft.audience}
              onChange={(audience) => setDraft({ ...draft, audience })}
              options={options.data}
              optionsError={options.isError}
              disabled={busy}
            />
          </FormField>
          <FormField label="Rodzaj" description={KIND_HINTS[draft.kind]}>
            <SegmentedRadio
              label="Rodzaj komunikatu"
              value={draft.kind}
              disabled={busy}
              onChange={(kind) => setDraft({ ...draft, kind })}
              options={KINDS.map((kind) => ({ value: kind, label: KIND_LABELS[kind] }))}
            />
          </FormField>
          <FormField label="Od">
            <p className="rounded-md border border-border bg-muted/40 px-3 py-1.5 text-sm text-muted-foreground">
              {settings.sender ?? "administracja@"} · odpowiedzi trafią do Spraw
            </p>
          </FormField>
          <FormField
            label="Temat"
            htmlFor="announcement-subject"
            error={subjectTooLong ? `Temat może mieć najwyżej ${SUBJECT_MAX} znaków.` : undefined}
          >
            <Input
              id="announcement-subject"
              value={draft.subject}
              maxLength={SUBJECT_MAX + 20}
              disabled={busy}
              placeholder="np. Od listopada faktury do 5. dnia miesiąca"
              onChange={(event) => setDraft({ ...draft, subject: event.target.value })}
            />
          </FormField>
          <FormField
            label="Treść"
            htmlFor="announcement-body"
            error={
              unknown.length
                ? `Nieznane pole ${unknown.join(", ")}. Dostępne: ${PLACEHOLDERS.join(", ")}.`
                : undefined
            }
            description="Pola uzupełniają się osobno dla każdej osoby."
          >
            <Textarea
              id="announcement-body"
              ref={bodyRef}
              rows={9}
              maxLength={10_000}
              disabled={busy}
              value={draft.body}
              onChange={(event) => setDraft({ ...draft, body: event.target.value })}
            />
            <div className="flex flex-wrap gap-1.5">
              {PLACEHOLDERS.map((token) => (
                <Button
                  key={token}
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => insertPlaceholder(token)}
                >
                  Wstaw {token}
                </Button>
              ))}
            </div>
          </FormField>
        </div>

        <div className="space-y-3">
          <section aria-labelledby="announcement-recipients" className="rounded-lg border border-border bg-card p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 id="announcement-recipients" className="text-sm font-semibold">
                Odbiorcy
              </h3>
              <Button
                size="sm"
                variant="ghost"
                disabled={!preview.data}
                onClick={() => setListOpen(true)}
              >
                Pokaż listę
              </Button>
            </div>
            {!audienceComplete(draft.audience) ? (
              <p className="text-sm text-muted-foreground">Wybierz, do kogo idzie komunikat.</p>
            ) : preview.isError ? (
              <p role="alert" className="text-sm text-destructive">
                {apiErrorMessage(preview.error, "Nie udało się policzyć odbiorców.")}
              </p>
            ) : !preview.data ? (
              <p className="text-sm text-muted-foreground">Liczę odbiorców…</p>
            ) : (
              <dl className="space-y-1 text-sm">
                <div className="flex justify-between gap-2">
                  <dt>W grupie</dt>
                  <dd className="tabular-nums">{preview.data.total}</dd>
                </div>
                <div className="flex justify-between gap-2 text-muted-foreground">
                  <dt>bez adresu e-mail</dt>
                  <dd className="tabular-nums">−{preview.data.excluded_no_email}</dd>
                </div>
                <div className="flex justify-between gap-2 text-muted-foreground">
                  <dt>wypisani z informacyjnych</dt>
                  <dd className="tabular-nums">
                    {draft.kind === "mandatory"
                      ? "obowiązkowy idzie do wszystkich"
                      : `−${preview.data.excluded_opted_out}`}
                  </dd>
                </div>
                <div className="flex justify-between gap-2 border-t border-border pt-1 font-semibold">
                  <dt>Dostanie</dt>
                  <dd className="tabular-nums">{preview.data.will_receive}</dd>
                </div>
              </dl>
            )}
          </section>

          <section aria-labelledby="announcement-checks" className="rounded-lg border border-border bg-card p-3">
            <h3 id="announcement-checks" className="mb-2 text-sm font-semibold">
              Przed wysyłką
            </h3>
            <ul className="space-y-1.5 text-sm">
              <li className="flex items-start gap-2">
                {tested ? (
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
                ) : (
                  <Circle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                )}
                <span>{testLine}</span>
              </li>
              <li className="flex items-start gap-2">
                <Circle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                <span>
                  {requiresApproval
                    ? `Zatwierdzenie: head back office albo administrator, bo powyżej ${settings.approval_threshold} osób`
                    : `Do ${settings.approval_threshold} osób — bez zatwierdzenia`}
                </span>
              </li>
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">
              Wysyłka w kolejce, {settings.rate_per_minute} maili na minutę
              {willReceive ? `, ok. ${sendMinutes(willReceive, settings.rate_per_minute)} min` : ""}.
              Każdy dostaje osobny mail, nikt nie widzi innych adresów.
            </p>
            {!transportReady ? (
              <p className="mt-2 text-xs text-destructive">
                Wysyłka maili z administracja@ nie jest jeszcze skonfigurowana — próba nie wyjdzie.
              </p>
            ) : null}
            {blocker && formValid ? (
              <p className="mt-2 text-xs text-muted-foreground">{blocker}</p>
            ) : null}
          </section>
        </div>
      </div>

      <RecipientsDialog
        open={listOpen}
        onClose={() => setListOpen(false)}
        title={`Odbiorcy · ${preview.data?.will_receive ?? 0} dostanie`}
        rows={preview.data?.rows ?? []}
      />
      {confirmDialog}
    </div>
  );
}
