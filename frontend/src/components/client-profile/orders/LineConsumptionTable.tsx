"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, Pencil, Trash2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
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

/** Jedno zapytanie o rozliczenia linii — wspólne dla tabeli i okna, które
 *  z tych samych danych bierze numer zamówienia do nagłówka (ten sam klucz,
 *  więc react-query wysyła jedno żądanie). */
export function useLineConsumptions(
  clientId: number,
  groupId: number,
  lineId: number,
  enabled: boolean,
) {
  return useQuery({
    queryKey: lineConsumptionsQueryKey(clientId, groupId, lineId),
    queryFn: async () => (await orderGroupsApi.listConsumptions(clientId, groupId, lineId)).data,
    enabled,
  });
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

export interface LineConsumptionTableProps {
  clientId: number;
  group: OrderGroupRead;
  line: OrderLineRead;
  /** Bez uprawnień do obsady tabela jest samym podglądem. */
  canEdit: boolean;
  /** Pobieranie i reset formularza — okno podaje tu `open`. */
  enabled?: boolean;
  /** Wąski panel boczny (~380 px): trzy kolumny, reszta w rozwijanych
   *  szczegółach wiersza, formularz w jednej kolumnie. */
  compact?: boolean;
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
export function LineConsumptionTable({
  clientId,
  group,
  line,
  canEdit,
  enabled = true,
  compact = false,
}: LineConsumptionTableProps) {
  const queryClient = useQueryClient();
  const queryKey = lineConsumptionsQueryKey(clientId, group.id, line.id);
  const fieldId = useId();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editingMonth, setEditingMonth] = useState<string | null>(null);
  const [confirmDeleteMonth, setConfirmDeleteMonth] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [expandedMonths, setExpandedMonths] = useState<ReadonlySet<string>>(new Set());

  useEffect(() => {
    if (!enabled) return;
    setForm(EMPTY_FORM);
    setEditingMonth(null);
    setConfirmDeleteMonth(null);
    setFormError(null);
    setExpandedMonths(new Set());
  }, [enabled, line.id]);

  const rows = useLineConsumptions(clientId, group.id, line.id, enabled);

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

  function toggleExpanded(month: string) {
    setExpandedMonths((prev) => {
      const next = new Set(prev);
      if (next.has(month)) next.delete(month);
      else next.add(month);
      return next;
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
  // Zwarty widok: Miesiąc, MD, Saldo (+ Akcje); reszta w szczegółach wiersza.
  const columnCount = (compact ? 3 : 7) + (canEdit ? 1 : 0);
  // Miesiąc edytowanego wpisu może leżeć poza okresem (import za wcześniejszy
  // miesiąc) — musi być na liście, inaczej zablokowany select pokazałby pustkę.
  const selectOptions =
    form.month && !monthOptions.some((option) => option.value === form.month)
      ? [{ value: form.month, label: monthLabelPl(form.month) }, ...monthOptions]
      : monthOptions;

  const cell = compact ? "py-1.5 pr-2" : "py-2 pr-3";
  const headCell = compact ? "py-1 pr-2 font-semibold" : "py-1.5 pr-3 font-semibold";
  const ids = {
    month: `${fieldId}-consumption-month`,
    md: `${fieldId}-consumption-md`,
    status: `${fieldId}-consumption-status`,
    note: `${fieldId}-consumption-note`,
  };

  function importRefs(row: LineConsumptionRow) {
    const importRows = row.import_rows ?? [];
    if (importRows.length === 0) return "—";
    return importRows.map((ref) => (
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
    ));
  }

  function rowActions(row: LineConsumptionRow) {
    const confirming = confirmDeleteMonth === row.period_month;
    return (
      <td className={cn(compact ? "py-1.5" : "py-2", "text-right")}>
        {confirming ? (
          <span
            className={cn(
              "inline-flex items-center gap-1",
              compact && "flex-wrap justify-end",
            )}
          >
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
    );
  }

  return (
    <div className={cn("flex flex-col", compact ? "gap-3" : "gap-4")}>
      {rows.isSuccess ? (
        <dl
          className={cn(
            "grid grid-cols-3 gap-2 rounded-md border border-border bg-muted/30 text-sm",
            compact ? "p-2" : "p-3",
          )}
        >
          <div>
            <dt className="text-xs text-muted-foreground">Wykorzystane</dt>
            <dd className="font-semibold tabular-nums text-foreground">{formatMd(used)} MD</dd>
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
                Za {monthLabelPl(warning.period_month)} zaksięgowano {formatMd(warning.md)} MD
                z wiersza importu nr {warning.row_number} z numerem zamówienia{" "}
                <strong>{warning.order_number}</strong> — innym niż to zamówienie.
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
          {canEdit ? "Brak wpisów miesięcznych — dodaj pierwszy." : "Brak wpisów miesięcznych."}
        </p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className={cn("w-full text-sm", !compact && "min-w-[46rem]")}>
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className={headCell}>Miesiąc</th>
                <th className={cn(headCell, "text-right")}>MD</th>
                {compact ? null : (
                  <>
                    <th className={headCell}>Nr z importu</th>
                    <th className={headCell}>Źródło</th>
                  </>
                )}
                <th className={cn(headCell, "text-right")}>
                  {compact ? "Saldo" : "Saldo po miesiącu"}
                </th>
                {compact ? null : (
                  <>
                    <th className={headCell}>Autor</th>
                    <th className={headCell}>Notatka</th>
                  </>
                )}
                {canEdit ? <th className="py-1.5 font-semibold sr-only">Akcje</th> : null}
              </tr>
            </thead>
            {/* Jeden `<tbody>` na miesiąc: korekty stoją POD swoim miesiącem,
                bez kreski oddzielającej, kreska dzieli dopiero miesiące. */}
            {rows.data.rows.map((row) => {
              const corrections = row.corrections ?? [];
              const expanded = compact && expandedMonths.has(row.period_month);
              const monthLabel = formatPeriodMonthPl(row.period_month);
              const detailsId = `${fieldId}-details-${row.period_month}`;
              return (
                <tbody key={row.period_month} className="border-t border-border">
                  <tr className={cn(editingMonth === row.period_month && "bg-primary/5")}>
                    <td className={cn(cell, "font-medium text-foreground")}>
                      {compact ? (
                        <button
                          type="button"
                          onClick={() => toggleExpanded(row.period_month)}
                          aria-expanded={expanded}
                          aria-controls={expanded ? detailsId : undefined}
                          title={expanded ? "Ukryj szczegóły" : "Pokaż szczegóły"}
                          className="inline-flex items-center gap-1 rounded-md py-0.5 pointer-coarse:py-2 text-left hover:text-primary"
                        >
                          <ChevronDown
                            className={cn(
                              "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
                              expanded && "rotate-180",
                            )}
                            aria-hidden
                          />
                          <span>{monthLabel}</span>
                        </button>
                      ) : (
                        monthLabel
                      )}
                    </td>
                    <td className={cn(cell, "text-right tabular-nums text-foreground")}>
                      {formatMd(row.md_reported)}
                      {row.status ? (
                        <span className="ml-1 block text-[11px] text-muted-foreground">
                          {CONSUMPTION_STATUS_LABEL[row.status]}
                        </span>
                      ) : null}
                    </td>
                    {compact ? null : (
                      <>
                        <td className={cn(cell, "text-muted-foreground")}>{importRefs(row)}</td>
                        <td className={cn(cell, "text-muted-foreground")}>{sourceLabel(row)}</td>
                      </>
                    )}
                    <td
                      className={cn(
                        cell,
                        "text-right font-medium tabular-nums",
                        row.balance_after != null && row.balance_after < 0
                          ? "text-destructive"
                          : "text-foreground",
                      )}
                    >
                      {row.balance_after == null ? "—" : formatMd(row.balance_after)}
                    </td>
                    {compact ? null : (
                      <>
                        <td
                          className={cn(cell, "max-w-[10rem] truncate text-muted-foreground")}
                          title={row.updated_at ? formatDateTimePl(row.updated_at) : undefined}
                        >
                          {row.created_by_name ?? "—"}
                        </td>
                        <td
                          className={cn(cell, "max-w-[12rem] truncate text-muted-foreground")}
                          title={row.note ?? undefined}
                        >
                          {row.note ?? "—"}
                        </td>
                      </>
                    )}
                    {canEdit ? rowActions(row) : null}
                  </tr>
                  {expanded ? (
                    <tr id={detailsId} className="text-xs">
                      <td colSpan={columnCount} className="pb-2 pl-5 pt-0">
                        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                          <dt className="text-muted-foreground">Nr z importu</dt>
                          <dd className="text-foreground">{importRefs(row)}</dd>
                          <dt className="text-muted-foreground">Źródło</dt>
                          <dd className="text-foreground">{sourceLabel(row)}</dd>
                          <dt className="text-muted-foreground">Autor</dt>
                          <dd
                            className="text-foreground"
                            title={row.updated_at ? formatDateTimePl(row.updated_at) : undefined}
                          >
                            {row.created_by_name ?? "—"}
                          </dd>
                          <dt className="text-muted-foreground">Notatka</dt>
                          <dd className="break-words text-foreground">{row.note ?? "—"}</dd>
                        </dl>
                      </td>
                    </tr>
                  ) : null}
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
                <td className={cn(cell, "font-semibold")}>Razem</td>
                <td className={cn(cell, "text-right font-semibold tabular-nums text-foreground")}>
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
          <div className={cn("grid grid-cols-1 gap-3", !compact && "sm:grid-cols-3")}>
            <div>
              <label htmlFor={ids.month} className={labelClass}>
                Miesiąc *
              </label>
              <select
                id={ids.month}
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
              <label htmlFor={ids.md} className={labelClass}>
                MD *
              </label>
              <input
                id={ids.md}
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
              <label htmlFor={ids.status} className={labelClass}>
                Status
              </label>
              <select
                id={ids.status}
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
            <label htmlFor={ids.note} className={labelClass}>
              Notatka
            </label>
            <input
              id={ids.note}
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
  );
}
