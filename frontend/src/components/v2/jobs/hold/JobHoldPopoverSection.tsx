"use client";

import { useId, useState } from "react";
import { Pause, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { formatDayMonthPl } from "@/lib/date-pl";
import {
  HOLD_NOTE_MAX,
  holdReviewText,
  holdSinceText,
  shortName,
  stateLabelOf,
  type HoldView,
  type JobHold,
} from "@/lib/job-hold";

export interface JobHoldPopoverSectionProps {
  /** `GET …/hold`; `null` = jeszcze nie ma (albo błąd) — sekcja mówi tylko stan. */
  hold: JobHold | null | undefined;
  /** Widok wstrzymania (z `hold` albo z pól rekrutacji). */
  view: HoldView | null;
  /** Patrzący może zgłosić DL-owi (zapis w pipeline tej rekrutacji). */
  canReport: boolean;
  onHold: () => void;
  onResume: () => void;
  onEdit: () => void;
  onReport: (note: string) => Promise<boolean>;
  busy?: boolean;
}

/**
 * Sekcja „Stan rekrutacji” na górze dymka pigułki statusu (26.11.2026):
 * DL wstrzymuje, wznawia i zmienia powód (makieta m4 — okno osobno,
 * `JobHoldDialog`), rekruter przy otwartej, niewstrzymanej rekrutacji
 * zgłasza „Słyszysz, że klient wstrzymał?” (makieta m6).
 */
export function JobHoldPopoverSection({
  hold,
  view,
  canReport,
  onHold,
  onResume,
  onEdit,
  onReport,
  busy = false,
}: JobHoldPopoverSectionProps) {
  const ids = useId();
  const [note, setNote] = useState("");
  const onHoldNow = view != null;
  const canManage = hold?.can_manage === true;
  const by = shortName(hold?.by_name);
  const stateLine = onHoldNow
    ? [holdSinceText(view), view.reason ? `„${view.reason}”` : null].filter(Boolean).join(" · ")
    : [by ? `Stan ustawił(a) ${by}` : null, hold?.since ? `ostatnia zmiana ${formatDayMonthPl(hold.since)}` : null]
        .filter(Boolean)
        .join(" · ");

  return (
    <section className="space-y-2" data-testid="job-hold-section" aria-labelledby={`${ids}-title`}>
      <p
        id={`${ids}-title`}
        className="text-[11px] font-semibold uppercase tracking-eyebrow text-muted-foreground"
      >
        Stan rekrutacji
      </p>
      <div>
        <p className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
          {onHoldNow ? <Pause className="h-3.5 w-3.5 text-warning-muted-foreground" aria-hidden="true" /> : null}
          {onHoldNow ? "Wstrzymana przez klienta" : stateLabelOf(hold?.state)}
        </p>
        {stateLine ? <p className="text-xs text-muted-foreground">{stateLine}</p> : null}
        {onHoldNow && holdReviewText(view) ? (
          <p className="text-xs text-muted-foreground">{holdReviewText(view)}</p>
        ) : null}
      </div>

      {canManage ? (
        onHoldNow ? (
          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" onClick={onResume} disabled={busy} data-testid="job-hold-popover-resume">
              <Play className="h-3.5 w-3.5" aria-hidden="true" />
              Wznów rekrutację
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={onEdit} disabled={busy}>
              Zmień powód lub termin…
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onHold}
            disabled={busy}
            className="border-warning/60 text-warning-muted-foreground hover:bg-warning-muted"
            data-tour="job.hold.start"
            data-testid="job-hold-popover-hold"
          >
            <Pause className="h-3.5 w-3.5" aria-hidden="true" />
            Wstrzymaj rekrutację…
          </Button>
        )
      ) : canReport && !onHoldNow && hold ? (
        hold.my_open_report ? (
          <p
            className="rounded-md bg-muted px-2 py-1.5 text-xs text-muted-foreground"
            data-testid="job-hold-reported"
          >
            Zgłoszono DL-owi {formatDayMonthPl(hold.my_open_report.at)} — DL potwierdzi jednym
            kliknięciem.
          </p>
        ) : (
          <form
            className="space-y-2 border-t border-border pt-2"
            onSubmit={(event) => {
              event.preventDefault();
              void onReport(note).then((ok) => {
                if (ok) setNote("");
              });
            }}
          >
            <label htmlFor={`${ids}-note`} className="block text-sm font-semibold text-foreground">
              Słyszysz, że klient wstrzymał?
            </label>
            <Textarea
              id={`${ids}-note`}
              rows={2}
              maxLength={HOLD_NOTE_MAX}
              value={note}
              placeholder="np. DL powiedział na callu, że projekt stoi do stycznia"
              onChange={(event) => setNote(event.target.value)}
            />
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-muted-foreground">DL potwierdza jednym kliknięciem</span>
              <Button type="submit" size="sm" loading={busy} data-tour="job.hold.report" data-testid="job-hold-report">
                <Pause className="h-3.5 w-3.5" aria-hidden="true" />
                Zgłoś DL-owi
              </Button>
            </div>
          </form>
        )
      ) : null}
    </section>
  );
}
