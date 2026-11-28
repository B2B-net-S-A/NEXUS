"use client";

import { useState } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import type {
  MarketPanelInput,
  MarketTrainerApplication,
  MarketTrainerStatus,
} from "@/lib/api/trainings";
import { formatDateTimePl } from "@/lib/date-pl";
import { safeExternalHref } from "@/lib/safe-href";
import { cn } from "@/lib/utils";

import { MarketPanelDialog } from "./MarketPanelDialog";
import { ToneBadge } from "./TrainingStatus";
import {
  MARKET_STATUSES,
  MARKET_STATUS_LABEL,
  actionsFor,
  countByStatus,
  topicsLine,
  type MarketAction,
} from "./market-trainer-model";
import type { StatusTone } from "./training-model";

const TONES: Record<MarketTrainerStatus, StatusTone> = {
  new: "info",
  interview: "warning",
  accepted: "success",
  rejected: "neutral",
};

/** Link od osoby z internetu: tylko http(s), inaczej sam tekst (`safe-href.ts`). */
function ExternalLink({ href, label }: { href: string | null; label: string }) {
  const safe = safeExternalHref(href);
  if (!href) return null;
  if (!safe) return <span className="break-all text-muted-foreground">{href}</span>;
  return (
    <a
      href={safe}
      target="_blank"
      rel="noreferrer noopener"
      className="break-all text-primary hover:underline"
    >
      {label}
    </a>
  );
}

interface Props {
  applications: MarketTrainerApplication[];
  busy: boolean;
  onChange: (application: MarketTrainerApplication, to: MarketTrainerStatus, note: string) => void;
  /** 0808: otwarcie (albo poprawka) panelu z danymi firmy; `true` = zapisane. */
  onOpenPanel?: (application: MarketTrainerApplication, body: MarketPanelInput) => Promise<boolean>;
  onClosePanel?: (application: MarketTrainerApplication) => void;
}

/** Panel trenera z bazy: stan wejścia, zamówienie szkolenia, dane firmy (0808). */
function PanelRow({
  application,
  busy,
  onEdit,
  onClose,
}: {
  application: MarketTrainerApplication;
  busy: boolean;
  onEdit: () => void;
  onClose?: () => void;
}) {
  const { panel } = application;
  if (!panel.panel_open) {
    return (
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
        <p className="text-xs text-muted-foreground">
          {panel.panel_closed_at ? "Panel zamknięty." : "Panel trenera nie jest jeszcze otwarty."} Trener dostanie
          zamówienia, gdy otworzysz panel z danymi firmy do umowy.
        </p>
        <Button type="button" size="sm" disabled={busy} onClick={onEdit}>
          Otwórz panel trenera
        </Button>
      </div>
    );
  }
  return (
    <div className="mt-3 space-y-2 border-t pt-3">
      <p className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Panel otwarty</span> · {panel.company_name} · NIP{" "}
        {panel.nip} · logowanie: {panel.panel_email}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button asChild size="sm">
          <Link href={`/trainings/new?market=${application.id}`}>Zamów szkolenie</Link>
        </Button>
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onEdit}>
          Zmień dane firmy
        </Button>
        {onClose ? (
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={onClose}>
            Zamknij panel
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function MarketTrainerCandidates({
  applications,
  busy,
  onChange,
  onOpenPanel,
  onClosePanel,
}: Props) {
  const [filter, setFilter] = useState<MarketTrainerStatus>("new");
  const [editing, setEditing] = useState<MarketTrainerApplication | null>(null);
  const { askConfirm, askReason, confirmDialog } = useConfirmV2();
  const counts = countByStatus(applications);
  const shown = applications.filter((application) => application.status === filter);

  const run = async (application: MarketTrainerApplication, action: MarketAction) => {
    const note = await askReason({
      title: action.confirmTitle,
      description: `${application.full_name}. Notatka zostaje przy zgłoszeniu (opcjonalnie).`,
      confirmLabel: action.label,
      variant: action.destructive ? "destructive" : "default",
      field: {
        label: "Notatka",
        placeholder: "np. termin rozmowy albo powód",
        minLength: 0,
        maxLength: 1000,
      },
    });
    if (note === null) return;
    onChange(application, action.to, note);
  };

  return (
    <section aria-labelledby="market-trainers-title" className="space-y-3">
      {confirmDialog}
      {editing && onOpenPanel ? (
        <MarketPanelDialog
          application={editing}
          busy={busy}
          onClose={() => setEditing(null)}
          onSubmit={(body) => {
            void onOpenPanel(editing, body).then((ok) => {
              if (ok) setEditing(null);
            });
          }}
        />
      ) : null}
      <div>
        <h2 id="market-trainers-title" className="text-base font-semibold text-foreground">
          Kandydaci na trenerów z rynku
        </h2>
        <p className="text-sm text-muted-foreground">
          Zgłoszenia ze strony b2bnetwork.pl od osób bez kontraktu. Decydujesz Ty: rozmowa, baza
          trenerów albo odrzucenie. Nic nie wysyłamy automatycznie, kontakt z osobą jest po Twojej
          stronie.
        </p>
      </div>
      <div role="group" aria-label="Filtr statusu" className="flex flex-wrap gap-1.5">
        {MARKET_STATUSES.map((status) => (
          <button
            key={status}
            type="button"
            aria-pressed={filter === status}
            onClick={() => setFilter(status)}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium",
              filter === status
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:bg-accent",
            )}
          >
            {MARKET_STATUS_LABEL[status]}
            <span className="tabular-nums">{counts[status]}</span>
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
          Nic w tym stanie.
        </p>
      ) : (
        <ul className="space-y-3">
          {shown.map((application) => (
            <li key={application.id} className="rounded-lg border border-border bg-card p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-medium text-foreground">{application.full_name}</p>
                  <p className="break-all text-xs text-muted-foreground">
                    {application.email} · zgłoszenie {formatDateTimePl(application.created_at)}
                    {application.submissions > 1
                      ? ` · wysłane ${application.submissions} razy`
                      : ""}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  {application.contract_id !== null ? (
                    <ToneBadge tone="info">nasz konsultant</ToneBadge>
                  ) : null}
                  <ToneBadge tone={TONES[application.status]}>
                    {MARKET_STATUS_LABEL[application.status]}
                  </ToneBadge>
                </div>
              </div>
              <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-xs text-muted-foreground">Tematy</dt>
                  <dd>{topicsLine(application)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted-foreground">Pierwsze szkolenie</dt>
                  <dd>{application.first_training}</dd>
                </div>
                <div className="sm:col-span-2">
                  <dt className="text-xs text-muted-foreground">Doświadczenie trenerskie</dt>
                  <dd className="whitespace-pre-line">{application.experience}</dd>
                </div>
                {application.linkedin ? (
                  <div>
                    <dt className="text-xs text-muted-foreground">LinkedIn albo strona</dt>
                    <dd>
                      <ExternalLink href={application.linkedin} label={application.linkedin} />
                    </dd>
                  </div>
                ) : null}
                {application.sample_url ? (
                  <div>
                    <dt className="text-xs text-muted-foreground">Próbka</dt>
                    <dd>
                      <ExternalLink href={application.sample_url} label="Otwórz nagranie albo program" />
                    </dd>
                  </div>
                ) : null}
                {application.status_note ? (
                  <div className="sm:col-span-2">
                    <dt className="text-xs text-muted-foreground">Notatka</dt>
                    <dd className="whitespace-pre-line">{application.status_note}</dd>
                  </div>
                ) : null}
              </dl>
              {application.status === "accepted" && onOpenPanel ? (
                <PanelRow
                  application={application}
                  busy={busy}
                  onEdit={() => setEditing(application)}
                  onClose={
                    onClosePanel
                      ? () =>
                          void askConfirm({
                            title: "Zamknąć panel trenera?",
                            description: `${application.full_name} nie zaloguje się, a otwarte sesje się zamkną. Szkolenia i pliki zostają.`,
                            confirmLabel: "Zamknij panel",
                            variant: "destructive",
                          }).then((ok) => {
                            if (ok) onClosePanel(application);
                          })
                      : undefined
                  }
                />
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2">
                {actionsFor(application.status).map((action) => (
                  <Button
                    key={action.to}
                    type="button"
                    size="sm"
                    variant={action.destructive ? "outline" : "primary"}
                    disabled={busy}
                    onClick={() => void run(application, action)}
                  >
                    {action.label}
                  </Button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
