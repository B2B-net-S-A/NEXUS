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
 */

import { Copy, ExternalLink } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { AdCareerState, AdFinding, JobAdState } from "@/lib/api/jobAd";
import { formatDate } from "@/lib/utils";

import { AdChecksPanel } from "./AdChecksPanel";
import { AdPublications, type AdPublicationsApi } from "./AdPublications";

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
}

function careerNote(career: AdCareerState): string | null {
  if (career.status === "none" || !career.published_at) return null;
  const who = career.published_by_name ? ` · ${career.published_by_name}` : "";
  return `Opublikowane ${formatDate(career.published_at)}${who}`;
}

function CareerCard({
  career,
  jobClosed,
  blockedReason,
  publishing,
  copied,
  onPublish,
  onCopy,
}: {
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
      className="flex flex-col gap-2 rounded-md border border-border bg-card px-3 py-2.5 text-[13px]"
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
}: AdChannelsProps) {
  return (
    <aside
      aria-label="Gdzie publikujesz"
      className="flex w-[320px] flex-none flex-col gap-4 overflow-y-auto border-l border-border bg-card px-4 py-3"
    >
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
          career={state.career}
          jobClosed={jobClosed}
          blockedReason={publishBlockedReason}
          publishing={publishingCareer}
          copied={careerCopied}
          onPublish={onPublishCareer}
          onCopy={onCopyCareerLink}
        />
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
        />
      </div>
    </aside>
  );
}
