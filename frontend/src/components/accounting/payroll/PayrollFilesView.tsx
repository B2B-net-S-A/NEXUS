"use client";

import { useState } from "react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  downloadPayrollFile,
  payrollPaths,
  usePit11,
  useRegistrations,
  type Registrations,
  type YearFile,
} from "@/lib/api/payroll-lists";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard } from "../AccountingShell";
import { datePl } from "../ledger-model";
import { FileProblemDialog } from "./FileProblemDialog";
import {
  REGISTRATION_KINDS,
  errorDetail,
  fileProblem,
  monthRange,
  plural,
  rangeProblem,
  type FileProblem,
} from "./payroll-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const TITLE_KIND: Record<string, string> = { uop: "umowa o pracę", zlecenie: "zlecenie" };

/** „Pliki ZUS i PIT”: zgłoszenia ZUS w zakresie dat i roczne deklaracje PIT. */
export function PayrollFilesView({ year, month, today }: { year: number; month: number; today: string }) {
  return (
    <div className="space-y-3.5">
      <RegistrationsCard key={`${year}-${month}`} year={year} month={month} />
      <YearFilesCard key={year} defaultYear={year} today={today} />
    </div>
  );
}

function RegistrationsCard({ year, month }: { year: number; month: number }) {
  const { showToast } = useToast();
  const range = monthRange(year, month);
  const [from, setFrom] = useState(range.from);
  const [to, setTo] = useState(range.to);
  const [downloading, setDownloading] = useState(false);
  const [problem, setProblem] = useState<FileProblem | null>(null);
  const invalid = rangeProblem(from, to);
  const query = useRegistrations(from, to, invalid == null);
  const available = query.data?.file_available === true;

  const download = async () => {
    setDownloading(true);
    try {
      await downloadPayrollFile(payrollPaths.registrations(from, to), `zgloszenia-zus-${from}-${to}.xml`);
    } catch (error) {
      const found = fileProblem(error);
      if (found) setProblem(found);
      else showToast(apiErrorMessage(error, "Nie udało się pobrać zgłoszeń ZUS."), "error");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <SectionCard title="Zgłoszenia ZUS" aside="ZUA, ZZA i ZWUA w pliku KEDU do Płatnika">
      <div className="flex flex-wrap items-end gap-2 border-b border-border/70 px-3.5 py-2.5 text-[13px]">
        <label className="grid gap-1">
          <span className="font-medium">Od</span>
          <input type="date" aria-label="Zgłoszenia od" className={CONTROL} value={from} onChange={(event) => setFrom(event.target.value)} />
        </label>
        <label className="grid gap-1">
          <span className="font-medium">Do</span>
          <input type="date" aria-label="Zgłoszenia do" className={CONTROL} value={to} onChange={(event) => setTo(event.target.value)} />
        </label>
        <span className="inline-flex" title={available ? undefined : "W tym zakresie nie ma zgłoszeń z kompletem danych"}>
          <Button size="sm" disabled={!available || invalid != null} loading={downloading} onClick={() => void download()}>
            Pobierz KEDU zgłoszeń
          </Button>
        </span>
        {invalid ? <span className="text-[12px] text-destructive">{invalid}</span> : null}
      </div>
      {invalid ? null : query.isError ? (
        <QueryStateNotice state="error" onRetry={() => query.refetch()} className="m-3" />
      ) : !query.isSuccess ? (
        <p className="px-3.5 py-3 text-[13px] text-muted-foreground">Wczytywanie zgłoszeń…</p>
      ) : (
        <RegistrationsList data={query.data} />
      )}
      <FileProblemDialog problem={problem} onClose={() => setProblem(null)} />
    </SectionCard>
  );
}

function RegistrationsList({ data }: { data: Registrations }) {
  return (
    <>
      {data.events.length ? (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[640px] table-fixed text-sm">
            <thead>
              <tr className="border-b border-border/70">
                <th className={cn(CALM_HEAD, "w-[24%] px-3.5 py-2 text-left")}>Zgłoszenie</th>
                <th className={cn(CALM_HEAD, "w-[28%] px-2 py-2 text-left")}>Osoba</th>
                <th className={cn(CALM_HEAD, "w-[14%] px-2 py-2 text-left")}>Od dnia</th>
                <th className={cn(CALM_HEAD, "px-3.5 py-2 text-left")}>Uwagi</th>
              </tr>
            </thead>
            <tbody>
              {data.events.map((event, index) => (
                <tr key={`${event.kind}-${event.person_key}-${event.on}-${index}`} className={cn(CALM_ROW, "align-top last:border-0")}>
                  <td className="px-3.5 py-1.5">
                    <span className="font-medium">{event.kind}</span>
                    <span className={CALM_SUBLINE}>{REGISTRATION_KINDS[event.kind] ?? event.kind}</span>
                  </td>
                  <td className="min-w-0 px-2 py-1.5">
                    <span className="block truncate" title={event.name}>
                      {event.name}
                    </span>
                    <span className={CALM_SUBLINE}>{TITLE_KIND[event.title_kind] ?? event.title_kind}</span>
                  </td>
                  <td className="px-2 py-1.5 tabular-nums">{datePl(event.on)}</td>
                  <td className="min-w-0 px-3.5 py-1.5 text-[13px]">
                    {event.problems.length ? (
                      <span className="flex items-start gap-1.5">
                        <span aria-hidden className="mt-[7px] size-1.5 shrink-0 rounded-full bg-warning" />
                        <span className="min-w-0 break-words">{event.problems.map((problem) => problem.label).join(" ")}</span>
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-3.5 py-3 text-[13px] text-muted-foreground">
          W tym zakresie nikt nie zaczyna ani nie kończy umowy z ubezpieczeniem.
        </p>
      )}
      {data.skipped.length ? (
        <div className="border-t border-border/70 px-3.5 py-2 text-[12.5px]">
          <p className="font-medium">Pominięte: {data.skipped.length}</p>
          <ul className="mt-1 space-y-0.5 text-muted-foreground">
            {data.skipped.map((item, index) => (
              <li key={`${item.name}-${index}`}>
                {item.name}
                {item.kind ? ` (${item.kind})` : ""}: {item.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </>
  );
}

const YEAR_FILES: { key: string; label: string; note: string; files: { file: YearFile; label: string }[] }[] = [
  {
    key: "pit-4r",
    label: "PIT-4R",
    note: "roczna deklaracja zaliczek na podatek od wynagrodzeń i zleceń",
    files: [
      { file: "pit-4r.xml", label: "XML" },
      { file: "pit-4r.pdf", label: "PDF" },
    ],
  },
  {
    key: "pit-8ar",
    label: "PIT-8AR",
    note: "roczna deklaracja podatku ryczałtowego (zlecenia do limitu ryczałtu)",
    files: [
      { file: "pit-8ar.xml", label: "XML" },
      { file: "pit-8ar.pdf", label: "PDF" },
    ],
  },
];

function YearFilesCard({ defaultYear, today }: { defaultYear: number; today: string }) {
  const { showToast } = useToast();
  const top = Math.max(defaultYear, Number(today.slice(0, 4)));
  const years = [top, top - 1, top - 2];
  const [year, setYear] = useState(defaultYear);
  const [busy, setBusy] = useState<string | null>(null);
  const pit11 = usePit11(year);
  const people = pit11.data?.people ?? [];
  const ready = people.filter((person) => person.ready).length;

  const download = async (file: YearFile) => {
    setBusy(file);
    try {
      await downloadPayrollFile(payrollPaths.year(year, file), `${file.replace(".", `-${year}.`)}`);
    } catch (error) {
      const notFound = errorDetail(error).status === 404;
      showToast(
        apiErrorMessage(
          error,
          notFound ? `Brak kwot za rok ${year} — nie ma z czego zrobić deklaracji.` : "Nie udało się pobrać pliku.",
        ),
        "error",
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <SectionCard
      title="Roczne deklaracje PIT"
      aside={
        <select aria-label="Rok deklaracji" className={cn(CONTROL, "h-7")} value={year} onChange={(event) => setYear(Number(event.target.value))}>
          {years.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      }
    >
      <ul>
        {YEAR_FILES.map((row) => (
          <li key={row.key} className={cn(CALM_ROW, "flex flex-wrap items-center justify-between gap-2 px-3.5 py-2")}>
            <span className="min-w-0 text-[13px]">
              <span className="font-medium">
                {row.label} za {year}
              </span>
              <span className={CALM_SUBLINE}>{row.note}</span>
            </span>
            <span className="flex gap-1.5">
              {row.files.map((item) => (
                <Button
                  key={item.file}
                  size="sm"
                  variant="outline"
                  loading={busy === item.file}
                  aria-label={`${row.label} ${item.label}`}
                  onClick={() => void download(item.file)}
                >
                  {item.label}
                </Button>
              ))}
            </span>
          </li>
        ))}
        <li className="space-y-2 px-3.5 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="min-w-0 text-[13px]">
              <span className="font-medium">PIT-11 za {year}</span>
              <span className={CALM_SUBLINE}>
                informacje dla osób — ZIP z plikiem na osobę; trafiają do niego tylko osoby z kompletem danych
              </span>
            </span>
            <span className="inline-flex" title={ready ? undefined : "Nikt nie ma jeszcze kompletu danych do PIT-11"}>
              <Button
                size="sm"
                variant="outline"
                disabled={pit11.isSuccess && ready === 0}
                loading={busy === "pit-11.zip"}
                aria-label="PIT-11 ZIP"
                onClick={() => void download("pit-11.zip")}
              >
                ZIP
              </Button>
            </span>
          </div>
          {pit11.isError ? (
            <QueryStateNotice state="error" onRetry={() => pit11.refetch()} />
          ) : !pit11.isSuccess ? (
            <p className="text-[12.5px] text-muted-foreground">Wczytywanie osób do PIT-11…</p>
          ) : people.length ? (
            <div className="rounded-md border border-border/70">
              <p className="border-b border-border/70 px-3 py-1.5 text-[12px] text-muted-foreground">
                Gotowe: {ready} z {plural(people.length, "osoby", "osób", "osób")}
              </p>
              <table className="w-full table-fixed text-[13px]">
                <tbody>
                  {people.map((person) => (
                    <tr key={person.person_key} className={cn(CALM_ROW, "align-top last:border-0")}>
                      <td className="w-[40%] min-w-0 truncate px-3 py-1.5" title={person.name}>
                        {person.name}
                      </td>
                      <td className="min-w-0 px-3 py-1.5">
                        {person.ready ? (
                          <span className="text-success">gotowe</span>
                        ) : (
                          <span className="break-words text-warning-muted-foreground">brakuje: {person.missing.join(", ")}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-[12.5px] text-muted-foreground">W {year} r. nie ma zatwierdzonych list z wypłatami.</p>
          )}
        </li>
      </ul>
    </SectionCard>
  );
}
