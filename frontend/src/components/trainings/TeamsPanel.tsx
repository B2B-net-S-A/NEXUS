"use client";

import { Copy, ExternalLink, RotateCw, Star } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { TrainingView, TrainingsMe } from "@/lib/api/trainings";
import { formatIsoDatePl } from "@/lib/date-pl";
import { safeExternalHref } from "@/lib/safe-href";

import { rehearsalLabel } from "./training-model";

interface TeamsPanelProps {
  view: Pick<
    TrainingView,
    | "status"
    | "trainer_kind"
    | "join_url"
    | "teams"
    | "files"
    | "published_at"
    | "shared_registered_at"
    | "feedback"
    | "registrations"
    | "payment"
    | "rehearsal"
  >;
  me: Pick<TrainingsMe, "can_manage" | "teams_ready">;
  onRetry: () => Promise<boolean>;
  onShare: (share: boolean) => Promise<boolean>;
  busy?: boolean;
}

const RECORDING_LABEL: Record<string, string> = {
  waiting: "Nagranie wróci z Teams ok. 20 minut po końcu szkolenia.",
  imported: "Nagranie, transkrypt i obecność są już w szkoleniu.",
  none: "Teams nie oddał nagrania. Wgraj je ręcznie, jeśli powstało.",
  failed: "Nie udało się pobrać nagrania z Teams. Wgraj je ręcznie.",
};

const REHEARSAL_LABEL: Record<string, string> = {
  created: "Próba techniczna z prowadzącym",
  failed: "Nie udało się założyć próby technicznej. „Spróbuj ponownie” założy ją razem ze spotkaniem.",
  skipped: "Na próbę techniczną było za późno: termin próby już minął.",
  cancelled: "Próba techniczna odwołana.",
};

function ratingsLabel(count: number): string {
  const last = count % 10;
  const teen = count % 100 >= 12 && count % 100 <= 14;
  if (count === 1) return "1 ocena";
  return `${count} ${last >= 2 && last <= 4 && !teen ? "oceny" : "ocen"}`;
}

/** Spotkanie Teams założone przez NEXUS (0697), nagranie z Teams i oceny uczestników. */
export function TeamsPanel({ view, me, onRetry, onShare, busy }: TeamsPanelProps) {
  const teams = view.teams;
  const link = view.join_url ? safeExternalHref(view.join_url) : null;
  const hasRecording = view.files.some(
    (file) => file.kind === "recording" && file.status === "accepted" && file.for_participants,
  );
  const canShare =
    me.can_manage &&
    view.status === "signed" &&
    hasRecording &&
    !view.published_at &&
    !view.shared_registered_at;
  const feedback = view.feedback;

  const copy = async () => {
    if (!view.join_url) return;
    try {
      await navigator.clipboard.writeText(view.join_url);
    } catch {
      // Schowek bywa zablokowany; link i tak widać obok.
    }
  };

  return (
    <div className="space-y-3 text-sm">
      {teams?.status === "created" ? (
        <p className="text-muted-foreground">
          Spotkanie założył NEXUS w kalendarzu skrzynki szkoleń, z nagrywaniem i transkrypcją od startu.
          Zapisani dostają zaproszenie do kalendarza.
        </p>
      ) : teams?.status === "failed" ? (
        <div role="alert" className="space-y-1 rounded-md border border-destructive/20 bg-destructive-muted px-3 py-2">
          <p className="text-destructive-muted-foreground">Nie udało się założyć albo zmienić spotkania w Teams.</p>
          {me.can_manage ? (
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void onRetry()}>
              <RotateCw className="h-3.5 w-3.5" aria-hidden /> Spróbuj ponownie
            </Button>
          ) : null}
        </div>
      ) : teams?.status === "cancelled" ? (
        <p className="text-muted-foreground">Spotkanie odwołane razem z zaproszeniami.</p>
      ) : me.teams_ready ? (
        <p className="text-muted-foreground">
          {view.trainer_kind === "consultant"
            ? "Spotkanie powstanie po podpisie umowy przez obie strony."
            : "Spotkanie powstanie po zatwierdzeniu szkolenia z datą i godziną."}
        </p>
      ) : (
        <p className="text-muted-foreground">Link do spotkania wkleja się w zamówieniu.</p>
      )}

      {link ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button asChild size="sm" variant="outline">
            <a href={link} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="h-3.5 w-3.5" aria-hidden /> Otwórz w Teams
            </a>
          </Button>
          <Button size="sm" variant="ghost" onClick={() => void copy()}>
            <Copy className="h-3.5 w-3.5" aria-hidden /> Kopiuj link
          </Button>
        </div>
      ) : null}

      {view.rehearsal?.status ? (
        <div className="space-y-1 border-t border-border pt-2" data-testid="teams-rehearsal">
          <p className={view.rehearsal.status === "failed" ? "text-destructive" : "text-muted-foreground"}>
            {REHEARSAL_LABEL[view.rehearsal.status]}
            {view.rehearsal.status === "created" && view.rehearsal.start
              ? `: ${rehearsalLabel(view.rehearsal.start)}, ${view.rehearsal.minutes} min, bez nagrywania.`
              : ""}
          </p>
          {view.rehearsal.status === "failed" && me.can_manage && teams?.status === "created" ? (
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void onRetry()}>
              <RotateCw className="h-3.5 w-3.5" aria-hidden /> Spróbuj ponownie
            </Button>
          ) : null}
        </div>
      ) : null}

      {teams?.recording ? (
        <p className="border-t border-border pt-2 text-muted-foreground">{RECORDING_LABEL[teams.recording]}</p>
      ) : null}

      {view.shared_registered_at ? (
        <div className="space-y-1 border-t border-border pt-2">
          <p>
            Nagranie widzą zapisani ({view.registrations}) od {formatIsoDatePl(view.shared_registered_at.slice(0, 10))}.
          </p>
          {me.can_manage && !view.published_at ? (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => void onShare(false)}>
              Cofnij udostępnienie
            </Button>
          ) : null}
        </div>
      ) : canShare ? (
        <div className="space-y-1 border-t border-border pt-2">
          <Button size="sm" disabled={busy} onClick={() => void onShare(true)}>
            Udostępnij nagranie zapisanym
          </Button>
          <p className="text-xs text-muted-foreground">
            {view.trainer_kind === "consultant" && !view.payment.paid_at
              ? "Przed zapłatą trenera tylko zapisani na to szkolenie (licencja z § 8 ust. 4). Cała biblioteka po zapłacie."
              : "Zapisani zobaczą nagranie od razu, reszta po publikacji w bibliotece."}
          </p>
        </div>
      ) : null}

      {feedback && feedback.count > 0 ? (
        <div className="space-y-1 border-t border-border pt-2">
          <p className="inline-flex items-center gap-1 font-medium">
            <Star className="h-3.5 w-3.5 text-warning" aria-hidden />
            {feedback.average?.toFixed(1).replace(".", ",")} / 5
            <span className="font-normal text-muted-foreground"> · {ratingsLabel(feedback.count)}</span>
          </p>
          {(feedback.comments ?? []).slice(0, 5).map((comment, index) => (
            <p key={index} className="text-xs text-muted-foreground">
              „{comment}”
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}
