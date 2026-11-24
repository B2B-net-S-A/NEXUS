"use client";

import { CalendarRange } from "lucide-react";

import {
  classifyJobDeadline,
  deadlineRelativeLabel,
  formatDeadlineTime,
  type DeadlineUrgency,
} from "@/lib/job-deadline";
import { formatDayMonthPl, formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

/**
 * „Dodana → Termin” w nagłówku rekrutacji, obok Klient · Budżet · Tryb pracy
 * (decyzja Artura 19.11.2026, makieta wariant B). Jedna pigułka, bo przy
 * 1280 px linia faktów ma 0–155 px wolnego, a dwie pełne pigułki to ok. 400 px.
 * Pełne daty (z rokiem i godziną) są w dymku.
 */
export interface JobDatesSource {
  /** `opened_at`, a bez niej `created_at` — ta sama data co kolumna „Otwarta” listy. */
  opened_effective_at?: string | null;
  opened_at?: string | null;
  created_at?: string | null;
  deadline?: string | null;
  deadline_time?: string | null;
  deadline_not_provided?: boolean | null;
}

interface JobDatesFactProps {
  job: JobDatesSource;
  /** Parametr dla testów — domyślnie teraz. */
  now?: Date;
}

/** Po terminie zawsze czerwone (decyzja Artura 19.11.2026), ≤ 7 dni pomarańczowe. */
const TONE_TEXT: Record<DeadlineUrgency, string> = {
  overdue: "text-destructive",
  soon: "text-warning-muted-foreground",
  normal: "text-muted-foreground",
  none: "text-muted-foreground",
};

/**
 * „po terminie 1 dz.” poniżej szerokości nagłówka 86rem (19.11.2026): przy 1280 px pełne „po
 * terminie 1 dzień” ścinało tryb pracy do „H…”. Pełne zdanie zostaje w dymku.
 */
function shortRelative(daysLeft: number | null): string | null {
  return daysLeft != null && daysLeft < 0 ? `po terminie ${-daysLeft} dz.` : null;
}

export function jobAddedAt(job: JobDatesSource): string | null {
  return job.opened_effective_at ?? job.opened_at ?? job.created_at ?? null;
}

export function JobDatesFact({ job, now = new Date() }: JobDatesFactProps) {
  const added = jobAddedAt(job);
  const info = classifyJobDeadline(job.deadline, now);
  const relative = deadlineRelativeLabel(info);
  const relativeShort = shortRelative(info.daysLeft);
  const time = formatDeadlineTime(job.deadline_time);
  // Godzina w pigułce tylko dziś i jutro — wtedy decyduje; zawsze jest w dymku.
  const showTime = time != null && info.daysLeft != null && info.daysLeft >= 0 && info.daysLeft <= 1;
  const hasDeadline = info.daysLeft != null && job.deadline != null;
  const missing = job.deadline_not_provided ? "klient nie podał" : "nie podano";

  const addedText = added ? formatIsoDatePl(added) : "nie podano";
  const deadlineText = hasDeadline
    ? `${formatIsoDatePl(job.deadline)}${time ? `, ${time}` : ""} (${relative})`
    : missing;
  const title = `Dodana: ${addedText}\nTermin: ${deadlineText}`;

  return (
    <span
      className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-primary/20 bg-primary/5 px-2.5 text-[13px] font-semibold text-foreground"
      title={title}
      aria-label={`Dodana: ${addedText}. Termin: ${deadlineText}`}
      role="note"
      data-testid="job-header-dates"
      data-tour="job.header-dates"
      data-urgency={info.urgency}
    >
      <CalendarRange className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
      <span aria-hidden="true">{added ? formatDayMonthPl(added) : "—"}</span>
      <span className="font-normal text-muted-foreground" aria-hidden="true">
        →
      </span>
      {hasDeadline ? (
        <>
          <span aria-hidden="true">
            {formatDayMonthPl(job.deadline)}
            {showTime ? `, ${time}` : null}
          </span>
          <span
            className={cn("text-xs font-medium", TONE_TEXT[info.urgency])}
            aria-hidden="true"
            data-testid="job-header-dates-relative"
          >
            ·{" "}
            {relativeShort ? (
              <>
                <span className="@min-[86rem]/job-header:hidden">{relativeShort}</span>
                <span className="hidden @min-[86rem]/job-header:inline">{relative}</span>
              </>
            ) : (
              relative
            )}
          </span>
        </>
      ) : (
        <span className="font-normal text-muted-foreground" aria-hidden="true">
          {missing}
        </span>
      )}
    </span>
  );
}
