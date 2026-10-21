"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, Pencil, Trash2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api-error";
import {
  orderGroupsApi,
  type CostConsumptionRow,
  type LineConsumptionStatus,
  type OrderGroupRead,
  type OrderLineRead,
} from "@/lib/api/orderGroups";
import { previewCostEntry } from "@/lib/cost-consumption";
import { formatDateTimePl } from "@/lib/date-pl";
import { consumptionMonthOptions, monthLabelPl } from "@/lib/order-consumption";
import { cn, parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";
import { formatPLN } from "@/types/client-profile";

import { CONSUMPTION_STATUS_LABEL, formatPeriodMonthPl } from "./LineConsumptionTable";

export function lineCostConsumptionsQueryKey(clientId: number, groupId: number, lineId: number) {
  return ["order-line-cost-consumptions", clientId, groupId, lineId] as const;
}

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass = "mb-1 block text-xs font-semibold text-muted-foreground";

interface FormState {
  month: string;
  amount: string;
  status: LineConsumptionStatus | "";
  note: string;
}

const EMPTY_FORM: FormState = { month: "", amount: "", status: "", note: "" };

export interface CostConsumptionTabProps {
  clientId: number;
  group: OrderGroupRead;
  line: OrderLineRead;
  canEdit: boolean;
}

/**
 * „Zużycie” osoby na zamówieniu kosztowym (ticket 21.10.2026, wersja B makiet).
 *
 * Kafelki i saldo opisują WSPÓLNY budżet zamówienia, nie osobę — kwota mieszka
 * na grupie, więc „pozostało” liczone per osoba pokazywałoby za dużo, gdy
 * resztę zużył ktoś inny. Udział osób stoi pod paskiem. Podgląd i ostrzeżenie
 * o przekroczeniu liczą się przed zapisem tą samą kolejnością co serwer.
 * Usunięcie jest dwustopniowe w wierszu — bez `window.confirm`.
 */
export function CostConsumptionTab({ clientId, group, line, canEdit }: CostConsumptionTabProps) {
  const queryClient = useQueryClient();
  const queryKey = lineCostConsumptionsQueryKey(clientId, group.id, line.id);
  const fieldId = useId();
  const missingMonth = line.missing_consumption_month ?? null;
  const initialForm = (): FormState => ({ ...EMPTY_FORM, month: missingMonth ?? "" });
  const [form, setForm] = useState<FormState>(initialForm);
  const [editingMonth, setEditingMonth] = useState<string | null>(null);
  const [confirmDeleteMonth, setConfirmDeleteMonth] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [expandedMonths, setExpandedMonths] = useState<ReadonlySet<string>>(new Set());

  useEffect(() => {
    setForm(initialForm());
    setEditingMonth(null);
    setConfirmDeleteMonth(null);
    setFormError(null);
    setExpandedMonths(new Set());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [line.id]);

  const query = useQuery({
    queryKey,
    queryFn: async () => (await orderGroupsApi.listCostConsumptions(clientId, group.id, line.id)).data,
  });

  const monthOptions = useMemo(
    () =>
      consumptionMonthOptions(line.start_date ?? group.start_date, line.end_date ?? group.end_date, new Date()),
    [line.start_date, line.end_date, group.start_date, group.end_date],
  );

  // Po zapisie zmienia się karta zamówienia (zafakturowano, pozostało, uwaga
  // „Brak zejścia”) i historia — nie tylko ta tabela.
  const invalidateAfterWrite = () => {
    queryClient.invalidateQueries({ queryKey });
    queryClient.invalidateQueries({ queryKey: ["client-order-groups", clientId] });
    queryClient.invalidateQueries({ queryKey: ["order-group-events", clientId] });
  };

  const save = useMutation({
    mutationFn: (values: { month: string; amount: number; status: LineConsumptionStatus | null; note: string | null }) =>
      orderGroupsApi.putCostConsumption(clientId, group.id, line.id, values.month, {
        invoice_amount: values.amount,
        status: values.status,
        note: values.note,
      }),
    onSuccess: (response) => {
      queryClient.setQueryData(queryKey, response.data);
      setForm(EMPTY_FORM);
      setEditingMonth(null);
      setFormError(null);
      invalidateAfterWrite();
    },
    onError: (err) => setFormError(apiErrorMessage(err, "Nie udało się zapisać wpisu miesięcznego.")),
  });

  const remove = useMutation({
    mutationFn: (month: string) => orderGroupsApi.deleteCostConsumption(clientId, group.id, line.id, month),
    onSuccess: (response) => {
      queryClient.setQueryData(queryKey, response.data);
      setConfirmDeleteMonth(null);
      setFormError(null);
      invalidateAfterWrite();
    },
    onError: (err) => setFormError(apiErrorMessage(err, "Nie udało się usunąć wpisu miesięcznego.")),
  });

  const data = query.data;
  const parsedAmount = parseDecimalInput(form.amount);
  const validMonth = /^\d{4}-\d{2}$/.test(form.month);
  const canSave = canEdit && !save.isPending && validMonth && parsedAmount !== null && parsedAmount >= 0;
  const preview =
    data && validMonth && parsedAmount !== null && parsedAmount >= 0
      ? previewCostEntry(data.budget_pool, data.group_rows, {
          orderId: line.id,
          periodMonth: form.month,
          amount: parsedAmount,
        })
      : null;
  const names = new Map((data?.people ?? []).map((person) => [person.order_id, person.name]));
  const existingMonths = new Set(data?.rows.map((row) => row.period_month) ?? []);
  const selectOptions =
    form.month && !monthOptions.some((option) => option.value === form.month)
      ? [{ value: form.month, label: monthLabelPl(form.month) }, ...monthOptions]
      : monthOptions;
  const ids = {
    month: `${fieldId}-cost-month`,
    amount: `${fieldId}-cost-amount`,
    status: `${fieldId}-cost-status`,
    note: `${fieldId}-cost-note`,
  };

  function startEdit(row: CostConsumptionRow) {
    setEditingMonth(row.period_month);
    setConfirmDeleteMonth(null);
    setForm({
      month: row.period_month,
      amount: String(row.invoice_amount).replace(".", ","),
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
    if (!canSave || parsedAmount === null) return;
    save.mutate({
      month: form.month,
      amount: parsedAmount,
      status: form.status === "" ? null : form.status,
      note: form.note.trim() || null,
    });
  }

  if (query.isError) {
    // Awaria pobrania nie może wyglądać jak „brak wpisów” — pustka czytałaby
    // się jak zero faktur, czyli jak fakt handlowy.
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(query.error, "Nie udało się wczytać rozliczeń tego zamówienia.")}
        onRetry={() => query.refetch()}
      />
    );
  }
  if (!query.isSuccess || !data) {
    return <p className="text-sm text-muted-foreground">Wczytywanie rozliczeń…</p>;
  }

  const shared = data.people.length > 1;
  const pool = data.budget_pool;
  const own = data.people.find((person) => person.order_id === line.id)?.invoiced ?? 0;
  const ownPercent = pool > 0 ? Math.min(100, (Math.min(own, data.budget_used) / pool) * 100) : 0;
  const usedPercent = pool > 0 ? Math.min(100, (data.budget_used / pool) * 100) : 0;
  const total = data.rows.reduce((sum, row) => sum + row.invoice_amount, 0);
  const overflowNames = preview
    ? Array.from(
        new Set(
          preview.overflowRows.map(
            (row) => `${names.get(row.order_id) ?? line.consultant_name} za ${monthLabelPl(row.period_month)}`,
          ),
        ),
      )
    : [];

  return (
    <div className="flex flex-col gap-3">
      {missingMonth && !existingMonths.has(missingMonth) ? (
        <p className="rounded-md bg-warning-muted p-2 text-xs text-warning-muted-foreground">
          Brak zejścia za {monthLabelPl(missingMonth)} — import Finansów za ten miesiąc nie miał faktury tej osoby.
        </p>
      ) : null}

      <div className="flex flex-col gap-2">
        <p className="text-xs text-muted-foreground">
          {shared ? `Wspólny budżet zamówienia · ${data.people.length} osoby` : "Budżet zamówienia"}
        </p>
        <div
          className="flex h-2 overflow-hidden rounded-full bg-muted"
          role="img"
          aria-label={`Wykorzystano ${formatPLN(data.budget_used)} z ${formatPLN(pool)}`}
        >
          <div className="h-2 bg-primary" style={{ width: `${shared ? ownPercent : usedPercent}%` }} />
          {shared ? (
            <div className="h-2 bg-primary/40" style={{ width: `${Math.max(0, usedPercent - ownPercent)}%` }} />
          ) : null}
        </div>
        <dl className="grid grid-cols-3 gap-2 rounded-md border border-border bg-muted/30 p-2 text-sm">
          <div>
            <dt className="text-xs text-muted-foreground">Wykorzystane</dt>
            <dd className="font-semibold tabular-nums text-foreground">{formatPLN(data.budget_used)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Budżet</dt>
            <dd className="font-semibold tabular-nums text-foreground">{formatPLN(pool)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Pozostało</dt>
            <dd className="font-semibold tabular-nums text-foreground">{formatPLN(data.budget_remaining)}</dd>
          </div>
        </dl>
        {shared ? (
          <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-foreground" aria-label="Zafakturowano na osoby">
            {data.people.map((person) => (
              <li key={person.order_id} className="inline-flex items-center gap-1.5">
                <span
                  aria-hidden
                  className={cn(
                    "inline-block h-2 w-2 rounded-sm",
                    person.order_id === line.id ? "bg-primary" : "bg-primary/40",
                  )}
                />
                {person.name}: <span className="tabular-nums">{formatPLN(person.invoiced)}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      {formError ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {formError}
        </p>
      ) : null}

      {data.rows.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground">
          Brak wpisów. Zejścia przychodzą z importu Finansów{canEdit ? "; brakujący miesiąc dodasz niżej." : "."}
        </p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="py-1 pr-2 font-semibold">Miesiąc</th>
                <th className="py-1 pr-2 text-right font-semibold">Kwota</th>
                <th className="py-1 pr-2 text-right font-semibold">Saldo zamówienia</th>
                {canEdit ? <th className="sr-only py-1.5 font-semibold">Akcje</th> : null}
              </tr>
            </thead>
            {data.rows.map((row) => {
              const expanded = expandedMonths.has(row.period_month);
              const monthLabel = formatPeriodMonthPl(row.period_month);
              const detailsId = `${fieldId}-cost-details-${row.period_month}`;
              const confirming = confirmDeleteMonth === row.period_month;
              return (
                <tbody key={row.period_month} className="border-t border-border">
                  <tr className={cn(editingMonth === row.period_month && "bg-primary/5")}>
                    <td className="py-1.5 pr-2 font-medium text-foreground">
                      <button
                        type="button"
                        onClick={() => toggleExpanded(row.period_month)}
                        aria-expanded={expanded}
                        aria-controls={expanded ? detailsId : undefined}
                        title={expanded ? "Ukryj szczegóły" : "Pokaż szczegóły"}
                        className="inline-flex items-center gap-1 whitespace-nowrap rounded-md py-0.5 text-left hover:text-primary pointer-coarse:py-2"
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
                    </td>
                    <td className="py-1.5 pr-2 text-right tabular-nums text-foreground">
                      {formatPLN(row.invoice_amount)}
                      <span className="block text-[11px] text-muted-foreground">
                        {row.source === "manual" ? "ręcznie" : "import"}
                        {row.status ? ` · ${CONSUMPTION_STATUS_LABEL[row.status]}` : ""}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 text-right font-medium tabular-nums text-foreground">
                      {formatPLN(row.balance_after)}
                      {row.unsettled_amount > 0 ? (
                        <span className="block text-[11px] font-normal text-destructive">
                          nierozliczone {formatPLN(row.unsettled_amount)}
                        </span>
                      ) : null}
                    </td>
                    {canEdit ? (
                      <td className="py-1.5 text-right">
                        {confirming ? (
                          <span className="inline-flex flex-wrap items-center justify-end gap-1">
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
                              aria-label={`Edytuj wpis za ${monthLabel}`}
                              title="Edytuj"
                              className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground pointer-coarse:p-2.5"
                            >
                              <Pencil className="h-4 w-4" aria-hidden />
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmDeleteMonth(row.period_month)}
                              aria-label={`Usuń wpis za ${monthLabel}`}
                              title="Usuń"
                              className="rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive pointer-coarse:p-2.5"
                            >
                              <Trash2 className="h-4 w-4" aria-hidden />
                            </button>
                          </span>
                        )}
                      </td>
                    ) : null}
                  </tr>
                  {expanded ? (
                    <tr id={detailsId} className="text-xs">
                      <td colSpan={canEdit ? 4 : 3} className="pb-2 pl-5 pt-0">
                        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                          <dt className="text-muted-foreground">Źródło</dt>
                          <dd className="text-foreground">{row.source === "manual" ? "ręcznie" : "import Finansów"}</dd>
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
                </tbody>
              );
            })}
            <tfoot>
              <tr className="border-t border-border text-xs text-muted-foreground">
                <td className="py-1.5 pr-2 font-semibold">Razem</td>
                <td className="py-1.5 pr-2 text-right font-semibold tabular-nums text-foreground">
                  {formatPLN(total)}
                </td>
                <td colSpan={canEdit ? 2 : 1} />
              </tr>
            </tfoot>
          </table>
          {shared ? (
            <p className="mt-1 text-xs text-muted-foreground">
              Saldo zamówienia liczy wpisy wszystkich osób, w kolejności miesięcy.
            </p>
          ) : null}
        </div>
      )}

      {canEdit ? (
        <fieldset className="rounded-md border border-border p-3">
          <legend className="px-1 text-xs font-semibold text-muted-foreground">
            {editingMonth ? `Edycja wpisu za ${formatPeriodMonthPl(editingMonth)}` : "Nowy wpis miesięczny"}
          </legend>
          <div className="grid grid-cols-1 gap-3">
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
                    {editingMonth === null && existingMonths.has(option.value)
                      ? " — ma wpis (nadpisze)"
                      : option.value === missingMonth
                        ? " — brak zejścia"
                        : ""}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor={ids.amount} className={labelClass}>
                Kwota (zł) *
              </label>
              <input
                id={ids.amount}
                inputMode="decimal"
                value={form.amount}
                onChange={(event) => setForm((prev) => ({ ...prev, amount: sanitizeDecimalInput(event.target.value) }))}
                className={cn(inputClass, preview && preview.overBy > 0 && "border-warning")}
                placeholder="1540,00"
              />
            </div>
            <div>
              <label htmlFor={ids.status} className={labelClass}>
                Status
              </label>
              <select
                id={ids.status}
                value={form.status}
                onChange={(event) => setForm((prev) => ({ ...prev, status: event.target.value as FormState["status"] }))}
                className={inputClass}
              >
                <option value="">—</option>
                <option value="protocol">{CONSUMPTION_STATUS_LABEL.protocol}</option>
                <option value="accepted">{CONSUMPTION_STATUS_LABEL.accepted}</option>
              </select>
            </div>
            <div>
              <label htmlFor={ids.note} className={labelClass}>
                Notatka
              </label>
              <input
                id={ids.note}
                value={form.note}
                maxLength={255}
                onChange={(event) => setForm((prev) => ({ ...prev, note: event.target.value }))}
                className={inputClass}
              />
            </div>
          </div>

          {preview && preview.overBy > 0 ? (
            <div
              role="status"
              className="mt-3 flex gap-2 rounded-md border border-warning/50 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <div>
                <p className="text-sm font-semibold">Przekroczenie budżetu o {formatPLN(preview.overBy)}</p>
                <p>
                  Wpis da się zapisać. Zamówienie przejdzie w „Wyczerpane”, a nadwyżka zostanie jako nierozliczona
                  {overflowNames.length > 0 ? ` (${overflowNames.join(", ")})` : ""}. Delivery Lead dostanie alert.
                </p>
              </div>
            </div>
          ) : preview ? (
            <p className="mt-3 rounded-md bg-muted/50 px-3 py-2 text-xs text-foreground">
              Po zapisie na zamówieniu zostanie {formatPLN(preview.remainingAfter)}.
            </p>
          ) : null}

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={submit}
              disabled={!canSave}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50",
                preview && preview.overBy > 0
                  ? "border border-warning bg-warning-muted text-warning-muted-foreground hover:bg-warning-muted/80"
                  : "bg-primary text-primary-foreground hover:bg-primary/90",
              )}
            >
              {save.isPending
                ? "Zapisywanie…"
                : preview && preview.overBy > 0
                  ? "Zapisz mimo przekroczenia"
                  : editingMonth
                    ? "Zapisz zmiany"
                    : "Dodaj wpis"}
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
