"use client";

/**
 * Prawa kolumna okna „Ogłoszenie” (21.10.2026): kontrola i to, gdzie
 * ogłoszenie wisi — strona kariery jednym kliknięciem z tej samej treści oraz
 * portale (wklejane ręcznie, oznaczane w `AdPublications`).
 *
 * Do tej daty strona kariery miała osobny „Opis publiczny” w oknie
 * „Udostępnij”, a kontrola stała w osobnej kolumnie. Makiety:
 * https://claude.ai/artifact/1wcS1zr1hc73nFMKSPwm7P. Reguły:
 * `docs/claude/rekrutacja-tworzenie/ogloszenie-jedna-tresc-strona-kariery.md`.
 *
 * Od 27.10.2026 kolumna mówi też, kto robi brakujący kanał, a DL rekrutacji
 * zapisuje tu „Nie publikujemy” i przypomina rekruterowi o stronie kariery.
 * Wejście z maila przypomnienia (`?ogloszenie=`) otwiera ją z krokami
 * dla kanału — `ogloszenia-przypomnienia-mailem.md`.
 */

import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BellRing, Copy, ExternalLink } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { ConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  jobAdApi,
  jobAdQueryKey,
  missingAdsQueryKey,
  type AdCareerState,
  type AdChannel,
  type AdChannelView,
  type AdFinding,
  type JobAdState,
} from "@/lib/api/jobAd";
import { cn, formatDate } from "@/lib/utils";

import { AdChecksPanel } from "./AdChecksPanel";
import { AdPublications, type AdPublicationsApi } from "./AdPublications";
import { ChannelReminderLine, SkipChannelDialog, shortName } from "./AdReminderControls";

export type AdReminderApi = Pick<
  typeof jobAdApi,
  "skipChannel" | "unskipChannel" | "remindRecruiters"
>;

export interface AdChannelsProps {
  jobId: number;
  state: JobAdState;
  jobClosed: boolean;
  /** Trwa zapis albo przygotowanie treści w oknie. */
  locked: boolean;
  /** Dlaczego teraz nie wolno publikować (kontrola, zapis, otwarta poprawka). */
  publishBlockedReason: string | null;
  publishingCareer: boolean;
  careerCopied: boolean;
  onPublishCareer: () => void;
  onCopyCareerLink: (url: string) => void;
  onShowFinding: (field: string) => void;
  onRemoveFinding: (finding: AdFinding) => void;
  api: AdPublicationsApi;
  /** Kanał z maila przypomnienia (`?ogloszenie=`): kroki i podświetlona karta. */
  focusChannel?: AdFocusChannel | null;
  /** Z maila: od razu okno „Nie publikujemy” (`?ogloszenie=pomin`). */
  openSkip?: boolean;
  /** Z maila: od razu pytanie „Przypomnieć rekruterowi?” (`&przypomnij=rekruter`). */
  askRemind?: boolean;
  /** Parametry maila obsłużone — okno nie otworzy się drugi raz po F5. */
  onIntentHandled?: () => void;
  reminderApi?: AdReminderApi;
}

export type AdFocusChannel = AdChannel;

const FOCUS_STEPS: Record<AdFocusChannel, { title: string; steps: string[] }> = {
  kariera: {
    title: "Z maila: opublikuj na stronie kariery",
    steps: [
      "Przeczytaj treść obok — jest gotowa z Profilu Championa.",
      "Kliknij „Opublikuj na stronie” poniżej.",
    ],
  },
  pracuj: {
    title: "Z maila: wstaw ogłoszenie na Pracuj.pl",
    steps: [
      "Skopiuj pola z zakładki Pracuj.pl (obok) do formularza Pracuj.pl.",
      "Opublikuj tam ogłoszenie.",
      "Wklej poniżej link do ogłoszenia i kliknij „Oznacz”.",
    ],
  },
  jjit: {
    title: "Z maila: wstaw ogłoszenie na JustJoin.IT",
    steps: [
      "Skopiuj opis z zakładki JustJoin.IT (obok) do panelu JustJoin.IT.",
      "Opublikuj tam ogłoszenie.",
      "Wklej poniżej link do ogłoszenia i kliknij „Oznacz”.",
    ],
  },
};

function FocusSteps({ channel }: { channel: AdFocusChannel }) {
  const { title, steps } = FOCUS_STEPS[channel];
  return (
    <section
      aria-label={title}
      data-testid="job-ad-focus"
      className="flex flex-col gap-1.5 rounded-md border border-primary/30 bg-primary/5 px-3 py-2.5 text-[13px]"
    >
      <h2 className="text-[13px] font-semibold leading-snug text-foreground">{title}</h2>
      <ol className="list-decimal pl-5 text-xs leading-relaxed text-foreground">
        {steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <p className="text-xs text-muted-foreground">
        Gdy to zrobisz, przypomnienia o tym kanale przestaną przychodzić.
      </p>
    </section>
  );
}

function careerNote(career: AdCareerState): string | null {
  if (career.status === "none" || !career.published_at) return null;
  const who = career.published_by_name ? ` · ${career.published_by_name}` : "";
  return `Opublikowane ${formatDate(career.published_at)}${who}`;
}

function CareerCard({
  highlight,
  career,
  jobClosed,
  blockedReason,
  publishing,
  copied,
  onPublish,
  onCopy,
}: {
  highlight: boolean;
  career: AdCareerState;
  jobClosed: boolean;
  blockedReason: string | null;
  publishing: boolean;
  copied: boolean;
  onPublish: () => void;
  onCopy: (url: string) => void;
}) {
  const live = career.status !== "none";
  const reason = jobClosed
    ? "Na stronie kariery publikujemy tylko otwarte rekrutacje."
    : blockedReason;
  const note = careerNote(career);
  return (
    <section
      aria-label="Strona kariery"
      data-testid="job-ad-career"
      className={cn(
        "flex flex-col gap-2 rounded-md border bg-card px-3 py-2.5 text-[13px]",
        highlight ? "border-primary ring-2 ring-primary/30" : "border-border",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[13px] font-medium text-foreground">Strona kariery</h3>
        {career.status === "live" ? (
          <span className="rounded-full bg-success-muted px-2 py-0.5 text-[11px] font-medium text-success-muted-foreground">
            Wisi
          </span>
        ) : career.status === "outdated" ? (
          <span className="rounded-full bg-warning-muted px-2 py-0.5 text-[11px] font-medium text-warning-muted-foreground">
            Starsza treść
          </span>
        ) : null}
      </div>

      {career.status === "outdated" ? (
        <p className="text-xs text-warning-muted-foreground">
          Strona pokazuje poprzednią wersję ogłoszenia. Kandydaci widzą ją, dopóki nie
          zaktualizujesz.
        </p>
      ) : !live ? (
        <p className="text-xs text-muted-foreground">
          kariera.b2bnetwork.pl — zgłoszenia trafiają od razu do „Nowych” tej rekrutacji.
          Nazwy klienta i stawek tam nie ma.
        </p>
      ) : null}

      {career.status !== "live" ? (
        <Button
          type="button"
          size="sm"
          className="self-start"
          loading={publishing}
          disabled={!!reason}
          title={reason ?? undefined}
          onClick={onPublish}
        >
          {career.status === "outdated" ? "Zaktualizuj na stronie" : "Opublikuj na stronie"}
        </Button>
      ) : null}
      {reason && career.status !== "live" ? (
        <p className="text-xs text-muted-foreground">{reason}</p>
      ) : null}

      {live && career.url ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 px-2.5"
            onClick={() => onCopy(career.url as string)}
          >
            <Copy className="h-3.5 w-3.5" aria-hidden="true" />
            {copied ? "Skopiowano link" : "Kopiuj link"}
          </Button>
          <a
            href={career.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline"
          >
            Otwórz stronę
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </a>
        </div>
      ) : null}
      {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
    </section>
  );
}

export function AdChannels({
  jobId,
  state,
  jobClosed,
  locked,
  publishBlockedReason,
  publishingCareer,
  careerCopied,
  onPublishCareer,
  onCopyCareerLink,
  onShowFinding,
  onRemoveFinding,
  api,
  focusChannel = null,
  openSkip = false,
  askRemind = false,
  onIntentHandled,
  reminderApi = jobAdApi,
}: AdChannelsProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [skipFor, setSkipFor] = useState<AdChannel[] | null>(null);
  // Okno sterowane stanem, nie `askConfirm` z obietnicą: pytanie otwierane
  // z efektu (link z maila) przeżywa podwójne montowanie StrictMode, a
  // obietnica `useConfirmV2` rozstrzygała się wtedy na „nie” (staging 27.10).
  const [askingRemind, setAskingRemind] = useState(false);
  const reminders = state.reminders;
  const view = (channel: AdChannel): AdChannelView | undefined =>
    reminders?.channels.find((c) => c.channel === channel);
  const canManage = reminders?.can_manage === true;
  const missing = (reminders?.channels ?? [])
    .filter((c) => c.state === "missing")
    .map((c) => c.channel);
  const career = view("kariera");
  const recruiters = reminders?.recruiter_names ?? [];
  const canRemind =
    canManage && career?.state === "missing" && !career.mine && recruiters.length > 0;

  const apply = (next: JobAdState) => {
    queryClient.setQueryData(jobAdQueryKey(jobId), next);
    void queryClient.invalidateQueries({ queryKey: missingAdsQueryKey });
  };

  const skip = useMutation({
    mutationFn: async (input: { channels: AdChannel[]; reason: string }) => {
      let next: JobAdState | null = null;
      for (const channel of input.channels) {
        next = await reminderApi.skipChannel(jobId, channel, input.reason);
      }
      return next;
    },
    onSuccess: (next) => {
      if (next) apply(next);
      setSkipFor(null);
      showSuccess("Zapisane. Przypomnienia o tych kanałach nie przyjdą.");
    },
    onError: (err) =>
      showError(apiErrorMessage(err, "Nie udało się zapisać „nie publikujemy”. Spróbuj ponownie.")),
  });

  const unskip = useMutation({
    mutationFn: (channel: AdChannel) => reminderApi.unskipChannel(jobId, channel),
    onSuccess: apply,
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się cofnąć. Spróbuj ponownie.")),
  });

  const remind = useMutation({
    mutationFn: () => reminderApi.remindRecruiters(jobId),
    onSuccess: (result) => {
      if (result.sent_to.length > 0) {
        showSuccess(`Wysłano przypomnienie: ${result.sent_to.map(shortName).join(", ")}`);
      } else {
        showSuccess(`Już dziś przypomniano: ${result.already.map(shortName).join(", ")}`);
      }
    },
    onError: (err) =>
      showError(apiErrorMessage(err, "Nie udało się wysłać przypomnienia. Spróbuj ponownie.")),
  });


  // Parametry maila obsługujemy raz, gdy stan kanałów jest już wczytany.
  const handled = useRef(false);
  useEffect(() => {
    if (handled.current || !reminders || (!openSkip && !askRemind)) return;
    handled.current = true;
    if (openSkip && canManage && missing.length > 0) {
      setSkipFor(missing);
    } else if (askRemind && canRemind) {
      setAskingRemind(true);
    }
    onIntentHandled?.();
    // Jednorazowo — ref pilnuje, żeby okno nie wracało przy każdym odświeżeniu.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reminders, openSkip, askRemind]);

  const busy = locked || skip.isPending || unskip.isPending;
  const reminderLine = (channel: AdChannel) => {
    const v = view(channel);
    if (!v) return null;
    return (
      <ChannelReminderLine
        view={v}
        canManage={canManage}
        busy={busy}
        onSkip={() => setSkipFor([channel])}
        onUnskip={() => unskip.mutate(channel)}
      />
    );
  };

  return (
    <aside
      aria-label="Gdzie publikujesz"
      className="flex w-[320px] flex-none flex-col gap-4 overflow-y-auto border-l border-border bg-card px-4 py-3"
    >
      {focusChannel ? <FocusSteps channel={focusChannel} /> : null}

      {state.findings.length > 0 ? (
        <AdChecksPanel
          findings={state.findings}
          busy={locked}
          onShow={onShowFinding}
          onRemove={onRemoveFinding}
        />
      ) : null}

      <div className="flex flex-col gap-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Gdzie publikujesz
        </h2>
        <CareerCard
          highlight={focusChannel === "kariera"}
          career={state.career}
          jobClosed={jobClosed}
          blockedReason={publishBlockedReason}
          publishing={publishingCareer}
          copied={careerCopied}
          onPublish={onPublishCareer}
          onCopy={onCopyCareerLink}
        />
        {reminderLine("kariera")}
        {canRemind ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="self-start"
            loading={remind.isPending}
            onClick={() => setAskingRemind(true)}
            data-testid="ad-remind-recruiters"
          >
            <BellRing className="h-3.5 w-3.5" aria-hidden="true" />
            Przypomnij: {recruiters.map(shortName).join(", ")}
          </Button>
        ) : null}
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Portale
        </h3>
        <p className="text-xs text-muted-foreground">
          Treść do wklejenia jest w zakładkach Pracuj.pl i JustJoin.IT. Po wklejeniu oznacz
          publikację tutaj.
        </p>
        {/* Po wklejeniu treści na portalu rekruter oznacza to tutaj. */}
        <AdPublications
          jobId={jobId}
          portals={["pracuj", "jjit"]}
          state={state}
          jobClosed={jobClosed}
          locked={locked}
          api={api}
          initialLinkFor={focusChannel === "pracuj" || focusChannel === "jjit" ? focusChannel : null}
          renderExtra={(portal) => reminderLine(portal)}
        />
      </div>
      <SkipChannelDialog
        open={skipFor !== null}
        channels={missing}
        initial={skipFor ?? []}
        saving={skip.isPending}
        onSubmit={(channels, reason) => skip.mutate({ channels, reason })}
        onClose={() => setSkipFor(null)}
      />
      <ConfirmV2
        open={askingRemind}
        onOpenChange={setAskingRemind}
        title={`Przypomnieć: ${recruiters.map(shortName).join(", ")}?`}
        description="Dostanie teraz mail z przyciskiem „Opublikuj na stronie kariery”. Codzienne przypomnienie i tak przychodzi rano."
        confirmLabel="Przypomnij"
        onConfirm={() => {
          setAskingRemind(false);
          remind.mutate();
        }}
      />
    </aside>
  );
}
