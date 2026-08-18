"use client";

import { AlertTriangle } from "lucide-react";

import { AppModal } from "@/components/ds";
import type { ExtractionConflict } from "@/lib/order-extraction";

interface Props {
  open: boolean;
  conflicts: ExtractionConflict[];
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * „Odczytane dane różnią się od wpisanych ręcznie. Zapisać dane z dokumentu?"
 *
 * Dialog wymienia rozbieżności POLE PO POLU, a nie zadaje ogólnego pytania:
 * „Tak/Nie" bez pokazania, co dokładnie się zmieni, zmusza do zgadywania,
 * której wartości użytkownik właśnie się pozbywa.
 *
 * Wyłącznie widok wielo-konsultantowy — formularze jednoosobowe nadpisują bez
 * pytania (patrz `lib/order-extraction.ts`).
 */
export function ExtractionConflictDialog({
  open,
  conflicts,
  onConfirm,
  onCancel,
}: Props) {
  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
      title="Odczytane dane różnią się od wpisanych"
      description="Wybierz, które wartości mają zostać w formularzu."
      size="md"
      footer={
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-border px-3 py-2 text-sm font-medium"
          >
            Nie — zostaw wpisane ręcznie
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
          >
            Tak — zapisz dane z dokumentu
          </button>
        </div>
      }
    >
      <div className="flex items-start gap-2 rounded-md border border-orange-300 bg-orange-50 p-3 text-sm text-orange-900">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <p>
          Dokument podaje inne wartości niż te, które są w formularzu. Nic nie
          zostało jeszcze zmienione.
        </p>
      </div>

      <ul className="mt-3 flex flex-col divide-y divide-border">
        {conflicts.map((conflict) => (
          <li key={conflict.key} className="py-2 text-sm">
            <p className="font-medium text-foreground">{conflict.label}</p>
            <p className="text-muted-foreground">
              wpisano: <span className="text-foreground">{conflict.current}</span>
              {" · "}w dokumencie:{" "}
              <span className="text-foreground">{conflict.incoming}</span>
            </p>
          </li>
        ))}
      </ul>
    </AppModal>
  );
}
