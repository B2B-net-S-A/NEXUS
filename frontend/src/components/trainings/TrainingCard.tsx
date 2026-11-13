"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import type {
  AgreementVersion,
  OrderInput,
  TrainingFees,
  TrainingFileRow,
  TrainingPartner,
  TrainingPartnerResponse,
  TrainingPeople,
  TrainingRow,
  TrainingView,
  TrainingsMe,
} from "@/lib/api/trainings";
import { formatIsoDatePl } from "@/lib/date-pl";

import { AgreementPanel } from "./AgreementPanel";
import { HandoverReview } from "./HandoverReview";
import { OrderFields } from "./OrderFields";
import { PeoplePanel } from "./PeoplePanel";
import { PublishPanel } from "./PublishPanel";
import { TeamsPanel } from "./TeamsPanel";
import { QuoteTable } from "./QuoteTable";
import { TrainingFilesPanel } from "./TrainingFilesPanel";
import { TrainingStatusBadge, TrainingSteps } from "./TrainingStatus";
import {
  CANCELLABLE,
  EDITABLE_ORDER,
  chapterTime,
  deliverablesFromOrder,
  deliverablesPayload,
  formatAmount,
  handoverSummary,
  orderFormProblem,
  orderFromView,
  trainingSteps,
  type DeliverableDraft,
} from "./training-model";

/** Każda akcja zwraca `true`, gdy serwer ją przyjął; błąd pokazuje kontener. */
export interface TrainingCardActions {
  saveOrder: (input: OrderInput) => Promise<boolean>;
  send: () => Promise<boolean>;
  cancel: (reason: string) => Promise<boolean>;
  returnQuote: (note: string) => Promise<boolean>;
  acceptQuote: () => Promise<boolean>;
  generateAgreement: (input: { partner: TrainingPartner; company_email: string }) => Promise<boolean>;
  companySign: (file: File) => Promise<boolean>;
  downloadAgreement: (version: AgreementVersion) => void;
  downloadFile: (file: TrainingFileRow) => void;
  reviewFile: (input: { fileId: number; accept: boolean; note: string }) => Promise<boolean>;
  toggleParticipants: (input: { fileId: number; value: boolean }) => Promise<boolean>;
  uploadFile: (input: {
    kind: "recording" | "internal";
    file: File;
    onProgress: (fraction: number) => void;
  }) => Promise<boolean>;
  mediaUrl: (file: TrainingFileRow) => Promise<string | null>;
  markPaid: (paid: boolean) => Promise<boolean>;
  publish: (publish: boolean) => Promise<boolean>;
  importAttendance: (file: File) => Promise<boolean>;
  /** 0697: ponowienie spotkania Teams i udostępnienie nagrania zapisanym. */
  retryTeams?: () => Promise<boolean>;
  shareRegistered?: (share: boolean) => Promise<boolean>;
}

export interface TrainingCardProps {
  view: TrainingView;
  me: TrainingsMe;
  /** Dzień firmy `RRRR-MM-DD` (pasek kroków: przed albo po szkoleniu). */
  today: string;
  previous?: { row: TrainingRow; fees: TrainingFees } | null;
  partner?: TrainingPartnerResponse;
  partnerError?: string | null;
  people?: TrainingPeople;
  peopleError?: string | null;
  peopleLoading?: boolean;
  actions: TrainingCardActions;
  busy?: boolean;
}

function Section({
  title,
  children,
  actions,
}: {
  title: string;
  children: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <Card size="sm" className="space-y-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">{title}</h2>
        {actions}
      </div>
      {children}
    </Card>
  );
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm text-foreground">{value || "—"}</dd>
    </div>
  );
}

function when(view: TrainingView): string {
  const { session_date, time_from, time_to } = view.order;
  if (!session_date) return "termin do ustalenia";
  const hours = time_from ? ` · ${time_from}${time_to ? `–${time_to}` : ""}` : "";
  return `${formatIsoDatePl(session_date)}${hours}`;
}

function OrderSection({
  view,
  canManage,
  actions,
  busy,
  teamsReady = false,
}: {
  view: TrainingView;
  canManage: boolean;
  actions: TrainingCardActions;
  busy?: boolean;
  teamsReady?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [order, setOrder] = useState<OrderInput>(() => orderFromView(view));
  const [drafts, setDrafts] = useState<DeliverableDraft[]>(() =>
    deliverablesFromOrder(view.order.deliverables),
  );
  const [problem, setProblem] = useState<string | null>(null);
  const employee = view.trainer_kind === "employee";
  // Szkolenie pracownika nie ma umowy, więc można je przełożyć także po zatwierdzeniu
  // (spotkanie i zaproszenia przesuwają się same, 0697).
  const editable =
    canManage &&
    (EDITABLE_ORDER.includes(view.status) || (view.status === "signed" && view.trainer_kind === "employee"));

  const startEdit = () => {
    setOrder(orderFromView(view));
    setDrafts(deliverablesFromOrder(view.order.deliverables));
    setProblem(null);
    setEditing(true);
  };

  const save = async () => {
    const issue = orderFormProblem(order, employee ? [] : drafts);
    setProblem(issue);
    if (issue) return;
    const ok = await actions.saveOrder({
      ...order,
      deliverables: employee ? [] : deliverablesPayload(drafts),
    });
    if (ok) setEditing(false);
  };

  return (
    <Section
      title="Zamówienie"
      actions={
        editable && !editing ? (
          <Button size="sm" variant="outline" onClick={startEdit}>
            Edytuj zamówienie
          </Button>
        ) : null
      }
    >
      {editing ? (
        <div className="space-y-3">
          <OrderFields
            value={order}
            onChange={setOrder}
            deliverables={drafts}
            onDeliverablesChange={setDrafts}
            disabled={busy}
            employee={employee}
            teamsReady={teamsReady}
          />
          {problem ? (
            <p role="alert" className="text-sm text-destructive">
              {problem}
            </p>
          ) : null}
          <div className="flex gap-2">
            <Button size="sm" disabled={busy} onClick={save}>
              Zapisz zamówienie
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Anuluj edycję
            </Button>
          </div>
        </div>
      ) : (
        <>
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Fact label="Termin" value={when(view)} />
            <Fact
              label="Czas"
              value={view.order.duration_minutes ? `${view.order.duration_minutes} min` : null}
            />
            <Fact label="Platforma" value={view.order.platform} />
            <Fact label="Uczestników" value={view.order.expected_participants} />
            <Fact label="Limit miejsc" value={view.order.seat_limit ? String(view.order.seat_limit) : "bez limitu"} />
            {employee ? null : (
              <Fact label="Wycena do" value={view.order.quote_due_on ? formatIsoDatePl(view.order.quote_due_on) : null} />
            )}
            <Fact label="Temat" value={view.order.topic} />
          </dl>
          {view.order.description ? (
            <p className="whitespace-pre-line text-sm text-foreground">{view.order.description}</p>
          ) : null}
          {employee ? null : (
            <div>
              <p className="text-xs text-muted-foreground">Pliki do przekazania (Zał. 1 pkt 4)</p>
              {view.order.deliverables.length === 0 ? (
                <p className="text-sm text-muted-foreground">Nie zaznaczono plików.</p>
              ) : (
                <ul className="mt-1 space-y-0.5 text-sm">
                  {view.order.deliverables.map((item) => (
                    <li key={item.key}>
                      {item.label}
                      <span className="text-muted-foreground">
                        {item.format ? ` · ${item.format}` : ""}
                        {item.due_days !== null ? ` · ${item.due_days} dni po` : ""}
                        {item.required ? "" : " · opcjonalne"}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {canManage && view.status === "draft" ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" disabled={busy} onClick={() => actions.send()}>
                {employee ? "Zatwierdź szkolenie" : "Wyślij zamówienie trenerowi"}
              </Button>
              <span className="text-xs text-muted-foreground">
                {employee
                  ? "Szkolenie pracownika nie ma umowy: po zatwierdzeniu otwierają się zapisy."
                  : "Trener zobaczy zamówienie w panelu konsultanta i przygotuje wycenę A–E."}
              </span>
            </div>
          ) : null}
        </>
      )}
    </Section>
  );
}

function QuoteSection({
  view,
  canManage,
  previous,
  actions,
  busy,
  askReason,
}: {
  view: TrainingView;
  canManage: boolean;
  previous: TrainingCardProps["previous"];
  actions: TrainingCardActions;
  busy?: boolean;
  askReason: ReturnType<typeof useConfirmV2>["askReason"];
}) {
  const { quote, fees } = view;
  return (
    <Section title="Wycena trenera">
      {view.status === "ordered" && !quote.quoted_at ? (
        <p className="text-sm text-muted-foreground">Trener jeszcze nie przysłał wyceny.</p>
      ) : null}
      {quote.return_note && view.status === "returned" ? (
        <p className="rounded-md bg-muted px-3 py-2 text-sm">
          Odesłane z uwagą: {quote.return_note}
        </p>
      ) : null}
      {fees ? (
        <QuoteTable
          fees={fees}
          previousFees={previous?.fees ?? null}
          previous={previous?.row ?? null}
        />
      ) : (
        <p className="text-sm text-muted-foreground">Kwot nie pokazujemy w tym widoku.</p>
      )}
      {quote.agenda.length > 0 ? (
        <div>
          <p className="text-xs text-muted-foreground">Agenda</p>
          <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-sm">
            {quote.agenda.map((item, index) => (
              <li key={`${item.title}-${index}`}>
                {item.title}
                {item.minutes ? <span className="text-muted-foreground"> · {item.minutes} min</span> : null}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      <dl className="grid gap-3 sm:grid-cols-2">
        <Fact label="Materiały własne trenera" value={quote.own_materials || "brak"} />
        <Fact label="Materiały osób trzecich" value={quote.third_party_materials || "brak"} />
      </dl>
      {quote.quote_note ? <Fact label="Uwagi trenera" value={quote.quote_note} /> : null}
      {canManage && view.status === "quoted" ? (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" disabled={busy} onClick={() => actions.acceptQuote()}>
            Akceptuję, przygotuj umowę
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={async () => {
              const note = await askReason({
                title: "Odeślij wycenę z uwagą",
                description: "Trener poprawi wycenę w panelu i wyśle ją ponownie.",
                confirmLabel: "Odeślij",
                field: { label: "Co poprawić", minLength: 3, maxLength: 3000 },
              });
              if (note) await actions.returnQuote(note);
            }}
          >
            Odeślij z uwagą
          </Button>
        </div>
      ) : null}
    </Section>
  );
}

/** Karta szkolenia po stronie TCM, Finansów i reprezentanta B2B Network. */
export function TrainingCard({
  view,
  me,
  today,
  previous = null,
  partner,
  partnerError = null,
  people,
  peopleError = null,
  peopleLoading,
  actions,
  busy,
}: TrainingCardProps) {
  const { askReason, confirmDialog } = useConfirmV2();
  const steps = trainingSteps(view, today);
  const consultant = view.trainer_kind === "consultant";
  const signed = view.status === "signed";
  const summary = handoverSummary(view);
  const canCancel = me.can_manage && CANCELLABLE.includes(view.status);
  const showQuote = consultant && view.status !== "draft";
  const showAgreement =
    consultant && ["accepted", "trainer_signed", "signed"].includes(view.status);

  const cancel = async () => {
    const reason = await askReason({
      title: "Anulować szkolenie?",
      description: "Trener dostanie informację w panelu. Tego nie da się cofnąć.",
      confirmLabel: "Anuluj szkolenie",
      cancelLabel: "Zostaw",
      variant: "destructive",
      field: { label: "Powód (opcjonalnie)", maxLength: 2000 },
    });
    if (reason !== null) await actions.cancel(reason);
  };

  const planning = (
    <>
      <OrderSection
        view={view}
        canManage={me.can_manage}
        actions={actions}
        busy={busy}
        teamsReady={me.teams_ready === true}
      />
      {showQuote ? (
        <QuoteSection
          view={view}
          canManage={me.can_manage}
          previous={previous}
          actions={actions}
          busy={busy}
          askReason={askReason}
        />
      ) : null}
      {showAgreement ? (
        <Section title="Umowa szkoleniowa">
          <AgreementPanel
            view={view}
            canManage={me.can_manage}
            isCompanySigner={me.is_company_signer}
            partner={partner}
            partnerError={partnerError}
            onDownload={actions.downloadAgreement}
            onGenerate={actions.generateAgreement}
            onCompanySign={actions.companySign}
            busy={busy}
          />
        </Section>
      ) : null}
    </>
  );
  const delivery = (
    <>
      {consultant && signed ? (
        <Section
          title="Przekazanie plików"
          actions={
            <span className="text-xs text-muted-foreground">
              Przyjęte {summary.accepted} z {summary.required} wymaganych
            </span>
          }
        >
          <HandoverReview
            items={view.handover}
            canManage={me.can_manage}
            onDownload={actions.downloadFile}
            onReview={actions.reviewFile}
            busy={busy}
          />
        </Section>
      ) : null}
      {signed ? (
        <Section title="Pliki, nagranie i materiały">
          <TrainingFilesPanel
            files={view.files}
            canManage={me.can_manage}
            onDownload={actions.downloadFile}
            onToggleParticipants={actions.toggleParticipants}
            onUpload={actions.uploadFile}
            getMediaUrl={actions.mediaUrl}
            busy={busy}
          />
        </Section>
      ) : null}
      {signed && me.can_manage ? (
        <Section title="Zapisy i obecność">
          <PeoplePanel
            people={people}
            error={peopleError}
            loading={peopleLoading}
            canManage={me.can_manage}
            onImport={actions.importAttendance}
            busy={busy}
          />
        </Section>
      ) : null}
    </>
  );

  return (
    <div className="space-y-4">
      {confirmDialog}
      <header className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-foreground">{view.order.title}</h1>
            <p className="text-sm text-muted-foreground">
              {view.trainer_name || "trener bez nazwiska"} ·{" "}
              {consultant ? "konsultant z umową B2B" : "pracownik"} · {when(view)}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <TrainingStatusBadge status={view.status} label={view.status_label} />
            {canCancel ? (
              <Button size="sm" variant="quiet" disabled={busy} onClick={cancel}>
                Anuluj szkolenie
              </Button>
            ) : null}
          </div>
        </div>
        <TrainingSteps steps={steps} />
        {view.status === "cancelled" ? (
          <p className="rounded-md border border-destructive/20 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground">
            Anulowane{view.cancel_reason ? `: ${view.cancel_reason}` : "."}
          </p>
        ) : null}
      </header>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-4">
          {signed ? (
            <>
              {delivery}
              {planning}
            </>
          ) : (
            <>
              {planning}
              {delivery}
            </>
          )}
        </div>

        <aside className="min-w-0 space-y-4">
          {signed || view.teams?.status ? (
            <Section title="Spotkanie w Teams">
              <TeamsPanel
                view={view}
                me={me}
                onRetry={actions.retryTeams ?? (async () => false)}
                onShare={actions.shareRegistered ?? (async () => false)}
                busy={busy}
              />
            </Section>
          ) : null}
          {signed ? (
            <Section title={consultant ? "Zapłata i biblioteka" : "Biblioteka"}>
              <PublishPanel
                view={view}
                me={me}
                onPaid={actions.markPaid}
                onPublish={actions.publish}
                busy={busy}
              />
            </Section>
          ) : null}
          <Section title="W skrócie">
            <dl className="grid grid-cols-2 gap-3">
              <Fact label="Zapisani" value={String(view.registrations)} />
              <Fact label="Obecni (Teams)" value={String(view.attendance)} />
              {consultant ? (
                <Fact label="Kontrakt" value={view.trainer_contract_id ? `#${view.trainer_contract_id}` : null} />
              ) : null}
              {view.fees?.total ? (
                <Fact label="Razem netto" value={`${formatAmount(Number(view.fees.total))} zł`} />
              ) : null}
            </dl>
            {consultant ? (
              <p className="border-t border-border pt-2 text-xs text-muted-foreground">
                Kwoty widzą TCM, Finanse i admin. Rekruter i DL ich nie widzą, tak jak stawek.
              </p>
            ) : null}
          </Section>
          {view.chapters.length > 0 ? (
            <Section title="Rozdziały nagrania">
              <ol className="space-y-1 text-sm">
                {view.chapters.map((chapter, index) => (
                  <li key={`${chapter.title}-${index}`} className="flex gap-3">
                    <span className="w-12 shrink-0 tabular-nums text-muted-foreground">
                      {chapterTime(chapter.start_minute)}
                    </span>
                    <span>{chapter.title}</span>
                  </li>
                ))}
              </ol>
            </Section>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
