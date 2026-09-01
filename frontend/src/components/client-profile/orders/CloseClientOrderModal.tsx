"use client";

import { useEffect, useState } from "react";

import { AppModal } from "@/components/ds";
import type { ClientOrderRead } from "@/lib/api/dlPortal";

const inputClass =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring";
const labelClass = "mb-1 block text-xs font-semibold text-muted-foreground";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  order: ClientOrderRead | null;
  consultantName: string;
  submitting: boolean;
  error: string | null;
  onSubmit: (values: { closure_date: string; closure_reason: string | null }) => void;
}

/**
 * „Zakończ zamówienie" — zamyka JEDNO zamówienie okresowe.
 *
 * Świadomie osobna akcja od „Zakończ współpracę": tamta wypowiada UMOWĘ, a
 * umowa niesie także zamówienia rozliczane w MD tej samej osoby. Zakończenie
 * zamówienia okresowego nie może ich dotykać — to jest cały sens rozdzielenia.
 */
export function CloseClientOrderModal({
  open,
  onOpenChange,
  order,
  consultantName,
  submitting,
  error,
  onSubmit,
}: Props) {
  const [closureDate, setClosureDate] = useState("");
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (!open) return;
    setClosureDate(order?.end_date ?? "");
    setReason("");
  }, [open, order]);

  const canSubmit = !submitting && closureDate !== "";

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Zakończ zamówienie"
      description={
        order
          ? `Zamówienie „${order.title}" (${consultantName}) zostanie domknięte. ` +
            "Umowa i pozostałe zamówienia tej osoby zostają bez zmian."
          : undefined
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
                closure_date: closureDate,
                closure_reason: reason.trim() || null,
              })
            }
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {submitting ? "Zapisywanie…" : "Zakończ zamówienie"}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {error ? (
          <p
            role="alert"
            className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
          >
            {error}
          </p>
        ) : null}

        <div>
          <label htmlFor="close-order-date" className={labelClass}>
            Data zakończenia zamówienia *
          </label>
          <input
            id="close-order-date"
            type="date"
            value={closureDate}
            onChange={(e) => setClosureDate(e.target.value)}
            className={inputClass}
          />
          <p className="mt-1 text-xs text-muted-foreground">
            Data w przyszłości nie wyłącza zamówienia od razu — obowiązuje do
            jej nadejścia.
          </p>
        </div>

        <div>
          <label htmlFor="close-order-reason" className={labelClass}>
            Powód (opcjonalnie)
          </label>
          <textarea
            id="close-order-reason"
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className={inputClass}
          />
          <p className="mt-1 text-xs text-muted-foreground">
            Powód trafia do historii zmian, nie do dokumentu zamówienia.
          </p>
        </div>
      </div>
    </AppModal>
  );
}
