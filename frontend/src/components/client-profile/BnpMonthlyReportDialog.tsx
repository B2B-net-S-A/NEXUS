"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { fetchAuthenticatedBlob } from "@/lib/authenticated-files";
import { formatIsoDatePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { previousMonth } from "@/lib/previous-month";
import { cn } from "@/lib/utils";
import { AppModal, TabbedNav } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuthStore } from "@/store/auth";

interface ReportRow {
  job_id: number;
  title: string;
  start: string;
  closed: string | null;
  sla: string;
  ritm: string | null;
  ritm_source: "field" | "title" | "rfp" | "none";
  role: string;
  seniority: string | null;
  seniority_label: string | null;
  seniority_source: "field" | "title" | "years" | "description" | "none";
  rate_card_id: number | null;
  contract_role: string | null;
  contract_role_source: "field" | "proposal" | "none";
  cv: number;
  cv_sla: number;
  cv_in_budget: number | null;
  percent_cv_sla: number | null;
  ritm_sla: number;
  ritm_sla_and_budget: number | null;
  rejected_cv: number;
  meetings: number;
  rejected_after_meeting: number;
  meetings_per_cv: number | null;
  rejected_per_cv: number | null;
  offers: number;
  offer_min_md: number | null;
  offer_max_md: number | null;
  band_min_md: number | null;
  band_max_md: number | null;
  band_average_md: number | null;
  recommended_average_md: number | null;
  percent_from_band_average: number | null;
  offer_min_minus_top: number | null;
  percent_difference: number | null;
  needs_attention: boolean;
}

interface ReportBand {
  id: number | null;
  role: string;
  minimum: number;
  maximum: number;
  average: number;
}

interface ReportData {
  month: string;
  rows: ReportRow[];
  bands: ReportBand[];
  bands_source: "saved" | "contract" | "none";
  seniority_options: { value: string; label: string }[];
}

type Flag = "missing" | "proposal" | null;
interface Cell {
  value: string | number | null;
  flag?: Flag;
}
interface Column {
  head: string;
  cell: (row: ReportRow) => Cell;
}

const date = (value: string | null) => (value ? formatIsoDatePl(value) : null);
const percent = (value: number | null) => (value === null ? null : `${Math.round(value * 100)}%`);
const ratio = (value: number | null) => (value === null ? null : value.toFixed(2));

const ritmCell = (row: ReportRow): Cell => ({
  value: row.ritm,
  flag: row.ritm_source === "none" ? "missing" : row.ritm_source === "rfp" ? "proposal" : null,
});
const seniorityCell = (row: ReportRow): Cell => ({
  value: row.seniority_label,
  flag:
    row.seniority_source === "none"
      ? "missing"
      : row.seniority_source === "field"
        ? null
        : "proposal",
});
const budgetCell = (row: ReportRow): Cell => ({
  value: row.cv_in_budget,
  flag: row.cv_in_budget === null ? "missing" : null,
});
const bandCell = (row: ReportRow, value: number | null): Cell => ({
  value,
  flag:
    row.contract_role_source === "none"
      ? "missing"
      : row.contract_role_source === "proposal"
        ? "proposal"
        : null,
});

const OPTION_COLUMNS: Column[] = [
  { head: "START", cell: (r) => ({ value: date(r.start) }) },
  { head: "CLOSED", cell: (r) => ({ value: date(r.closed) }) },
  { head: "SLA (10 DR)", cell: (r) => ({ value: date(r.sla) }) },
  { head: "RITM", cell: ritmCell },
  { head: "ROLA", cell: (r) => ({ value: r.role }) },
  { head: "SENIORITY", cell: seniorityCell },
  { head: "# CV", cell: (r) => ({ value: r.cv }) },
  { head: "# CV SLA", cell: (r) => ({ value: r.cv_sla }) },
  { head: "# CV stawka", cell: budgetCell },
  { head: "# ODRZ. CV", cell: (r) => ({ value: r.rejected_cv }) },
  { head: "# SPOTKAŃ", cell: (r) => ({ value: r.meetings }) },
  { head: "# ODRZ. PO SPOTK.", cell: (r) => ({ value: r.rejected_after_meeting }) },
  { head: "# OFERT", cell: (r) => ({ value: r.offers }) },
  { head: "Stawka min", cell: (r) => ({ value: r.offer_min_md }) },
  { head: "Stawka max", cell: (r) => ({ value: r.offer_max_md }) },
];

const FULL_COLUMNS: Column[] = [
  { head: "DOSTAWCA", cell: () => ({ value: "B2B.net S.A." }) },
  ...OPTION_COLUMNS.slice(0, 9),
  { head: "% CV SLA", cell: (r) => ({ value: percent(r.percent_cv_sla) }) },
  { head: "# RITM SLA", cell: (r) => ({ value: r.ritm_sla }) },
  { head: "RITM SLA i stawka", cell: (r) => ({ value: r.ritm_sla_and_budget }) },
  { head: "# ODRZ. CV", cell: (r) => ({ value: r.rejected_cv }) },
  { head: "# SPOTKAŃ", cell: (r) => ({ value: r.meetings }) },
  { head: "# ODRZ. PO SPOTK.", cell: (r) => ({ value: r.rejected_after_meeting }) },
  { head: "spotkań / CV", cell: (r) => ({ value: ratio(r.meetings_per_cv) }) },
  { head: "odrz. / CV", cell: (r) => ({ value: ratio(r.rejected_per_cv) }) },
  { head: "# OFERT", cell: (r) => ({ value: r.offers }) },
  { head: "uwagi", cell: () => ({ value: null }) },
  { head: "Widełki min", cell: (r) => bandCell(r, r.band_min_md) },
  { head: "Widełki max", cell: (r) => bandCell(r, r.band_max_md) },
  { head: "Średnia z umowy", cell: (r) => bandCell(r, r.band_average_md) },
  { head: "Stawka min", cell: (r) => ({ value: r.offer_min_md }) },
  { head: "Stawka max", cell: (r) => ({ value: r.offer_max_md }) },
  { head: "Śr. z rekom.", cell: (r) => ({ value: r.recommended_average_md }) },
  { head: "Rozb. od śr.", cell: (r) => ({ value: percent(r.percent_from_band_average) }) },
  { head: "Min − górna gr.", cell: (r) => ({ value: r.offer_min_minus_top }) },
  { head: "% różnicy", cell: (r) => ({ value: percent(r.percent_difference) }) },
];

function SheetTable({ columns, rows }: { columns: Column[]; rows: ReportRow[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-max min-w-full border-collapse text-xs">
        <thead>
          <tr className="bg-muted/60">
            {columns.map((column, index) => (
              <th
                key={index}
                className="max-w-[66px] border-b border-border px-1.5 py-2 text-left align-bottom text-[11px] font-semibold leading-tight text-muted-foreground"
              >
                {column.head}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.job_id} className="border-b border-border/60 last:border-0">
              {columns.map((column, index) => {
                const { value, flag } = column.cell(row);
                return (
                  <td key={index} className="px-1 py-1">
                    <span
                      title={typeof value === "string" ? value : undefined}
                      className={cn(
                        "inline-block min-w-[1.5rem] max-w-[160px] truncate whitespace-nowrap rounded px-1 align-bottom tabular-nums",
                        flag === "missing" && "bg-warning-muted text-warning-muted-foreground",
                        flag === "proposal" &&
                          "underline decoration-primary decoration-dotted underline-offset-2",
                      )}
                    >
                      {value ?? (flag === "missing" ? "brak" : "—")}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const FIELD = "h-8 w-full rounded-md border border-border bg-card px-2 text-xs disabled:opacity-60";

function FillTable({
  data,
  canEdit,
  onSave,
}: {
  data: ReportData;
  canEdit: boolean;
  onSave: (jobId: number, fields: Record<string, unknown>) => void;
}) {
  const bandsSaved = data.bands_source === "saved";
  return (
    <div className="space-y-2">
      {!bandsSaved ? (
        <p className="text-xs text-muted-foreground">
          Rolę z umowy wybierzesz po zapisaniu widełek w zakładce „Widełki z umowy”.
        </p>
      ) : null}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="bg-muted/60 text-left text-[11px] text-muted-foreground">
              <th className="px-2 py-2 font-semibold">Proces</th>
              <th className="w-[130px] px-2 py-2 font-semibold">START</th>
              <th className="w-[130px] px-2 py-2 font-semibold">RITM</th>
              <th className="w-[100px] px-2 py-2 font-semibold">Seniority</th>
              <th className="w-[240px] px-2 py-2 font-semibold">Rola z umowy</th>
              <th className="w-[90px] px-2 py-2 font-semibold">Widełki za MD</th>
              <th className="w-[90px] px-2 py-2 font-semibold">Stawki za MD</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.job_id} className="border-b border-border/60 last:border-0">
                <td className="px-2 py-1">
                  <a
                    href={`/jobs/${row.job_id}`}
                    title={row.title}
                    className="block max-w-[250px] truncate font-medium hover:underline"
                  >
                    {row.title}
                  </a>
                </td>
                <td className="px-2 py-1">
                  <input
                    key={row.start}
                    type="date"
                    aria-label={`START: ${row.title}`}
                    defaultValue={row.start}
                    disabled={!canEdit}
                    className={FIELD}
                    onBlur={(e) => {
                      if (e.target.value && e.target.value !== row.start) {
                        onSave(row.job_id, { start: e.target.value });
                      }
                    }}
                  />
                </td>
                <td className="px-2 py-1">
                  <input
                    key={row.ritm ?? ""}
                    aria-label={`RITM: ${row.title}`}
                    defaultValue={row.ritm ?? ""}
                    placeholder="uzupełnij"
                    maxLength={120}
                    disabled={!canEdit}
                    className={cn(FIELD, !row.ritm && "bg-warning-muted")}
                    onBlur={(e) => {
                      const value = e.target.value.trim();
                      if (value !== (row.ritm ?? "")) {
                        onSave(row.job_id, { client_reference: value });
                      }
                    }}
                  />
                </td>
                <td className="px-2 py-1">
                  <select
                    aria-label={`Seniority: ${row.title}`}
                    value={row.seniority ?? ""}
                    disabled={!canEdit}
                    className={cn(FIELD, !row.seniority && "bg-warning-muted")}
                    onChange={(e) => onSave(row.job_id, { seniority: e.target.value || null })}
                  >
                    <option value="">wybierz</option>
                    {data.seniority_options.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="px-2 py-1">
                  {bandsSaved ? (
                    <select
                      aria-label={`Rola z umowy: ${row.title}`}
                      value={row.rate_card_id ?? ""}
                      disabled={!canEdit}
                      className={cn(FIELD, !row.rate_card_id && "bg-warning-muted")}
                      onChange={(e) =>
                        onSave(row.job_id, {
                          rate_card_id: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                    >
                      <option value="">wybierz rolę</option>
                      {data.bands.map((band) => (
                        <option key={band.id} value={band.id ?? ""}>
                          {band.role}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="block truncate text-muted-foreground">
                      {row.contract_role ?? "brak propozycji"}
                    </span>
                  )}
                </td>
                <td className="whitespace-nowrap px-2 py-1 tabular-nums">
                  {row.band_min_md === null ? "—" : `${row.band_min_md}–${row.band_max_md}`}
                </td>
                <td className="whitespace-nowrap px-2 py-1 tabular-nums">
                  {row.offer_min_md === null ? "—" : `${row.offer_min_md}–${row.offer_max_md}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const BANDS_NOTE: Record<ReportData["bands_source"], string> = {
  saved: "Zapisane widełki klienta, zł/h netto. W pliku idą przeliczone na stawkę za MD.",
  contract:
    "Propozycja odczytana z umowy ramowej, zł/h netto. Sprawdź wartości i zapisz; raport korzysta z nich już teraz.",
  none: "Nie udało się odczytać tabeli stawek z umowy tego klienta.",
};

function BandsEditor({
  data,
  canEdit,
  clientId,
  onSaved,
}: {
  data: ReportData;
  canEdit: boolean;
  clientId: number;
  onSaved: () => void;
}) {
  const { showSuccess, showError } = useToast();
  const [bands, setBands] = useState(() =>
    data.bands.map((band) => ({
      role: band.role,
      minimum: String(band.minimum),
      maximum: String(band.maximum),
    })),
  );
  const invalid = bands.some(
    (band) =>
      !Number.isInteger(Number(band.minimum)) ||
      !Number.isInteger(Number(band.maximum)) ||
      Number(band.minimum) < 1 ||
      Number(band.minimum) > Number(band.maximum),
  );
  const save = useMutation({
    mutationFn: () =>
      api.put(`/api/clients/${clientId}/bnp-report/rate-bands`, {
        bands: bands.map((band) => ({
          role: band.role,
          minimum: Number(band.minimum),
          maximum: Number(band.maximum),
        })),
      }),
    onSuccess: () => {
      showSuccess("Zapisano widełki z umowy.");
      onSaved();
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać widełek.")),
  });
  const update = (index: number, field: "minimum" | "maximum", value: string) =>
    setBands((current) =>
      current.map((band, position) => (position === index ? { ...band, [field]: value } : band)),
    );
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">{BANDS_NOTE[data.bands_source]}</p>
        {canEdit && bands.length > 0 ? (
          <Button size="sm" disabled={invalid || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? "Zapisywanie…" : "Zapisz widełki"}
          </Button>
        ) : null}
      </div>
      {invalid ? (
        <p role="alert" className="text-xs text-destructive">
          Minimum musi być liczbą całkowitą nie większą niż maksimum.
        </p>
      ) : null}
      <div className="columns-2 gap-4">
        {bands.map((band, index) => (
          <div
            key={band.role}
            className="flex break-inside-avoid items-center justify-between gap-2 border-b border-border/60 py-1 text-xs"
          >
            <span className="min-w-0 flex-1 truncate" title={band.role}>
              {band.role}
            </span>
            <input
              aria-label={`Minimum: ${band.role}`}
              inputMode="numeric"
              value={band.minimum}
              disabled={!canEdit}
              onChange={(e) => update(index, "minimum", e.target.value)}
              className="h-7 w-14 rounded border border-border bg-card px-1 text-right tabular-nums disabled:opacity-60"
            />
            <input
              aria-label={`Maksimum: ${band.role}`}
              inputMode="numeric"
              value={band.maximum}
              disabled={!canEdit}
              onChange={(e) => update(index, "maximum", e.target.value)}
              className="h-7 w-14 rounded border border-border bg-card px-1 text-right tabular-nums disabled:opacity-60"
            />
          </div>
        ))}
      </div>
    </div>
  );
}

type ReportTab = "option" | "full" | "fill" | "bands";

export function BnpMonthlyReportDialog({
  clientId,
  onClose,
}: {
  clientId: number;
  onClose: () => void;
}) {
  const [month, setMonth] = useState(() => previousMonth().key);
  const [tab, setTab] = useState<ReportTab>("option");
  const [downloading, setDownloading] = useState(false);
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "recruitment_manage");
  const { showError } = useToast();
  const queryClient = useQueryClient();

  const report = useQuery({
    queryKey: ["bnp-report", clientId, month],
    enabled: /^\d{4}-\d{2}$/.test(month),
    queryFn: async () =>
      (await api.get(`/api/clients/${clientId}/bnp-report`, { params: { month } }))
        .data as ReportData,
  });
  const data = report.data;
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["bnp-report", clientId] });

  const saveJob = useMutation({
    mutationFn: ({ jobId, fields }: { jobId: number; fields: Record<string, unknown> }) =>
      api.patch(`/api/clients/${clientId}/bnp-report/jobs/${jobId}`, fields),
    onSuccess: () => {
      void refresh();
      void queryClient.invalidateQueries({ queryKey: ["client-jobs", clientId] });
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać zmiany.")),
  });

  const download = async () => {
    setDownloading(true);
    try {
      const blob = await fetchAuthenticatedBlob(
        `/api/clients/${clientId}/bnp-report/export?month=${month}`,
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `Raport BNP ${month}.xlsx`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać raportu."));
    } finally {
      setDownloading(false);
    }
  };

  const attention = data?.rows.filter((row) => row.needs_attention).length;

  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      size="2xl"
      title="Raport miesięczny BNP"
      description="Procesy otwarte w wybranym miesiącu, stan na dzień pobrania. Kwoty za MD, układ kolumn z szablonu BNP."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Zamknij
          </Button>
          <Button disabled={!data?.rows.length || downloading} onClick={() => void download()}>
            <Download className="h-3.5 w-3.5" aria-hidden="true" />
            {downloading ? "Pobieranie…" : "Pobierz Excel"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <TabbedNav
            ariaLabel="Arkusze raportu"
            className="sm:w-auto"
            listClassName="sm:w-auto"
            value={tab}
            onValueChange={(value) => setTab(value as ReportTab)}
            tabs={[
              { value: "option", label: "Arkusz 1", count: data?.rows.length },
              { value: "full", label: "Cały raport", count: data?.rows.length },
              { value: "fill", label: "Do uzupełnienia", count: attention },
              { value: "bands", label: "Widełki z umowy", count: data?.bands.length },
            ]}
          />
          <Input
            type="month"
            aria-label="Miesiąc raportu"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            className="h-9 w-[170px]"
          />
        </div>

        {report.isLoading ? (
          <div className="py-8 text-center text-sm text-muted-foreground">Ładowanie…</div>
        ) : report.isError ? (
          <div className="py-8 text-center text-sm text-muted-foreground">
            {apiErrorMessage(report.error, "Nie udało się załadować raportu.")}
          </div>
        ) : !data ? null : tab === "bands" ? (
          <BandsEditor
            key={`${data.bands_source}-${data.bands.length}`}
            data={data}
            canEdit={canEdit}
            clientId={clientId}
            onSaved={() => void refresh()}
          />
        ) : data.rows.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground">
            W tym miesiącu nie otwarto żadnego procesu.
          </div>
        ) : tab === "fill" ? (
          <FillTable
            data={data}
            canEdit={canEdit}
            onSave={(jobId, fields) => saveJob.mutate({ jobId, fields })}
          />
        ) : (
          <>
            <p className="flex flex-wrap items-center gap-x-4 text-xs text-muted-foreground">
              <span>
                <span className="rounded bg-warning-muted px-1 text-warning-muted-foreground">
                  brak
                </span>{" "}
                trzeba uzupełnić
              </span>
              <span>
                <span className="underline decoration-primary decoration-dotted underline-offset-2">
                  propozycja
                </span>{" "}
                z nazwy lub opisu, do sprawdzenia
              </span>
            </p>
            <SheetTable columns={tab === "option" ? OPTION_COLUMNS : FULL_COLUMNS} rows={data.rows} />
          </>
        )}
      </div>
    </AppModal>
  );
}
