"use client";

import { useState } from "react";
import { Download } from "lucide-react";

import { StatusDot } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { daysLabel, formatRange } from "@/components/hr/leave/leave-format";
import { STATUS_TONE } from "@/components/hr/time/time-format";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadHrFile, type PersonFull } from "@/lib/api/hr";
import { usePersonHistory } from "@/lib/api/hr-person-history";
import { TIMESHEET_STATUS_LABELS, timePaths } from "@/lib/api/hr-time";
import { monthTitlePl } from "@/lib/date-pl";
import { employmentTerms } from "@/lib/hr-employment-terms";

import { TonePill } from "./people-ui";
import {
  ABSENCE_STATE_LABEL,
  ABSENCE_STATE_TONE,
  hoursOfNorm,
  poolSummary,
  timesheetStatus,
} from "./person-history-view";
import { ringParts } from "./person-view";

function CardHeading({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between gap-2">
      <h3 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
        {title}
      </h3>
      {action}
    </div>
  );
}

function Failure({ text, onRetry }: { text: string; onRetry: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
      {text}
      <Button size="sm" variant="ghost" onClick={onRetry}>
        Spróbuj ponownie
      </Button>
    </div>
  );
}

/**
 * Karty „Nieobecności <rok>” i „Raporty godzin” w zakładce kartoteki
 * „Nieobecności i godziny” (`#czas`). Jedno zapytanie
 * (`GET /api/hr/people/{id}/history`); część modułu zamkniętego dla
 * patrzącego (`null`) nie ma listy ani karty raportów. Awaria to zdanie z „Spróbuj ponownie”,
 * pusty stan wisi na sukcesie zapytania.
 */
export function PersonAbsencesHours({
  person,
  year,
  canEditPool,
  onEditPool,
}: {
  person: PersonFull;
  year: number;
  canEditPool: boolean;
  onEditPool: () => void;
}) {
  const history = usePersonHistory(person.user_id, year);
  // Błąd pobrania PDF jako zdanie w karcie — kartoteka nie zależy od dostawcy toastów.
  const [pdfError, setPdfError] = useState<string | null>(null);
  const data = history.isSuccess ? history.data : undefined;
  const form = person.employment_type;
  // Słowo raportu z formy osoby; forma ukryta (Kadry bez Płac) — neutralnie.
  const reportWord = form ? employmentTerms(form).timesheet : "Raporty godzin";
  const absences = data?.absences ?? null;
  const timesheets = data?.timesheets ?? null;
  const pool = poolSummary({
    form,
    ring: ringParts(person.leave_balance),
    entitlement: person.entitlements?.find((row) => row.year === year),
    year,
  });

  const downloadPdf = async (id: number, label: string) => {
    setPdfError(null);
    try {
      await downloadHrFile(timePaths.timesheetPdf(id), `raport-godzin-${label}.pdf`);
    } catch (err) {
      setPdfError(apiErrorMessage(err, "Nie udało się pobrać PDF."));
    }
  };

  const loading = history.isLoading;
  const failed = history.isError;

  return (
    <>
      {/* Linia puli to dane kartoteki — karta stoi także przy module nieobecności
          zamkniętym dla patrzącego (wtedy bez listy), bo Kadry zmieniają tu pulę. */}
      <Card className="p-4" data-testid="person-absences">
        <CardHeading
          title={`Nieobecności ${year}`}
          action={
            canEditPool ? (
              <Button size="sm" variant="ghost" onClick={onEditPool}>
                Zmień pulę
              </Button>
            ) : undefined
          }
        />
        <p className="text-sm text-foreground">{pool}</p>
        {form === "uop" && person.suggested_entitlement_days ? (
          <p className="mt-1 text-xs text-muted-foreground">
            Wymiar według stażu ({person.leave_seniority_years} lat):{" "}
            {person.suggested_entitlement_days} dni.
          </p>
        ) : null}
        {loading || failed || absences ? (
          <div className="mt-3 border-t border-border/60 pt-2">
            {loading ? (
              <p className="text-sm text-muted-foreground">Wczytywanie nieobecności…</p>
            ) : failed ? (
              <Failure
                text="Nie udało się wczytać nieobecności i raportów godzin."
                onRetry={() => history.refetch()}
              />
            ) : absences && absences.items.length === 0 ? (
              <p className="text-sm text-muted-foreground">Brak nieobecności w {year}.</p>
            ) : absences ? (
              <ul className="divide-y divide-border/60" aria-label={`Nieobecności ${year}`}>
                {absences.items.map((item) => (
                  <li
                    key={item.id}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-sm"
                  >
                    <span className="min-w-[10rem] font-medium tabular-nums text-foreground">
                      {formatRange(item.start_date, item.end_date)}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-foreground">
                      {item.label}
                      <span className="text-muted-foreground">
                        {" · "}
                        {daysLabel(item.days_total)}
                      </span>
                    </span>
                    <TonePill tone={ABSENCE_STATE_TONE[item.state]}>
                      {ABSENCE_STATE_LABEL[item.state]}
                    </TonePill>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
      </Card>

      {timesheets ? (
        <Card className="p-4 lg:col-span-2" data-testid="person-timesheets">
          <CardHeading title={reportWord} />
          {pdfError ? (
            <p role="alert" className="mb-2 text-sm text-destructive">
              {pdfError}
            </p>
          ) : null}
          {timesheets.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {timesheets.timesheet_required
                ? "Brak raportów w ostatnich miesiącach."
                : "Ta osoba nie składa raportu godzin."}
            </p>
          ) : (
            <ul className="divide-y divide-border/60" aria-label={reportWord}>
              {timesheets.items.map((item) => {
                const status = timesheetStatus(item);
                const label = `${item.year}-${String(item.month).padStart(2, "0")}`;
                return (
                  <li
                    key={label}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5 text-sm"
                  >
                    <span className="min-w-[9rem] font-medium text-foreground">
                      {monthTitlePl(item)}
                    </span>
                    <span className="min-w-[7rem] tabular-nums text-muted-foreground">
                      {item.timesheet_id ? hoursOfNorm(item) : "—"}
                    </span>
                    <StatusDot tone={STATUS_TONE[status]}>
                      {TIMESHEET_STATUS_LABELS[status].toLowerCase()}
                    </StatusDot>
                    {item.has_pdf && item.timesheet_id ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="ml-auto"
                        onClick={() => downloadPdf(item.timesheet_id as number, label)}
                      >
                        <Download className="mr-1 h-3.5 w-3.5" aria-hidden />
                        PDF
                      </Button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      ) : null}
    </>
  );
}
