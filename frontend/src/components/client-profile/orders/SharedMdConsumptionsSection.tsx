"use client";

// Zejścia wspólnej puli MD — miesiąc po miesiącu, z podziałem na konsultantów.
//
// Ticket 10.2026: miesiąc wspólnej puli dało się tylko dopisać (jedna suma
// w „Uzupełnij zamówienie”). Nie dało się go poprawić ani usunąć, a usunięcie
// zamówienia blokowały właśnie te rozliczenia. Ta sekcja stoi w panelu
// zamówienia i w oknie „Uzupełnij zamówienie”: edycja MD per konsultant,
// usunięcie miesiąca, a pulę przelicza serwer od zera.

import { useEffect, useId, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
import { apiErrorMessage } from "@/lib/api-error";
import {
  orderGroupsApi,
  type OrderGroupRead,
  type SharedMdConsumptionMonth,
} from "@/lib/api/orderGroups";
import { consumptionMonthOptions } from "@/lib/order-consumption";
import { cn, parseDecimalInput, sanitizeDecimalInput } from "@/lib/utils";

import { formatPeriodMonthPl } from "./LineConsumptionTable";
import { formatMd } from "./MdBudgetBar";

export function sharedMdConsumptionsQueryKey(clientId: number, groupId: number) {
  return ["order-group-md-consumptions", clientId, groupId] as const;
}

interface EditorState {
  /** `null` = nowy miesiąc (wybór z listy), inaczej edytowany miesiąc. */
  editing: string | null;
  month: string;
  /** MD per linia zamówienia (klucz = `order_id`), tekst pola. */
  values: Record<number, string>;
  /** Suma bez podziału na osoby, którą edycja zastąpi. */
  undividedTotal: number | null;
}

interface Props {
  clientId: number;
  group: Pick<OrderGroupRead, "id" | "start_date" | "end_date" | "status">;
  canEdit: boolean;
  enabled?: boolean;
}

const SOURCE_LABEL: Record<SharedMdConsumptionMonth["source"], string> = {
  import: "import",
  manual: "ręcznie",
};

export function SharedMdConsumptionsSection({
  clientId,
  group,
  canEdit,
  enabled = true,
}: Props) {
  const queryClient = useQueryClient();
  const fieldId = useId();
  const queryKey = sharedMdConsumptionsQueryKey(clientId, group.id);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEditor(null);
    setConfirmDelete(null);
    setError(null);
  }, [group.id, enabled]);

  const query = useQuery({
    queryKey,
    queryFn: async () =>
      (await orderGroupsApi.listSharedMdConsumptions(clientId, group.id)).data,
    enabled,
  });

  // Pula liczy się na zamówieniu (pasek, status „wyczerpane”), a każdy zapis
  // dopisuje wpis do historii — odświeżamy wszystkie trzy, nie tylko tę listę.
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey });
    queryClient.invalidateQueries({ queryKey: ["client-order-groups", clientId] });
    queryClient.invalidateQueries({ queryKey: ["order-group-events", clientId] });
  };

  const save = useMutation({
    mutationFn: (values: { month: string; lines: { order_id: number; md: number }[] }) =>
      orderGroupsApi.putSharedMdConsumption(clientId, group.id, values.month, {
        lines: values.lines,
      }),
    onSuccess: () => {
      setEditor(null);
      setError(null);
      invalidate();
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać zejścia MD.")),
  });

  const remove = useMutation({
    mutationFn: (month: string) =>
      orderGroupsApi.deleteSharedMdConsumption(clientId, group.id, month),
    onSuccess: () => {
      setConfirmDelete(null);
      setError(null);
      invalidate();
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się usunąć zejścia MD.")),
  });

  const data = query.data;
  const months = useMemo(() => data?.months ?? [], [data?.months]);

  // Wiersze formularza: wszyscy konsultanci zamówienia + osoby z podziału,
  // których już na liście nie ma (np. linia anulowana po zapisie miesiąca).
  const editorPeople = useMemo(() => {
    const people = new Map<number, string>();
    for (const c of data?.consultants ?? []) people.set(c.order_id, c.consultant_name);
    if (editor?.editing) {
      const month = months.find((m) => m.period_month === editor.editing);
      for (const p of month?.breakdown ?? []) {
        if (!people.has(p.order_id)) people.set(p.order_id, p.consultant_name);
      }
    }
    return [...people.entries()].map(([orderId, name]) => ({ orderId, name }));
  }, [data?.consultants, editor?.editing, months]);

  // Miesiące okresu zamówienia bez zapisanego zejścia — zapisany edytuje się
  // przyciskiem przy nim, a nie drugim wpisem tego samego miesiąca.
  const monthOptions = useMemo(() => {
    const existing = new Set(months.map((m) => m.period_month));
    return consumptionMonthOptions(group.start_date, group.end_date, new Date()).filter(
      (option) => !existing.has(option.value),
    );
  }, [group.start_date, group.end_date, months]);

  function startAdd() {
    setConfirmDelete(null);
    setError(null);
    setEditor({
      editing: null,
      month: monthOptions[0]?.value ?? "",
      values: {},
      undividedTotal: null,
    });
  }

  function startEdit(month: SharedMdConsumptionMonth) {
    setConfirmDelete(null);
    setError(null);
    const values: Record<number, string> = {};
    for (const p of month.breakdown ?? []) values[p.order_id] = String(p.md);
    setEditor({
      editing: month.period_month,
      month: month.period_month,
      values,
      undividedTotal: month.breakdown ? null : month.md_reported,
    });
  }

  const entered = editor
    ? editorPeople
        .map(({ orderId }) => ({
          order_id: orderId,
          md: parseDecimalInput(editor.values[orderId] ?? ""),
        }))
        .filter((line): line is { order_id: number; md: number } => line.md !== null)
    : [];
  const invalidValue = entered.some((line) => line.md < 0);
  const enteredTotal = entered.reduce((sum, line) => sum + line.md, 0);
  const canSave =
    editor !== null &&
    !save.isPending &&
    /^\d{4}-\d{2}$/.test(editor.month) &&
    entered.length > 0 &&
    !invalidValue;

  function submit() {
    if (!editor || !canSave) return;
    save.mutate({ month: editor.month, lines: entered });
  }

  const draft = group.status === "draft";

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>
          Każdy miesiąc pomniejsza pulę. Edycja i usunięcie przeliczają
          wykorzystanie i pozostały budżet.
        </span>
        {canEdit && !draft && editor === null ? (
          <button
            type="button"
            onClick={startAdd}
            disabled={!query.isSuccess}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 font-medium text-foreground hover:bg-muted disabled:opacity-50"
          >
            <Plus className="h-3.5 w-3.5" aria-hidden /> Dodaj miesiąc
          </button>
        ) : null}
      </div>

      {error ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {query.isError ? (
        // Awaria nie może wyglądać jak „brak zejść” — to czytałoby się jak
        // nietknięta pula.
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać zejść wspólnej puli MD."
          onRetry={() => query.refetch()}
        />
      ) : !query.isSuccess ? (
        <p className="text-sm text-muted-foreground">Wczytywanie zejść…</p>
      ) : months.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-3 py-4 text-center text-sm text-muted-foreground">
          Brak zejść MD na tym zamówieniu.
        </p>
      ) : (
        <ul className="divide-y divide-border/60 rounded-md border border-border text-sm">
          {months.map((month) => {
            const label = formatPeriodMonthPl(month.period_month);
            const confirming = confirmDelete === month.period_month;
            return (
              <li
                key={month.period_month}
                className={cn(
                  "flex flex-wrap items-start gap-x-3 gap-y-1 px-2.5 py-2",
                  editor?.editing === month.period_month && "bg-primary/5",
                )}
              >
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-foreground">
                    {label} ·{" "}
                    <span className="tabular-nums">{formatMd(month.md_reported)} MD</span>
                    <span className="ml-1 text-xs font-normal text-muted-foreground">
                      ({SOURCE_LABEL[month.source]}
                      {month.created_by_name ? `, ${month.created_by_name}` : ""})
                    </span>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {month.breakdown && month.breakdown.length > 0
                      ? month.breakdown
                          .map((p) => `${p.consultant_name}: ${formatMd(p.md)} MD`)
                          .join(" · ")
                      : "bez podziału na osoby"}
                  </p>
                </div>
                {canEdit ? (
                  confirming ? (
                    <span className="inline-flex flex-wrap items-center justify-end gap-1">
                      <button
                        type="button"
                        disabled={remove.isPending}
                        onClick={() => remove.mutate(month.period_month)}
                        className="rounded-md bg-destructive px-2 py-1 text-xs font-semibold text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
                      >
                        Potwierdź usunięcie
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDelete(null)}
                        className="rounded-md border border-border px-2 py-1 text-xs font-medium text-foreground hover:bg-muted"
                      >
                        Anuluj
                      </button>
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => startEdit(month)}
                        aria-label={`Edytuj zejście za ${label}`}
                        title="Edytuj"
                        className="rounded-md p-1.5 pointer-coarse:p-2.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        <Pencil className="h-4 w-4" aria-hidden />
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setEditor(null);
                          setConfirmDelete(month.period_month);
                        }}
                        aria-label={`Usuń zejście za ${label}`}
                        title="Usuń"
                        className="rounded-md p-1.5 pointer-coarse:p-2.5 text-muted-foreground hover:bg-muted hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" aria-hidden />
                      </button>
                    </span>
                  )
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      {editor !== null ? (
        <fieldset className="space-y-2 rounded-md border border-border p-3">
          <legend className="px-1 text-sm font-medium text-foreground">
            {editor.editing
              ? `Zejście za ${formatPeriodMonthPl(editor.editing)}`
              : "Nowe zejście MD"}
          </legend>
          {editor.editing === null ? (
            <label className="block text-xs font-medium text-foreground" htmlFor={`${fieldId}-month`}>
              Miesiąc
              <select
                id={`${fieldId}-month`}
                value={editor.month}
                onChange={(event) => setEditor({ ...editor, month: event.target.value })}
                className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
              >
                {monthOptions.length === 0 ? <option value="">Brak wolnych miesięcy</option> : null}
                {monthOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {editor.undividedTotal !== null ? (
            <p role="status" className="rounded-md bg-muted/50 px-2.5 py-2 text-xs text-muted-foreground">
              Ten miesiąc zapisano jako sumę {formatMd(editor.undividedTotal)} MD bez
              podziału na osoby. Wpisz MD każdej osoby — zapis zastąpi sumę.
            </p>
          ) : null}
          {editorPeople.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              Zamówienie nie ma konsultantów — dodaj ich, zanim wpiszesz zejście.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {editorPeople.map(({ orderId, name }) => (
                <li key={orderId} className="flex items-center gap-2">
                  <label
                    htmlFor={`${fieldId}-md-${orderId}`}
                    className="min-w-0 flex-1 truncate text-sm text-foreground"
                  >
                    {name}
                  </label>
                  <input
                    id={`${fieldId}-md-${orderId}`}
                    inputMode="decimal"
                    placeholder="—"
                    value={editor.values[orderId] ?? ""}
                    onChange={(event) =>
                      setEditor({
                        ...editor,
                        values: {
                          ...editor.values,
                          [orderId]: sanitizeDecimalInput(event.target.value),
                        },
                      })
                    }
                    className="w-24 rounded-md border border-border bg-background px-2 py-1 text-right text-sm tabular-nums"
                  />
                  <span className="text-xs text-muted-foreground">MD</span>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-muted-foreground">
            Razem: <span className="font-medium tabular-nums text-foreground">{formatMd(enteredTotal)} MD</span>
            {" "}— osoby bez wpisu nie wchodzą do miesiąca.
          </p>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                setEditor(null);
                setError(null);
              }}
              className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted"
            >
              Anuluj
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={!canSave}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              {save.isPending ? "Zapisywanie…" : "Zapisz zejście"}
            </button>
          </div>
        </fieldset>
      ) : null}
    </div>
  );
}
