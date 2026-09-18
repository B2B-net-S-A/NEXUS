"use client";

import { useEffect, useState } from "react";
import {
  CONTRACT_TERMINATION_REASONS,
  type ContractTerminationReason,
} from "@/lib/api";
import { AppModal } from "@/components/ds/AppModal";

interface Props {
  open: boolean;
  /** Ile umów obejmie dyspozycja — liczba jedzie w treść okna i w przycisk. */
  count: number;
  busy?: boolean;
  error?: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: (reason: ContractTerminationReason, endDate: string) => void;
}

/**
 * „Oznacz zakończone" dla zaznaczenia w rejestrze umów.
 *
 * Do 09.2026 stało tu generyczne `ConfirmV2`: jedno pytanie „na pewno?" i
 * natychmiastowy `status = ended` bez powodu i bez daty. Akcja znaczy jednak
 * faktyczny koniec projektu — to samo, co okno „Zakończ współpracę" na
 * pojedynczej umowie — więc pyta o ten sam komplet i zapisuje go na każdej
 * zaznaczonej umowie. Powłoka to `AppModal` (Radix: `role="dialog"`, focus
 * trap, Escape), bo `ConfirmV2` nie przyjmuje pól formularza.
 *
 * Oba pola startują PUSTE i przycisk jest do tego czasu nieaktywny. Domyślny
 * powód („Koniec projektu", jak w oknie pojedynczym) oznaczyłby N umów
 * wartością, której nikt nie wybrał, a domyślna data „dzisiaj" wpisałaby całej
 * grupie datę kliknięcia zamiast daty końca projektu.
 */
export function ContractsBulkEndDialog({
  open,
  count,
  busy,
  error,
  onOpenChange,
  onConfirm,
}: Props) {
  const [reason, setReason] = useState<ContractTerminationReason | "">("");
  const [endDate, setEndDate] = useState("");

  // Zamknięcie okna czyści formularz: następne otwarcie dotyczy innego
  // zaznaczenia, a podpowiedziany powód z poprzedniej dyspozycji byłby tu
  // dokładnie tym domyślnym, którego to okno unika.
  useEffect(() => {
    if (!open) {
      setReason("");
      setEndDate("");
    }
  }, [open]);

  const ready = reason !== "" && endDate !== "";
  const formId = "contracts-bulk-end";

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Zakończ współpracę"
      description={`Powód i data zostaną zapisane na ${count} zaznaczonych ${
        count === 1 ? "kontrakcie" : "kontraktach"
      } — tak samo jak przy zakończeniu pojedynczej współpracy.`}
      footer={
        <>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={busy}
            className="text-sm text-muted-foreground hover:underline disabled:opacity-50"
          >
            Anuluj
          </button>
          <button
            type="submit"
            form={formId}
            disabled={!ready || busy}
            className="text-sm bg-red-600 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-md px-4 py-2"
          >
            {busy ? "Zapisywanie…" : "Zakończ"}
          </button>
        </>
      }
    >
      <form
        id={formId}
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (!ready) return;
          onConfirm(reason as ContractTerminationReason, endDate);
        }}
      >
        <label className="block">
          <span className="text-xs text-muted-foreground">
            Powód zakończenia *
          </span>
          <select
            value={reason}
            required
            onChange={(e) =>
              setReason(e.target.value as ContractTerminationReason | "")
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-3 py-2 text-sm bg-card dark:bg-gray-950"
          >
            <option value="">— wybierz powód —</option>
            {CONTRACT_TERMINATION_REASONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">
            Data zakończenia projektu *
          </span>
          <input
            type="date"
            value={endDate}
            required
            onChange={(e) => setEndDate(e.target.value)}
            className="mt-1 w-full border border-border dark:border-border rounded-md px-3 py-2 text-sm bg-card dark:bg-gray-950"
          />
        </label>
        {error && (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}
      </form>
    </AppModal>
  );
}
