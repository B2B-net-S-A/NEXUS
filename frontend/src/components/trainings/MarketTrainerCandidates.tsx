"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import type { MarketTrainerApplication, MarketTrainerStatus } from "@/lib/api/trainings";
import { formatDateTimePl } from "@/lib/date-pl";
import { safeExternalHref } from "@/lib/safe-href";
import { cn } from "@/lib/utils";

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
}

export function MarketTrainerCandidates({ applications, busy, onChange }: Props) {
  const [filter, setFilter] = useState<MarketTrainerStatus>("new");
  const { askReason, confirmDialog } = useConfirmV2();
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
                      ? ` · wysłane ${application.submissions} razy, ostatnio ${formatDateTimePl(application.updated_at)}`
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
