"use client";

import { Pause } from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatDayMonthPl } from "@/lib/date-pl";
import { holdReviewText, holdSinceText, type HoldView } from "@/lib/job-hold";

export interface JobHoldBannerProps {
  view: HoldView;
  /**
   * `manage` — DL rekrutacji, HoR, admin: „Wznów rekrutację”, „Zmień termin”.
   * `recruiter` — „Zapytaj DL”. `read` — sam pas (podgląd bez zapisu).
   */
  variant: "manage" | "recruiter" | "read";
  onResume?: () => void;
  onChangeTerm?: () => void;
  onAskDl?: () => void;
  /** Moje otwarte zgłoszenie — zamiast „Zapytaj DL” informacja, kiedy. */
  reportedAt?: string | null;
  busy?: boolean;
}

/**
 * Pas nad Tablicą wstrzymanej rekrutacji (decyzja Artura 26.11.2026, makieta
 * m1): od kiedy, kto, powód i zakaz proponowania projektu kandydatom. Widzą
 * go wszyscy; przyciski zależą od tego, kto patrzy.
 */
export function JobHoldBanner({
  view,
  variant,
  onResume,
  onChangeTerm,
  onAskDl,
  reportedAt = null,
  busy = false,
}: JobHoldBannerProps) {
  const since = holdSinceText(view);
  const review = holdReviewText(view);
  return (
    <div
      role="status"
      data-testid="job-hold-banner"
      className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-warning/50 border-l-4 border-l-warning bg-warning-muted px-4 py-2.5 text-sm"
    >
      <span
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-warning text-warning-foreground"
        aria-hidden="true"
      >
        <Pause className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1 text-warning-muted-foreground">
        <p className="font-semibold">
          Rekrutacja wstrzymana przez klienta{since ? ` · ${since}` : ""}
        </p>
        <p className="leading-snug">
          {view.reason ? <>„{view.reason}”. </> : null}
          <strong>Nie proponuj kandydatom tego projektu i nie umawiaj weryfikacji.</strong>
          {review ? ` ${review}` : null}
        </p>
      </div>
      {variant === "manage" ? (
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" onClick={onResume} disabled={busy} data-testid="job-hold-resume">
            Wznów rekrutację
          </Button>
          <Button type="button" size="sm" variant="outline" onClick={onChangeTerm} disabled={busy}>
            Zmień termin
          </Button>
        </div>
      ) : variant === "recruiter" ? (
        reportedAt ? (
          <span className="text-xs text-warning-muted-foreground" data-testid="job-hold-asked">
            Zapytano DL {formatDayMonthPl(reportedAt)}
          </span>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="bg-card"
            onClick={onAskDl}
            disabled={busy}
            data-testid="job-hold-ask-dl"
          >
            Zapytaj DL
          </Button>
        )
      ) : null}
    </div>
  );
}
