"use client";

// Finanse → Rozliczenia → Raport klienta (T4T): plan Nordei N1.5.
// Wersja raportu z licznikami statusów, filtr „zmiany od poprzedniej wersji”,
// lista osób z tygodniami T4T; karta osoby otwiera się w miejscu listy.
import { useMemo, useRef, useState } from "react";
import { Download, FileSpreadsheet, Search, Upload } from "lucide-react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadNextRound, useTimeReportMonth, useUploadTimeReport, type TimeReportMonth, type TimeReportRow, type WeekCell } from "@/lib/api/client-time-reports";
import { downloadBlob } from "@/lib/authenticated-files";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

import { monthLabel } from "./format";
import {
  T4T_COUNTERS,
  T4T_FILTERS,
  T4T_STATUS,
  countT4tFilter,
  dateText,
  hoursText,
  matchesSearch,
  matchesT4tFilter,
  periodLabel,
  weekState,
  type T4tFilter,
} from "./time-report-format";

interface TimeReportViewProps {
  clientId: number;
  month: string;
  canWrite: boolean;
  versionId: number | null;
  onVersion: (id: number | null) => void;
  onOpen: (key: string) => void;
}

export function TimeReportView({ clientId, month, canWrite, versionId, onVersion, onOpen }: TimeReportViewProps) {
  const query = useTimeReportMonth(clientId, month, versionId);
  const [filter, setFilter] = useState<T4tFilter>("todo");
  const [search, setSearch] = useState("");

  const rows = useMemo(() => (query.data?.rows ?? []).filter((r) => matchesT4tFilter(filter, r) && matchesSearch(r, search)), [query.data, filter, search]);

  if (query.isError) {
    return (
      <QueryStateNotice state="error" description={apiErrorMessage(query.error, "Nie udało się pobrać raportu klienta.")} onRetry={() => query.refetch()} />
    );
  }
  if (!query.isSuccess) {
    return <div className="py-10 text-center text-sm text-muted-foreground">Ładowanie…</div>;
  }
  const data = query.data;
  const current = data.versions.find((v) => v.id === data.version_id) ?? null;

  return (
    <div className="space-y-2.5">
      <VersionBar data={data} clientId={clientId} month={month} canWrite={canWrite} onVersion={onVersion} />
      {current == null ? (
        <p className="rounded-xl border bg-card px-3 py-6 text-center text-sm text-muted-foreground">
          Za {monthLabel(month)} nie ma jeszcze raportu od klienta. Wgraj plik Excel z Time for Teams.
        </p>
      ) : (
        <>
          <Counters data={data} />
          <div className="flex flex-wrap items-center gap-1">
            {T4T_FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                aria-pressed={filter === f.key}
                onClick={() => setFilter(f.key)}
                disabled={f.key === "changed" && data.previous_version_id == null}
                className={cn(
                  "rounded-md border px-2.5 py-1 text-xs font-medium disabled:opacity-50 pointer-coarse:min-h-10",
                  filter === f.key ? "border-primary bg-primary/10 text-foreground" : "border-border bg-card text-muted-foreground",
                )}
              >
                {f.label} <span className="tabular-nums">{countT4tFilter(f.key, data.rows)}</span>
              </button>
            ))}
            <div className="relative ml-auto w-52">
              <Search aria-hidden className="absolute left-2 top-2 size-3.5 text-muted-foreground" />
              <Input
                aria-label="Szukaj osoby, numeru albo NIDS"
                placeholder="Osoba, numer, NIDS"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-8 pl-7 text-xs"
              />
            </div>
          </div>
          {rows.length === 0 ? (
            <p className="rounded-xl border bg-card px-3 py-6 text-center text-sm text-muted-foreground">Nikt nie pasuje do filtra.</p>
          ) : (
            <PeopleTable data={data} rows={rows} onOpen={onOpen} />
          )}
          <p className="text-[11px] text-muted-foreground">
            Liczą się tylko godziny w statusie 2 (Approved). Godziny z faktury kontraktora = netto z KSeF ÷ stawka z kontraktu.
          </p>
        </>
      )}
    </div>
  );
}

function VersionBar({
  data,
  clientId,
  month,
  canWrite,
  onVersion,
}: {
  data: TimeReportMonth;
  clientId: number;
  month: string;
  canWrite: boolean;
  onVersion: (id: number | null) => void;
}) {
  const index = data.versions.findIndex((v) => v.id === data.version_id);
  const current = index >= 0 ? data.versions[index] : null;
  const last = data.periods.at(-1);
  const { showError } = useToast();
  const [downloading, setDownloading] = useState(false);
  const pending = data.counts.all - (data.counts.ok ?? 0);

  async function nextRound() {
    setDownloading(true);
    try {
      const blob = await downloadNextRound(clientId, month, data.version_id === data.versions.at(-1)?.id ? null : data.version_id);
      downloadBlob(blob, `lista-kolejna-tura-${month}.xlsx`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać listy."));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="space-y-2 rounded-xl border bg-card px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <FileSpreadsheet aria-hidden className="size-4 text-muted-foreground" />
        <div className="min-w-0">
          <p className="text-[13px] font-medium">
            {current ? `Raport Time for Teams: wersja ${current.version_no} z ${dateText(current.received_on)}` : "Raport Time for Teams"}
          </p>
          {current ? (
            <p className="text-[11px] text-muted-foreground">
              {current.rows_count.toLocaleString("pl-PL")} wierszy · {current.people_count} osób
              {current.sheet_name ? ` · arkusz „${current.sheet_name}”` : ""}
              {last ? ` · ostatni przedział ${periodLabel(last)}` : ""}
            </p>
          ) : null}
        </div>
        {data.versions.length ? (
          <div className="flex flex-wrap gap-1" role="group" aria-label="Wersje raportu">
            {data.versions.map((v) => (
              <button
                key={v.id}
                type="button"
                aria-pressed={v.id === data.version_id}
                onClick={() => onVersion(v.id === data.versions.at(-1)?.id ? null : v.id)}
                className={cn(
                  "rounded-md border px-1.5 py-0.5 text-[11px] tabular-nums pointer-coarse:min-h-9",
                  v.id === data.version_id ? "border-primary bg-primary/10 font-medium" : "border-border text-muted-foreground hover:text-foreground",
                )}
              >
                v{v.version_no} · {dateText(v.received_on).slice(0, 5)}
              </button>
            ))}
          </div>
        ) : null}
        {current ? (
          <Button size="sm" variant="outline" className="ml-auto" disabled={downloading || pending === 0} onClick={() => void nextRound()}>
            <Download aria-hidden className="size-3.5" /> Lista do kolejnej tury ({pending})
          </Button>
        ) : null}
      </div>
      {canWrite ? <UploadForm clientId={clientId} month={month} onUploaded={() => onVersion(null)} /> : null}
    </div>
  );
}

function UploadForm({ clientId, month, onUploaded }: { clientId: number; month: string; onUploaded: () => void }) {
  const upload = useUploadTimeReport();
  const { showSuccess, showError } = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [receivedOn, setReceivedOn] = useState(warsawToday());
  const [sheets, setSheets] = useState<{ name: string; rows: number; people: number; month: string | null }[]>([]);
  const [sheet, setSheet] = useState("");

  function reset() {
    setFile(null);
    setSheets([]);
    setSheet("");
    if (fileRef.current) fileRef.current.value = "";
  }

  async function submit() {
    if (!file) return;
    try {
      const result = await upload.mutateAsync({
        clientId,
        month,
        receivedOn,
        file,
        sheet: sheet || undefined,
      });
      if (result.needs_sheet) {
        setSheets(result.sheets);
        setSheet(result.sheets.at(-1)?.name ?? "");
        return;
      }
      if (result.duplicate) {
        showSuccess(`Ten plik jest już wgrany jako wersja ${result.version.version_no}.`);
      } else {
        const suggested = result.suggested ? ` · ${result.suggested} podpowiedzi w kartotece` : "";
        showSuccess(`Wgrano wersję ${result.version.version_no}: ${result.version.people_count} osób${suggested}.`);
      }
      reset();
      onUploaded();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się wgrać raportu."));
    }
  }

  return (
    <form
      className="flex flex-wrap items-end gap-2 border-t pt-2"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <label className="grid gap-0.5 text-[11px] text-muted-foreground">
        Plik z Time for Teams (XLSX)
        <input
          ref={fileRef}
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setSheets([]);
            setSheet("");
          }}
          className="max-w-64 text-xs text-foreground file:mr-2 file:rounded-md file:border file:border-border file:bg-background file:px-2 file:py-1 file:text-xs"
        />
      </label>
      <label className="grid gap-0.5 text-[11px] text-muted-foreground">
        Otrzymany
        <Input type="date" value={receivedOn} max={warsawToday()} onChange={(e) => setReceivedOn(e.target.value)} className="h-8 w-36 text-xs" />
      </label>
      {sheets.length ? (
        <label className="grid gap-0.5 text-[11px] text-muted-foreground">
          Arkusz raportu ({sheets.length} w pliku)
          <select
            value={sheet}
            onChange={(e) => setSheet(e.target.value)}
            className="h-8 rounded-md border border-border bg-background px-2 text-xs text-foreground"
          >
            {sheets.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name} · {s.people} osób · {s.rows} wierszy
                {s.month && s.month !== month ? ` · ${s.month}` : ""}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <Button type="submit" size="sm" variant="outline" disabled={!file || !receivedOn || upload.isPending}>
        <Upload aria-hidden className="size-3.5" /> {upload.isPending ? "Wgrywam…" : "Wgraj nową wersję"}
      </Button>
    </form>
  );
}

function Counters({ data }: { data: TimeReportMonth }) {
  const total = data.counts.all || 1;
  // „Brak w raporcie” i „Bez kartoteki” tylko, gdy ktoś taki jest.
  const optional = new Set(["other_amount", "not_in_report", "unmatched"]);
  const shown = T4T_COUNTERS.filter((k) => !optional.has(k) || (data.counts[k] ?? 0) > 0);
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
      {shown.map((k) => (
        <div key={k} className="rounded-xl border bg-card px-3 py-2">
          <StatusDot tone={T4T_STATUS[k].tone}>{T4T_STATUS[k].label}</StatusDot>
          <p className="mt-0.5 font-display text-xl font-semibold tabular-nums">{data.counts[k] ?? 0}</p>
          <p className="text-[11px] text-muted-foreground">{Math.round(((data.counts[k] ?? 0) / total) * 100)}% osób</p>
        </div>
      ))}
    </div>
  );
}

export function WeekStrip({ weeks, labels }: { weeks: WeekCell[]; labels: string[] }) {
  return (
    <span className="inline-flex gap-0.5" aria-label="Przedziały T4T">
      {weeks.map((cell, i) => {
        const state = weekState(cell);
        return (
          <span
            key={labels[i] ?? i}
            title={`${labels[i]}: ${hoursText(cell[0])} zatw., ${hoursText(cell[1])} złoż.`}
            className={cn("h-3 w-4 rounded-[3px]", state === "submitted" ? "bg-warning" : state === "approved" ? "bg-success/70" : "bg-muted")}
          />
        );
      })}
    </span>
  );
}

function PeopleTable({ data, rows, onOpen }: { data: TimeReportMonth; rows: TimeReportRow[]; onOpen: (key: string) => void }) {
  const labels = data.periods.map(periodLabel);
  const prev = data.versions.find((v) => v.id === data.previous_version_id);
  return (
    <>
      <div className="hidden overflow-x-auto rounded-xl border bg-card md:block">
        <table className="w-full min-w-[920px] table-fixed text-[13px]">
          <colgroup>
            <col className="w-[22%]" />
            <col className="w-[20%]" />
            <col className="w-[8%]" />
            <col className="w-[8%]" />
            <col className="w-[8%]" />
            <col className="w-[10%]" />
            <col className="w-[12%]" />
            <col className="w-[12%]" />
          </colgroup>
          <thead className="border-b bg-muted/40 text-left text-[11px] text-muted-foreground">
            <tr>
              <th className="px-3 py-1.5 font-medium">Osoba</th>
              <th className="px-2 py-1.5 font-medium">Status</th>
              <th className="px-2 py-1.5 text-right font-medium">Zatw.</th>
              <th className="px-2 py-1.5 text-right font-medium">Złożone</th>
              <th className="px-2 py-1.5 text-right font-medium">Faktura</th>
              <th className="px-2 py-1.5 font-medium">Tygodnie</th>
              <th className="px-2 py-1.5 font-medium">{prev ? `Od v${prev.version_no}` : "Zmiana"}</th>
              <th className="px-3 py-1.5 font-medium">Następny krok</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((r) => (
              <tr key={r.key} className="cursor-pointer hover:bg-muted/30" onClick={() => onOpen(r.key)}>
                <td className="truncate px-3 py-1.5">
                  <button type="button" className="block max-w-full truncate text-left font-medium hover:underline" onClick={() => onOpen(r.key)}>
                    {r.name}
                  </button>
                  <span className="block truncate text-[11px] tabular-nums text-muted-foreground">
                    {r.person_no ?? "bez numeru"} · {r.projects.length ? `${r.projects.length} NIDS` : "bez NIDS"}
                    {r.mapping === "suggested" ? " · podpowiedź w kartotece" : ""}
                  </span>
                </td>
                <td className="px-2 py-1.5">
                  <StatusDot tone={T4T_STATUS[r.status].tone} note={r.notes[0]}>
                    {T4T_STATUS[r.status].label}
                  </StatusDot>
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">{hoursText(r.approved)}</td>
                <td className={cn("px-2 py-1.5 text-right tabular-nums", Number(r.submitted) > 0 ? "text-warning-muted-foreground" : "text-muted-foreground")}>
                  {Number(r.submitted) > 0 ? hoursText(r.submitted) : "–"}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">{hoursText(r.invoice_hours)}</td>
                <td className="px-2 py-1.5">
                  <WeekStrip weeks={r.weeks} labels={labels} />
                </td>
                <td className="px-2 py-1.5 text-[11px] text-muted-foreground">
                  {r.changed
                    ? `${r.previous_status ? T4T_STATUS[r.previous_status].label : "nowa osoba"} → ${T4T_STATUS[r.status].label}`
                    : prev
                      ? "bez zmian"
                      : "–"}
                </td>
                <td className={cn("px-3 py-1.5 text-xs", r.status === "ok" || r.status === "waiting" ? "text-muted-foreground" : "font-medium")}>
                  {T4T_STATUS[r.status].next}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="space-y-1.5 md:hidden">
        {rows.map((r) => (
          <li key={r.key}>
            <button type="button" onClick={() => onOpen(r.key)} className="w-full rounded-xl border bg-card px-3 py-2 text-left">
              <span className="flex items-start justify-between gap-2">
                <span className="min-w-0 truncate text-[13px] font-medium">{r.name}</span>
                <StatusDot tone={T4T_STATUS[r.status].tone}>{T4T_STATUS[r.status].label}</StatusDot>
              </span>
              <span className="block text-[11px] tabular-nums text-muted-foreground">
                zatw. {hoursText(r.approved)}
                {Number(r.submitted) > 0 ? ` · złoż. ${hoursText(r.submitted)}` : ""} · faktura {hoursText(r.invoice_hours)}
              </span>
              <span className="mt-1 flex items-center justify-between gap-2">
                <WeekStrip weeks={r.weeks} labels={labels} />
                <span className="text-[11px] text-muted-foreground">{T4T_STATUS[r.status].next}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
