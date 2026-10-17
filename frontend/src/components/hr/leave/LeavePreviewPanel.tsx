import type { EmploymentType } from "@/lib/api/hr";
import type { LeavePreview } from "@/lib/api/hr-leave";
import { formatWeekdayDayPl } from "@/lib/date-pl";
import { reportsAbsence } from "@/lib/hr-employment-terms";

import { daysLabel, eventLabel, formatRange, paySplitLabel, reportOutcome } from "./leave-format";

export interface PreviewPanelProps {
  preview: LeavePreview | undefined;
  loading: boolean;
  failed: boolean;
  waitingForPerson: boolean;
  onBehalf: boolean;
  range: string | null;
  /** Forma osoby — słowa puli i „Co się stanie po zgłoszeniu” (D4, D5). */
  form?: EmploymentType;
}

/** „Co wypada w tym czasie” — dni, pula, praca w NEXUSIE, nieobecni z działu. */
export function PreviewPanel({
  preview,
  loading,
  failed,
  waitingForPerson,
  onBehalf,
  range,
  form,
}: PreviewPanelProps) {
  const box = "grid content-start gap-3 rounded-lg border border-border bg-muted/40 p-4 text-sm";
  const report = reportsAbsence(form);
  if (waitingForPerson) {
    return <div className={box}>Wybierz osobę, żeby policzyć dni i pulę.</div>;
  }
  if (!range) {
    return <div className={box}>Podaj daty, żeby policzyć dni robocze.</div>;
  }
  if (failed && !preview) {
    return <div className={box}>Nie udało się policzyć dni — spróbuj zmienić daty.</div>;
  }
  if (!preview) {
    return <div className={box}>Liczę dni robocze…</div>;
  }
  return (
    <div className={box} aria-busy={loading}>
      <div className="flex items-baseline justify-between gap-2">
        <b className="text-foreground">Co wypada w tym czasie</b>
        <span className="text-[11px] text-muted-foreground">{range}</span>
      </div>
      {preview.blocking_reason ? (
        <p role="alert" className="rounded-md bg-destructive-muted p-2 text-destructive-muted-foreground">
          {preview.blocking_reason}
        </p>
      ) : null}
      <p className="text-foreground">
        <b className="tabular-nums">{daysLabel(preview.days_total)} roboczych</b>
        {preview.return_on ? (
          <span className="text-muted-foreground"> · powrót {formatWeekdayDayPl(preview.return_on)}</span>
        ) : null}
      </p>
      {preview.years.map((split) => (
        <p key={split.year} className="text-muted-foreground">
          {split.has_pool && split.remaining_before !== null ? (
            <>
              {report ? `Płatne dni z umowy ${split.year}` : `Pula ${split.year}`}: zostało{" "}
              <span className="tabular-nums text-foreground">
                {daysLabel(split.remaining_before)}
              </span>
              {Number(split.paid) > 0 ? (
                <>
                  {" "}→ po wniosku{" "}
                  <span className="tabular-nums text-foreground">
                    {daysLabel(split.remaining_after ?? "0")}
                  </span>
                </>
              ) : null}
            </>
          ) : (
            <>
              Rok {split.year}: {report ? "bez płatnych dni — bez wynagrodzenia" : "bez puli"}
            </>
          )}
          {Number(split.unpaid) > 0 ? (
            <span className="block text-warning-muted-foreground">
              {report ? "Bez wynagrodzenia" : "Bezpłatnie"}: {daysLabel(split.unpaid)}
            </span>
          ) : null}
        </p>
      ))}
      {preview.work.total > 0 ? (
        <div>
          <b className="text-foreground">{onBehalf ? "W tym czasie ta osoba ma" : "W tym czasie masz"}</b>
          <ul className="mt-1 space-y-0.5 text-muted-foreground">
            {preview.work.by_kind.map((kind) => (
              <li key={kind.kind}>
                {kind.label}: <span className="tabular-nums text-foreground">{kind.count}</span>
              </li>
            ))}
          </ul>
          <ul className="mt-1 space-y-0.5 text-[12px] text-muted-foreground">
            {preview.work.items.slice(0, 4).map((item) => (
              <li key={`${item.starts_at}-${item.kind}`} className="truncate">
                {eventLabel(item.starts_at)} · {item.title ?? item.label}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[12px] text-muted-foreground">Przejmie je zastępca.</p>
        </div>
      ) : null}
      {preview.department_absent.length > 0 ? (
        <div>
          <b className="text-foreground">Z działu też nieobecni</b>
          <ul className="mt-1 space-y-0.5 text-muted-foreground">
            {preview.department_absent.map((row) => (
              <li key={row.user_id}>
                {row.name} · {formatRange(row.start_date, row.end_date)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {preview.substitute_absent ? (
        <p className="text-warning-muted-foreground">
          Wybrany zastępca też jest nieobecny w części tego okresu.
        </p>
      ) : null}
      {report && !onBehalf ? (
        <div data-testid="report-outcome">
          <b className="text-foreground">Co się stanie po zgłoszeniu</b>
          <ul className="mt-1 space-y-1 text-muted-foreground">
            {reportOutcome(preview, form).map((line) => (
              <li key={line.title}>
                <span className="text-foreground">{line.title}</span> — {line.text}
              </li>
            ))}
          </ul>
          {form === "b2b" && paySplitLabel(preview) ? (
            <p className="mt-1 text-[12px] text-muted-foreground">{paySplitLabel(preview)}</p>
          ) : null}
        </div>
      ) : preview.auto_approved ? (
        <p className="text-muted-foreground">
          {onBehalf
            ? "Wpis jest od razu zatwierdzony; osoba dostanie powiadomienie."
            : "Zwolnienie zatwierdza się od razu — przełożony i Kadry dostaną powiadomienie."}
        </p>
      ) : null}
      {!report && !onBehalf && !preview.auto_approved ? (
        <p className="text-[12px] text-muted-foreground">
          Wniosek czeka na akceptację: {preview.approver}.
        </p>
      ) : null}
    </div>
  );
}
