"use client";

import { useEffect, useState } from "react";

import { AppModal } from "@/components/ds";
import type { OrderGroupInput, OrderGroupRead } from "@/lib/api/orderGroups";

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass = "mb-1 block text-xs font-semibold text-muted-foreground";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Ustawione = edycja; puste = nowe zamówienie. */
  group: OrderGroupRead | null;
  submitting: boolean;
  error: string | null;
  onSubmit: (values: OrderGroupInput) => void;
}

export function OrderGroupFormModal({
  open,
  onOpenChange,
  group,
  submitting,
  error,
  onSubmit,
}: Props) {
  const editing = Boolean(group);
  const [orderNumber, setOrderNumber] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    if (!open) return;
    setOrderNumber(group?.order_number ?? "");
    setStartDate(group?.start_date ?? "");
    setEndDate(group?.end_date ?? "");
    setNotes(group?.notes ?? "");
  }, [open, group]);

  const canSubmit = !submitting && orderNumber.trim() !== "" && startDate !== "";

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={editing ? "Edytuj zamówienie" : "Nowe zamówienie"}
      description={
        editing
          ? "Numer i okres obowiązywania. Linie konsultantów edytujesz osobno."
          : "Po zapisaniu dodasz do zamówienia konsultantów."
      }
      footer={
        <>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground hover:bg-muted"
          >
            Anuluj
          </button>
          <button
            type="button"
            disabled={!canSubmit}
            onClick={() =>
              onSubmit({
                order_number: orderNumber.trim(),
                start_date: startDate,
                end_date: endDate || null,
                notes: notes.trim() || null,
              })
            }
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {submitting ? "Zapisywanie…" : editing ? "Zapisz" : "Utwórz zamówienie"}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {error ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <div>
          <label htmlFor="group-number" className={labelClass}>
            Numer zamówienia *
          </label>
          <input
            id="group-number"
            value={orderNumber}
            onChange={(e) => setOrderNumber(e.target.value)}
            className={inputClass}
            placeholder="445"
          />
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="group-start" className={labelClass}>
              Obowiązuje od *
            </label>
            <input
              id="group-start"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="group-end" className={labelClass}>
              Obowiązuje do (puste = bezterminowo)
            </label>
            <input
              id="group-end"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className={inputClass}
            />
          </div>
        </div>

        <div>
          <label htmlFor="group-notes" className={labelClass}>
            Notatki
          </label>
          <textarea
            id="group-notes"
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className={inputClass}
          />
        </div>
      </div>
    </AppModal>
  );
}
