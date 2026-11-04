"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadHrFile } from "@/lib/api/hr";
import { timePaths } from "@/lib/api/hr-time";
import { monthTitlePl, type YearMonth } from "@/lib/date-pl";

/** Najdłuższy zakres eksportu (jak Compass i serwer). */
export const MAX_CSV_MONTHS = 24;

export function monthValue(period: YearMonth): string {
  return `${period.year}-${String(period.month).padStart(2, "0")}`;
}

function monthIndex(value: string): number | null {
  const match = /^(\d{4})-(\d{2})$/.exec(value);
  if (!match) return null;
  const month = Number(match[2]);
  if (month < 1 || month > 12) return null;
  return Number(match[1]) * 12 + month - 1;
}

/** Błąd zakresu „od–do” (`null` = poprawny). */
export function rangeError(from: string, to: string): string | null {
  const start = monthIndex(from);
  const end = monthIndex(to);
  if (start == null || end == null) return "Wybierz miesiąc „od” i „do”.";
  if (start > end) return "Miesiąc „od” musi być przed miesiącem „do” albo nim samym.";
  if (end - start + 1 > MAX_CSV_MONTHS) return `Eksport obejmuje najwyżej ${MAX_CSV_MONTHS} miesiące.`;
  return null;
}

export interface CsvPerson {
  user_id: number;
  name: string;
}

export type TimesheetCsvMode =
  | { kind: "self" }
  | {
      kind: "team";
      /** Osoby, których godziny czytający widzi (kolejka akceptacji). */
      people: readonly CsvPerson[];
      /** Cały zespół za miesiąc — Płace, Kadry, admin (jak paczka PDF). */
      allowMonth: boolean;
    };

export interface TimesheetCsvDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: TimesheetCsvMode;
  /** Miesiąc otwarty na ekranie — domyślny zakres. */
  period: YearMonth;
}

/**
 * „Eksport CSV” godzin (jak w Compassie): osoba — własne godziny za zakres
 * miesięcy; akceptujący — godziny osoby z zespołu; Płace i Kadry — także
 * cały zespół za miesiąc. Plik: separator „;”, UTF-8 z BOM, bez kwot.
 */
export function TimesheetCsvDialog({ open, onOpenChange, mode, period }: TimesheetCsvDialogProps) {
  const team = mode.kind === "team" ? mode : null;
  const [scope, setScope] = useState<"month" | "person">(
    team?.allowMonth ? "month" : "person",
  );
  const [personId, setPersonId] = useState<number | null>(team?.people[0]?.user_id ?? null);
  const [from, setFrom] = useState(monthValue(period));
  const [to, setTo] = useState(monthValue(period));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const monthName = monthTitlePl(period).toLowerCase();
  const wholeMonth = team != null && scope === "month";

  const download = async () => {
    setError(null);
    let path: string;
    let fallback: string;
    if (wholeMonth) {
      path = timePaths.monthCsv(period.year, period.month);
      fallback = `godziny-${monthValue(period)}.csv`;
    } else {
      const invalid = rangeError(from, to);
      if (invalid) {
        setError(invalid);
        return;
      }
      if (team) {
        if (personId == null) {
          setError("Wybierz osobę.");
          return;
        }
        path = timePaths.personCsv(personId, from, to);
      } else {
        path = timePaths.myCsv(from, to);
      }
      fallback = `godziny-${from}_${to}.csv`;
    }
    setBusy(true);
    try {
      await downloadHrFile(path, fallback);
      onOpenChange(false);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się pobrać pliku CSV."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Eksport godzin do CSV"
      description="Wiersz na każdy wpis: data, godziny, projekt, opis, źródło i godziny ponad 8 h dziennie. Plik otwiera się w Excelu; bez stawek i kwot."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={() => void download()} disabled={busy}>
            {busy ? "Pobieranie…" : "Pobierz CSV"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {team?.allowMonth && team.people.length > 0 ? (
          <div className="sm:col-span-2">
            <SegmentedRadio
              label="Zakres eksportu"
              value={scope}
              onChange={setScope}
              options={[
                { value: "month", label: `Cały zespół — ${monthName}` },
                { value: "person", label: "Jedna osoba" },
              ]}
            />
          </div>
        ) : null}
        {team && scope === "person" ? (
          <FormField label="Osoba" htmlFor="time-csv-person" className="sm:col-span-2">
            <Select
              value={personId != null ? String(personId) : undefined}
              onValueChange={(value) => setPersonId(Number(value))}
            >
              <SelectTrigger id="time-csv-person">
                <SelectValue placeholder="Wybierz osobę" />
              </SelectTrigger>
              <SelectContent>
                {team.people.map((person) => (
                  <SelectItem key={person.user_id} value={String(person.user_id)}>
                    {person.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        ) : null}
        {wholeMonth ? (
          <p className="text-sm text-muted-foreground sm:col-span-2">
            Wszystkie wpisy za {monthName} — każdy status raportu (szkic, wysłany,
            zaakceptowany). Miesiąc zmienisz strzałkami nad tabelą.
          </p>
        ) : (
          <>
            <FormField label="Od miesiąca" htmlFor="time-csv-from">
              <Input
                id="time-csv-from"
                type="month"
                value={from}
                onChange={(event) => setFrom(event.target.value)}
              />
            </FormField>
            <FormField
              label="Do miesiąca"
              htmlFor="time-csv-to"
              description={`Najwyżej ${MAX_CSV_MONTHS} miesiące.`}
            >
              <Input
                id="time-csv-to"
                type="month"
                value={to}
                onChange={(event) => setTo(event.target.value)}
              />
            </FormField>
          </>
        )}
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
