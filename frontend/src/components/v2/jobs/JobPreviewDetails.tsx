"use client";

/**
 * Szczegóły rekrutacji w Podglądzie listy (02.10.2026). Wiersz listy pokazuje
 * tylko nazwę stanowiska, kategorię, klienta i tryb pracy — wymagania, nazwa
 * od klienta, numery, miasta, data otwarcia i podobne rekrutacje stoją tutaj.
 *
 * Czyta WIERSZ listy (`GET /api/jobs`), więc nie wysyła własnych zapytań
 * i pokazuje pola takie, jakie przyszły z serwera — bez własnego skracania.
 */
import { Copy } from "lucide-react";
import type { ReactNode } from "react";

import { useToast } from "@/components/Toast";
import {
  SimilarJobsCell,
  hasSimilarJobs,
  jobOpenedDate,
  type JobListRowFields,
  type JobSimilarSummary,
} from "@/components/v2/jobs/JobListCells";
import { copyTextToClipboard } from "@/lib/clipboard";
import { jobWorkModeFull, type JobRowSource } from "@/lib/job-row-summary";
import { extractSkills } from "@/lib/job-skills";
import { formatDate } from "@/lib/utils";

const MAX_REQUIREMENTS = 8;

export interface JobPreviewDetailsJob extends JobRowSource, JobListRowFields {
  reference_number?: string | null;
  similar?: JobSimilarSummary | null;
}

const SECTION_LABEL =
  "text-[11px] font-semibold uppercase tracking-wide text-muted-foreground";

function clean(value: string | null | undefined): string | null {
  return value?.trim() || null;
}

export function JobPreviewDetails({
  job,
  onSimilar,
  extra,
}: {
  job: JobPreviewDetailsJob;
  /** Otwiera okno „Podobne rekrutacje” tej rekrutacji. */
  onSimilar: () => void;
  /** Dodatkowe plakietki pod sekcjami (Priority Work); puste = nic. */
  extra?: ReactNode;
}) {
  const { showSuccess, showError } = useToast();
  const requirements = extractSkills(job.must_skills);
  const clientTitle = clean(job.title);
  const clientReference = clean(job.client_reference);
  const ourReference = clean(job.reference_number);
  const workMode = jobWorkModeFull(job);
  const opened = jobOpenedDate(job);
  const hasFacts =
    clientTitle || clientReference || ourReference || workMode || opened;
  const similar = hasSimilarJobs(job.similar);

  if (requirements.length === 0 && !hasFacts && !similar && !extra) return null;

  const copyReference = async () => {
    if (!clientReference) return;
    if (await copyTextToClipboard(clientReference)) {
      showSuccess("Skopiowano numer u klienta");
    } else {
      showError("Nie udało się skopiować numeru — zaznacz go i skopiuj ręcznie.");
    }
  };

  return (
    <div
      className="space-y-3 border-b border-border pb-3"
      data-testid="job-preview-details"
    >
      {requirements.length > 0 && (
        <section className="space-y-1.5">
          <h3 className={SECTION_LABEL}>Wymagania</h3>
          <ul className="flex flex-wrap gap-1.5">
            {requirements.slice(0, MAX_REQUIREMENTS).map((name) => (
              <li
                key={name}
                className="rounded-md border border-border px-2 py-0.5 text-xs leading-snug text-foreground"
              >
                {name}
              </li>
            ))}
            {requirements.length > MAX_REQUIREMENTS && (
              <li className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                +{requirements.length - MAX_REQUIREMENTS}
              </li>
            )}
          </ul>
        </section>
      )}

      {hasFacts && (
        <section className="space-y-1.5">
          <h3 className={SECTION_LABEL}>Nazwy i numery</h3>
          <dl className="grid grid-cols-[minmax(0,116px)_minmax(0,1fr)] items-baseline gap-x-3 gap-y-1 text-xs">
            {clientTitle && (
              <>
                <dt className="text-muted-foreground">Nazwa od klienta</dt>
                <dd className="break-words text-foreground">{clientTitle}</dd>
              </>
            )}
            {clientReference && (
              <>
                <dt className="text-muted-foreground">Numer u klienta</dt>
                <dd className="flex min-w-0 items-center gap-1 text-foreground">
                  <span className="min-w-0 break-all font-mono">{clientReference}</span>
                  <button
                    type="button"
                    onClick={copyReference}
                    aria-label="Kopiuj numer u klienta"
                    className="hit-area shrink-0 rounded-md p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <Copy className="h-3 w-3" />
                  </button>
                </dd>
              </>
            )}
            {ourReference && (
              <>
                <dt className="text-muted-foreground">Nasz numer</dt>
                <dd className="break-all font-mono text-foreground">{ourReference}</dd>
              </>
            )}
            {workMode && (
              <>
                <dt className="text-muted-foreground">Tryb pracy</dt>
                <dd className="break-words text-foreground">{workMode}</dd>
              </>
            )}
            {opened && (
              <>
                <dt className="text-muted-foreground">Otwarta</dt>
                <dd className="tabular-nums text-foreground">{formatDate(opened)}</dd>
              </>
            )}
          </dl>
        </section>
      )}

      {similar && (
        <section className="space-y-1.5">
          <h3 className={SECTION_LABEL}>Podobne rekrutacje</h3>
          <SimilarJobsCell similar={job.similar} onOpen={onSimilar} />
        </section>
      )}

      {extra}
    </div>
  );
}
