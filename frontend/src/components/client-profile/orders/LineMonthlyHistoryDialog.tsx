"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Pencil, Trash2 } from "lucide-react";

import { AppModal, QueryStateNotice } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api-error";
import {
  orderGroupsApi,
  type LineConsumptionCorrection,
  type LineConsumptionRow,
  type LineConsumptionStatus,
  type OrderGroupRead,
  type OrderLineRead,
} from "@/lib/api/orderGroups";
import { formatDateTimePl } from "@/lib/date-pl";
import { consumptionMonthOptions, monthLabelPl } from "@/lib/order-consumption";
import { cn, parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";

import { formatMd } from "./MdBudgetBar";

/** Etykiety statusu rozliczenia. CELOWO w warstwie prezentacji, nie w
 *  `lib/api` — testy komponentów mockują `@/lib/api/*` w całości, więc stała
 *  trzymana tam wychodziłaby w nich jako `undefined`. */
export const CONSUMPTION_STATUS_LABEL: Record<LineConsumptionStatus, string> = {
  accepted: "Zaakceptowany",
  protocol: "Protokół",
};

const SOURCE_LABEL: Record<NonNullable<LineConsumptionRow["source_kind"]>, string> = {
  import: "import",
  manual: "ręcznie",
  manual_correction: "ręczna korekta",
};

function sourceLabel(row: LineConsumptionRow): string {
  return SOURCE_LABEL[row.source_kind ?? row.source] ?? row.source;
}

/** „gru 2025" z `YYYY-MM`. Dzień 15 zamiast 1: data składana lokalnie, więc
 *  strefa czasowa nie ma jak cofnąć miesiąca. */
export function formatPeriodMonthPl(period: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) return period;
  return new Intl.DateTimeFormat("pl-PL", { month: "short", year: "numeric" }).format(
    new Date(Number(match[1]), Number(match[2]) - 1, 15),
  );
}

/** „import 4 MD → ręcznie 3,7 MD" — treść jednej korekty miesiąca. */
export function correctionText(correction: LineConsumptionCorrection): string {
  const from =
    correction.from_md == null || correction.from_source === "none"
      ? "brak wpisu"
      : `${correction.from_source === "import" ? "import" : "ręcznie"} ${formatMd(
          correction.from_md,
        )} MD`;
  const to = correction.removed ? "usunięto" : `ręcznie ${formatMd(correction.to_md)} MD`;
  return `${from} → ${to}`;
}

function correctionLine(correction: LineConsumptionCorrection): string {
  return `↳ korekta: ${formatDateTimePl(correction.created_at)} · ${
    correction.author_name ?? "Automatycznie (system)"
  } · ${correctionText(correction)}`;
}

export function lineConsumptionsQueryKey(
  clientId: number,
  groupId: number,
  lineId: number,
) {
  return ["order-line-consumptions", clientId, groupId, lineId] as const;
}

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass = "mb-1 block text-xs font-semibold text-muted-foreground";

interface FormState {
  month: string;
  md: string;
  status: LineConsumptionStatus | "";
  note: string;
}

const EMPTY_FORM: FormState = { month: "", md: "", status: "", note: "" };

interface Props {
  clientId: number;
  group: OrderGroupRead;
  line: OrderLineRead;
  /** Bez uprawnień do obsady dialog jest samym podglądem. */
  canEdit: boolean;
  open: boolean;
  onClose: () => void;
}

/**
 * „Zużycie MD" jednej osoby — miesiąc po miesiącu, z saldem po każdym
 * miesiącu, numerem zamówienia z importu i korektami pod miesiącem, którego
 * dotyczą (ticket 7, 25.09.2026).
 *
 * Zapis idzie PUT-em po miesiącu (powtórka nadpisuje), więc „edycja" wpisu to
 * ten sam formularz z zablokowanym miesiącem: zmiana miesiąca w edycji
 * założyłaby drugi wpis zamiast przenieść ten, co czyta się jak duplikat.
 * Usunięcie jest dwustopniowe w wierszu — bez `window.confirm`, który zamraża
 * automatyzację przeglądarki.
 */
export function LineMonthlyHistoryDialog({
  clientId,
  group,
  line,
  canEdit,
  open,
  onClose,
}: Props) {
  const queryClient = useQueryClient();
  const queryKey = lineConsumptionsQueryKey(clientId, group.id, line.id);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editingMonth, setEditingMonth] = useState<string | null>(null);
  const [confirmDeleteMonth, setConfirmDeleteMonth] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setForm(EMPTY_FORM);
    setEditingMonth(null);
    setConfirmDeleteMonth(null);
    setFormError(null);
  }, [open, line.id]);

  const rows = useQuery({
    queryKey,
    queryFn: async () =>
      (await orderGroupsApi.listConsumptions(clientId, group.id, line.id)).data,
    enabled: open,
  });

  // Miesiące okresu osoby na zamówieniu — lista zamiast pełnej daty.
  const monthOptions = useMemo(
    () =>
      consumptionMonthOptions(
        line.start_date ?? group.start_date,
        line.end_date ?? group.end_date,
        new Date(),
      ),
    [line.start_date, line.end_date, group.start_date, group.end_date],
  );
  const existingMonths = new Set(rows.data?.rows.map((row) => row.period_month) ?? []);

  // Po zapisie linia ma nowe zużycie (paski na karcie), a historia zamówienia
  // nowy wpis — obie listy muszą się odświeżyć, nie tylko ta tabela.
  const invalidateAfterWrite = () => {
    queryClient.invalidateQueries({ queryKey });
    queryClient.invalidateQueries({ queryKey: ["client-order-groups", clientId] });
    queryClient.invalidateQueries({ queryKey: ["order-group-events", clientId] });
  };

  const save = useMutation({
    mutationFn: (values: {
      month: string;
      md: number;
      status: LineConsumptionStatus | null;
      note: string | null;
    }) =>
      orderGroupsApi.putConsumption(clientId, group.id, line.id, values.month, {
        md_reported: values.md,
        status: values.status,
        note: values.note,
      }),
    onSuccess: () => {
      setForm(EMPTY_FORM);
      setEditingMonth(null);
      setFormError(null);
      invalidateAfterWrite();
    },
    onError: (err) =>
      setFormError(apiErrorMessage(err, "Nie udało się zapisać wpisu miesięcznego.")),
  });

  const remove = useMutation({
    mutationFn: (month: string) =>
      orderGroupsApi.deleteConsumption(clientId, group.id, line.id, month),
    onSuccess: () => {
      setConfirmDeleteMonth(null);
      setFormError(null);
      invalidateAfterWrite();
    },
    onError: (err) =>
      setFormError(apiErrorMessage(err, "Nie udało się usunąć wpisu miesięcznego.")),
  });

  const parsedMd = parseDecimalInput(form.md);
  const canSave =
    canEdit &&
    !save.isPending &&
    /^\d{4}-\d{2}$/.test(form.month) &&
    parsedMd !== null &&
    parsedMd >= 0;

  function startEdit(row: LineConsumptionRow) {
    setEditingMonth(row.period_month);
    setConfirmDeleteMonth(null);
    setForm({
      month: row.period_month,
      md: String(row.md_reported),
      status: row.status ?? "",
      note: row.note ?? "",
    });
  }

  function submit() {
    if (!canSave || parsedMd === null) return;
    save.mutate({
      month: form.month,
      md: parsedMd,
      status: form.status === "" ? null : form.status,
      note: form.note.trim() || null,
    });
  }

  const data = rows.data;
  const totalMd = data?.rows.reduce((sum, row) => sum + row.md_reported, 0) ?? 0;
  const used = data?.md_used ?? totalMd;
  const remaining = data?.md_remaining ?? line.md_remaining;
  const budget = data?.md_budget ?? null;
  const columnCount = canEdit ? 8 : 7;
  // Miesiąc edytowanego wpisu może leżeć poza okresem (import za wcześniejszy
  // miesiąc) — musi być na liście, inaczej zablokowany select pokazałby pustkę.
  const selectOptions =
    form.month && !monthOptions.some((option) => option.value === form.month)
      ? [{ value: form.month, label: monthLabelPl(form.month) }, ...monthOptions]
      : monthOptions;

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      size="xl"
      title={`Zużycie MD — ${line.consultant_name}`}
      description={`Zamówienie nr ${data?.order_number ?? group.order_number}`}
      footer={
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-muted"
        >
          Zamknij
        </button>
      }
    >
      <div className="flex flex-col gap-4">
        {rows.isSuccess ? (
          <dl className="grid grid-cols-3 gap-2 rounded-md border border-border bg-muted/30 p-3 text-sm">
            <div>
              <dt className="text-xs text-muted-foreground">Wykorzystane</dt>
              <dd className="font-semibold tabular-nums text-foreground">
                {formatMd(used)} MD
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Budżet</dt>
              <dd className="font-semibold tabular-nums text-foreground">
                {budget == null ? "—" : `${formatMd(budget)} MD`}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Pozostało</dt>
              <dd
                className={cn(
                  "font-semibold tabular-nums",
                  remaining != null && remaining < 0 ? "text-destructive" : "text-foreground",
                )}
              >
                {remaining == null ? "—" : `${formatMd(remaining)} MD`}
              </dd>
            </div>
          </dl>
        ) : null}

        {(data?.foreign_import_warnings ?? []).length > 0 ? (
          <div
            role="alert"
            className="flex gap-2 rounded-md border border-warning/50 bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <ul className="space-y-0.5">
              {data!.foreign_import_warnings!.map((warning) => (
                <li key={`${warning.import_id}-${warning.row_number}`}>
                  Za {monthLabelPl(warning.period_month)} zaksięgowano{" "}
                  {formatMd(warning.md)} MD z wiersza importu nr {warning.row_number} z
                  numerem zamówienia <strong>{warning.order_number}</strong> — innym niż to
                  zamówienie.
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {formError ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {formError}
          </p>
        ) : null}

        {rows.isError ? (
          // Awaria pobrania nie może wyglądać jak „brak wpisów" — pustka
          // czytałaby się jak zero rozliczeń, czyli jak fakt handlowy.
          <QueryStateNotice
            state="error"
            description="Nie udało się wczytać rozliczeń miesięcznych tej osoby."
            onRetry={() => rows.refetch()}
          />
        ) : !rows.isSuccess ? (
          // `isSuccess`, nie `!isLoading`: między ponowieniami react-query ma
          // puste `data` i `isLoading === false`, a pusty stan nie może
          // wygrać, zanim cokolwiek wiadomo.
          <p className="text-sm text-muted-foreground">Wczytywanie rozliczeń…</p>
        ) : rows.data.rows.length === 0 ? (
          <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
            {canEdit
              ? "Brak wpisów miesięcznych — dodaj pierwszy."
              : "Brak wpisów miesięcznych."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[46rem] text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="py-1.5 pr-3 font-semibold">Miesiąc</th>
                  <th className="py-1.5 pr-3 text-right font-semibold">MD</th>
                  <th className="py-1.5 pr-3 font-semibold">Nr z importu</th>
                  <th className="py-1.5 pr-3 font-semibold">Źródło</th>
                  <th className="py-1.5 pr-3 text-right font-semibold">Saldo po miesiącu</th>
                  <th className="py-1.5 pr-3 font-semibold">Autor</th>
                  <th className="py-1.5 pr-3 font-semibold">Notatka</th>
                  {canEdit ? <th className="py-1.5 font-semibold sr-only">Akcje</th> : null}
                </tr>
              </thead>
              {/* Jeden `<tbody>` na miesiąc: korekty stoją POD swoim miesiącem,
                  bez kreski oddzielającej, kreska dzieli dopiero miesiące. */}
                {rows.data.rows.map((row) => {
                  const confirming = confirmDeleteMonth === row.period_month;
                  const importRows = row.import_rows ?? [];
                  const corrections = row.corrections ?? [];
                  return (
                    <tbody key={row.period_month} className="border-t border-border">
                      <tr className={cn(editingMonth === row.period_month && "bg-primary/5")}>
                        <td className="py-2 pr-3 font-medium text-foreground">
                          {formatPeriodMonthPl(row.period_month)}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-foreground">
                          {formatMd(row.md_reported)}
                          {row.status ? (
                            <span className="ml-1 block text-[11px] text-muted-foreground">
                              {CONSUMPTION_STATUS_LABEL[row.status]}
                            </span>
                          ) : null}
                        </td>
                        <td className="py-2 pr-3 text-muted-foreground">
                          {importRows.length === 0
                            ? "—"
                            : importRows.map((ref) => (
                                <span
                                  key={`${ref.import_id}-${ref.row_number}`}
                                  className={cn(
                                    "block tabular-nums",
                                    ref.foreign && "font-semibold text-warning-muted-foreground",
                                  )}
                                  title={`Wiersz ${ref.row_number} importu · ${formatMd(ref.md_reported)} MD`}
                                >
                                  {ref.order_number_hint ?? "bez numeru"}
                                  {importRows.length > 1 ? ` (${formatMd(ref.md_reported)})` : ""}
                                </span>
                              ))}
                        </td>
                        <td className="py-2 pr-3 text-muted-foreground">{sourceLabel(row)}</td>
                        <td
                          className={cn(
                            "py-2 pr-3 text-right font-medium tabular-nums",
                            row.balance_after != null && row.balance_after < 0
                              ? "text-destructive"
                              : "text-foreground",
                          )}
                        >
                          {row.balance_after == null ? "—" : formatMd(row.balance_after)}
                        </td>
                        <td
                          className="max-w-[10rem] truncate py-2 pr-3 text-muted-foreground"
                          title={row.updated_at ? formatDateTimePl(row.updated_at) : undefined}
                        >
                          {row.created_by_name ?? "—"}
                        </td>
                        <td
                          className="max-w-[12rem] truncate py-2 pr-3 text-muted-foreground"
                          title={row.note ?? undefined}
                        >
                          {row.note ?? "—"}
                        </td>
                        {canEdit ? (
                          <td className="py-2 text-right">
                            {confirming ? (
                              <span className="inline-flex items-center gap-1">
                                <button
                                  type="button"
                                  disabled={remove.isPending}
                                  onClick={() => remove.mutate(row.period_month)}
                                  className="rounded-md bg-destructive px-2 py-1 text-xs font-semibold text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
                                >
                                  Potwierdź usunięcie
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setConfirmDeleteMonth(null)}
                                  className="rounded-md border border-border px-2 py-1 text-xs font-medium text-foreground hover:bg-muted"
                                >
                                  Anuluj
                                </button>
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1">
                                <button
                                  type="button"
                                  onClick={() => startEdit(row)}
                                  aria-label={`Edytuj wpis za ${formatPeriodMonthPl(row.period_month)}`}
                                  title="Edytuj"
                                  className="rounded-md p-1.5 pointer-coarse:p-2.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                                >
                                  <Pencil className="h-4 w-4" aria-hidden />
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setConfirmDeleteMonth(row.period_month)}
                                  aria-label={`Usuń wpis za ${formatPeriodMonthPl(row.period_month)}`}
                                  title="Usuń"
                                  className="rounded-md p-1.5 pointer-coarse:p-2.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                                >
                                  <Trash2 className="h-4 w-4" aria-hidden />
                                </button>
                              </span>
                            )}
                          </td>
                        ) : null}
                      </tr>
                      {corrections.map((correction, index) => (
                        <tr
                          key={`${row.period_month}-korekta-${index}`}
                          className="text-xs text-muted-foreground"
                        >
                          <td colSpan={columnCount} className="pb-1 pl-4 pt-0">
                            {correctionLine(correction)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  );
                })}
              <tfoot>
                <tr className="border-t border-border text-xs text-muted-foreground">
                  <td className="py-2 pr-3 font-semibold">Razem</td>
                  <td className="py-2 pr-3 text-right font-semibold tabular-nums text-foreground">
                    {formatMd(totalMd)}
                  </td>
                  <td colSpan={columnCount - 2} />
                </tr>
              </tfoot>
            </table>
          </div>
        )}

        {(data?.removed_months ?? []).length > 0 ? (
          <div className="text-xs text-muted-foreground">
            <p className="font-semibold">Usunięte wpisy</p>
            <ul className="mt-1 space-y-0.5">
              {data!.removed_months!.map((correction, index) => (
                <li key={`usuniete-${index}`}>
                  {correction.period_month ? `${monthLabelPl(correction.period_month)}: ` : ""}
                  {correctionLine(correction)}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {canEdit ? (
          <fieldset className="rounded-md border border-border p-3">
            <legend className="px-1 text-xs font-semibold text-muted-foreground">
              {editingMonth
                ? `Edycja wpisu za ${formatPeriodMonthPl(editingMonth)}`
                : "Nowy wpis miesięczny"}
            </legend>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <label htmlFor="consumption-month" className={labelClass}>
                  Miesiąc *
                </label>
                <select
                  id="consumption-month"
                  value={form.month}
                  disabled={editingMonth !== null}
                  onChange={(event) => setForm((prev) => ({ ...prev, month: event.target.value }))}
                  className={inputClass}
                >
                  <option value="">Wybierz miesiąc…</option>
                  {selectOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                      {existingMonths.has(option.value) && editingMonth === null
                        ? " — ma wpis (nadpisze)"
                        : ""}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="consumption-md" className={labelClass}>
                  MD *
                </label>
                <input
                  id="consumption-md"
                  inputMode="decimal"
                  value={form.md}
                  onChange={(event) =>
                    setForm((prev) => ({ ...prev, md: sanitizeDecimalInput(event.target.value) }))
                  }
                  className={inputClass}
                  placeholder="20,5"
                />
              </div>
              <div>
                <label htmlFor="consumption-status" className={labelClass}>
                  Status
                </label>
                <select
                  id="consumption-status"
                  value={form.status}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      status: event.target.value as FormState["status"],
                    }))
                  }
                  className={inputClass}
                >
                  <option value="">—</option>
                  <option value="protocol">{CONSUMPTION_STATUS_LABEL.protocol}</option>
                  <option value="accepted">{CONSUMPTION_STATUS_LABEL.accepted}</option>
                </select>
              </div>
            </div>
            <div className="mt-3">
              <label htmlFor="consumption-note" className={labelClass}>
                Notatka
              </label>
              <input
                id="consumption-note"
                value={form.note}
                onChange={(event) => setForm((prev) => ({ ...prev, note: event.target.value }))}
                className={inputClass}
              />
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={submit}
                disabled={!canSave}
                className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {save.isPending ? "Zapisywanie…" : editingMonth ? "Zapisz zmiany" : "Dodaj wpis"}
              </button>
              {editingMonth ? (
                <button
                  type="button"
                  onClick={() => {
                    setEditingMonth(null);
                    setForm(EMPTY_FORM);
                  }}
                  className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted"
                >
                  Anuluj edycję
                </button>
              ) : null}
            </div>
          </fieldset>
        ) : null}
      </div>
    </AppModal>
  );
}
