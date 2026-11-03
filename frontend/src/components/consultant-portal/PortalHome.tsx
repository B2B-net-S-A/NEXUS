"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CalendarClock, ChevronRight, Mail, Search, Video } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  portalApi,
  portalKeys,
  usePortalQuery,
  type PortalCase,
  type PortalMe,
  type PortalMeeting,
  type PortalRatingInput,
} from "@/lib/api/consultant-portal";

import { BookingDialog } from "./BookingDialog";
import { FinanceSection } from "./FinanceSection";
import { NewCaseDialog } from "./NewCaseDialog";
import { formatDay, groupFaq, slotLabel } from "./portal-model";
import { RatingFields } from "./RatingFields";

const WAITING_TONE: Record<PortalCase["waiting"]["who"], "warning" | "info" | "neutral" | "success"> = {
  other: "warning",
  us: "info",
  nobody: "neutral",
  done: "success",
};

function FaqSection({ me }: { me: PortalMe }) {
  const [query, setQuery] = useState("");
  const faq = usePortalQuery(portalKeys.faq, portalApi.faq);
  const groups = faq.isSuccess ? groupFaq(faq.data.items, me.topics, query) : [];
  return (
    <section className="rounded-xl border bg-card p-4">
      <div className="relative">
        <Search aria-hidden className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          aria-label="Szukaj w pytaniach"
          placeholder="W czym możemy pomóc?"
          className="pl-9"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      {faq.isLoading ? <p className="mt-3 text-sm text-muted-foreground">Wczytujemy pytania…</p> : null}
      {faq.isError ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {apiErrorMessage(faq.error, "Nie udało się wczytać pytań. Odśwież stronę.")}
        </p>
      ) : null}
      {faq.isSuccess && groups.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">
          {query ? "Nic nie pasuje. Napisz do nas przez nowe zgłoszenie." : "Pytania wkrótce tu będą."}
        </p>
      ) : null}
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {groups.map((group) => (
          <div key={group.key} className="rounded-lg border p-3">
            <p className="text-sm font-medium">{group.label}</p>
            <ul className="mt-1.5 space-y-1">
              {group.items.map((item) => (
                <li key={item.id}>
                  <details className="group text-sm">
                    <summary className="flex cursor-pointer list-none items-start gap-1 text-muted-foreground">
                      <ChevronRight aria-hidden className="mt-0.5 size-3.5 shrink-0 transition-transform group-open:rotate-90" />
                      {item.question}
                    </summary>
                    <p className="mt-1 whitespace-pre-line pl-[18px]">{item.answer}</p>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}

function CasesSection() {
  const cases = usePortalQuery(portalKeys.cases, portalApi.cases);
  return (
    <section className="rounded-xl border bg-card p-4">
      <h2 className="text-sm font-semibold">Twoje sprawy</h2>
      {cases.isLoading ? <p className="mt-2 text-sm text-muted-foreground">Wczytujemy…</p> : null}
      {cases.isError ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {apiErrorMessage(cases.error, "Nie udało się wczytać spraw. Odśwież stronę.")}
        </p>
      ) : null}
      {cases.isSuccess && cases.data.items.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">Nie masz otwartych spraw.</p>
      ) : null}
      {cases.isSuccess ? (
        <ul className="mt-2 space-y-2">
          {cases.data.items.map((row) => (
            <li key={row.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-muted px-3 py-2.5 text-sm">
              <span className="min-w-0">
                <span className="block font-medium">{row.title}</span>
                <span className="block text-xs text-muted-foreground">Zgłoszono {formatDay(row.created_at)}</span>
              </span>
              <Badge variant={WAITING_TONE[row.waiting.who]} size="sm">
                {row.waiting.label}
              </Badge>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function RateDialog({ meeting, onClose }: { meeting: PortalMeeting; onClose: () => void }) {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (input: PortalRatingInput) => {
    setBusy(true);
    setError(null);
    try {
      await portalApi.rateMeeting(meeting.id, input);
      await client.invalidateQueries({ queryKey: portalKeys.meetings });
      onClose();
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się zapisać oceny. Spróbuj ponownie."));
    } finally {
      setBusy(false);
    }
  };
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={meeting.host ? `Jak oceniasz rozmowę? (${meeting.host})` : "Jak oceniasz rozmowę?"}
    >
      <RatingFields busy={busy} error={error} onSubmit={submit} />
    </AppModal>
  );
}

function MeetingsSection({ data, isError, error }: { data?: PortalMeeting[]; isError: boolean; error: unknown }) {
  const client = useQueryClient();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [rating, setRating] = useState<PortalMeeting | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const cancel = async (meeting: PortalMeeting) => {
    const yes = await askConfirm({
      title: "Odwołać rozmowę?",
      description: `${meeting.topic_label}, ${slotLabel(meeting.start_at)}. Osoba prowadząca dostanie odwołanie.`,
      confirmLabel: "Odwołaj",
      cancelLabel: "Zostaw",
      variant: "destructive",
    });
    if (!yes) return;
    setFailure(null);
    try {
      await portalApi.cancelMeeting(meeting.id);
      await client.invalidateQueries({ queryKey: portalKeys.meetings });
    } catch (issue) {
      setFailure(apiErrorMessage(issue, "Nie udało się odwołać rozmowy. Spróbuj ponownie za chwilę."));
    }
  };

  if (isError) {
    return (
      <p role="alert" className="text-sm text-destructive">
        {apiErrorMessage(error, "Nie udało się wczytać rozmów. Odśwież stronę.")}
      </p>
    );
  }
  if (!data || data.length === 0) return null;
  return (
    <section className="rounded-xl border bg-card p-4">
      <h2 className="text-sm font-semibold">Twoje rozmowy</h2>
      <ul className="mt-2 divide-y text-sm">
        {data.map((meeting) => (
          <li key={meeting.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
            <span className="min-w-0">
              <span className="block font-medium">
                {meeting.topic_label}
                {meeting.status === "cancelled" ? " (odwołana)" : ""}
              </span>
              <span className="block text-xs text-muted-foreground">
                {slotLabel(meeting.start_at)}
                {meeting.host ? ` · ${meeting.host}` : ""}
              </span>
            </span>
            <span className="flex flex-wrap gap-2">
              {meeting.join_url ? (
                <Button size="sm" asChild>
                  <a href={meeting.join_url} target="_blank" rel="noreferrer">
                    <Video aria-hidden className="size-3.5" /> Dołącz
                  </a>
                </Button>
              ) : null}
              {meeting.can_cancel ? (
                <Button size="sm" variant="outline" onClick={() => cancel(meeting)}>
                  Odwołaj
                </Button>
              ) : null}
              {meeting.can_rate ? (
                <Button size="sm" variant="outline" onClick={() => setRating(meeting)}>
                  Oceń
                </Button>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
      {failure ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {failure}
        </p>
      ) : null}
      {rating ? <RateDialog meeting={rating} onClose={() => setRating(null)} /> : null}
      {confirmDialog}
    </section>
  );
}

export function PortalHome({ me }: { me: PortalMe }) {
  const [dialog, setDialog] = useState<"booking" | "case" | null>(null);
  const meetings = usePortalQuery(portalKeys.meetings, portalApi.meetings);
  return (
    <>
      <section>
        <h1 className="text-2xl font-semibold">{me.first_name ? `Cześć, ${me.first_name}` : "Cześć"}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {[
            me.client,
            me.since ? `z nami od ${formatDay(me.since)}` : null,
            me.until ? `umowa do ${formatDay(me.until)}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </section>
      <FaqSection me={me} />
      <section>
        <h2 className="mb-2 text-sm font-semibold">Porozmawiaj z nami</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-xl border border-primary bg-card p-4 ring-1 ring-primary">
            <CalendarClock aria-hidden className="size-5 text-primary" />
            <p className="mt-2 font-medium">Umów rozmowę</p>
            <p className="text-xs text-muted-foreground">Wybierasz osobę i godzinę, rozmowa w Teams, 20 min.</p>
            <Button size="sm" className="mt-3 w-full" onClick={() => setDialog("booking")}>
              Wybierz termin
            </Button>
          </div>
          <div className="rounded-xl border bg-card p-4">
            <Mail aria-hidden className="size-5 text-primary" />
            <p className="mt-2 font-medium">Napisz</p>
            {me.support_email ? <p className="break-all text-sm font-semibold">{me.support_email}</p> : null}
            <p className="text-xs text-muted-foreground">
              Jeden adres do wszystkiego: faktury, umowa, sprzęt. Sami przekażemy sprawę właściwej osobie.
            </p>
            <Button size="sm" variant="outline" className="mt-3 w-full" onClick={() => setDialog("case")}>
              Nowe zgłoszenie
            </Button>
          </div>
        </div>
      </section>
      <FinanceSection supportEmail={me.support_email} />
      <CasesSection />
      <MeetingsSection data={meetings.data?.items} isError={meetings.isError} error={meetings.error} />
      {dialog === "booking" ? (
        <BookingDialog me={me} note={meetings.data?.note ?? null} onClose={() => setDialog(null)} />
      ) : null}
      {dialog === "case" ? <NewCaseDialog me={me} onClose={() => setDialog(null)} /> : null}
    </>
  );
}
