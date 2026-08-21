"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CONTRACT_TERMINATION_REASONS,
  contractsApi,
  type ContractTerminationReason,
} from "@/lib/api";
import { AppModal } from "@/components/ds/AppModal";

interface Props {
  contractId: number;
  defaultDate?: string;
  onClose: () => void;
  onSuccess: () => void;
}

/**
 * „Zakończ współpracę" — rejestracja zakończenia kontraktu.
 *
 * Powłoka to `AppModal` (Radix), NIE surowy `fixed inset-0` backdrop, którym
 * ten dialog był do 2026-08. Tamten kształt nie miał `role="dialog"`, focus
 * trapu ani obsługi Escape, a jedynym wyjściem był mały „X": użytkownik
 * klawiatury wychodził Tabem POZA dialog na listę kontraktów pod spodem —
 * wizualnie zasłoniętą, ale wciąż klikalną — i mógł Enterem odpalić akcję
 * na stronie za otwartym modalem. Operacja jest destrukcyjna (zdejmuje
 * konsultanta z aktywnych i ucina stawkę w MRR), więc anulowanie odruchem
 * (Escape) musi działać.
 */
export function ContractTerminationDialog({
  contractId,
  defaultDate,
  onClose,
  onSuccess,
}: Props) {
  const qc = useQueryClient();
  const [reason, setReason] = useState<ContractTerminationReason>("project_ended");
  const [lessons, setLessons] = useState("");
  const [when, setWhen] = useState(
    defaultDate || new Date().toISOString().slice(0, 10),
  );

  const mut = useMutation({
    mutationFn: () =>
      contractsApi.terminate(contractId, {
        termination_reason: reason,
        termination_lessons: lessons || null,
        terminated_at: when || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["contract", contractId] });
      // `["contracts"]` było osierocone po skasowaniu list V1 — żadna kwerenda
      // nie stała pod tym kluczem, więc inwalidacja nie trafiała w nic.
      // Rejestr (`staleTime` 30 s) pokazywał zakończony kontrakt jako aktywny,
      // a panel „Kończące się" (`staleTime` 5 min) trzymał go w oknie 30 dni,
      // więc Delivery Lead gonił odnowienie właśnie zamkniętej współpracy.
      qc.invalidateQueries({ queryKey: ["contracts-v2"] });
      qc.invalidateQueries({ queryKey: ["contracts-expiring-v2"] });
      qc.invalidateQueries({ queryKey: ["contractors-v2"] });
      qc.invalidateQueries({ queryKey: ["contractors-stats-v2"] });
      // Zakończenie zasila też profil klienta (kafle MRR, zakładka
      // Konsultanci). Bez `clientId` w propsach unieważniamy prefiksem —
      // zamontowany profil jest najwyżej jeden, więc koszt jest zerowy.
      qc.invalidateQueries({ queryKey: ["client-profile"] });
      onSuccess();
    },
  });

  const formId = `contract-termination-${contractId}`;

  return (
    <AppModal
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Zakończ współpracę"
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-muted-foreground hover:underline"
          >
            Anuluj
          </button>
          <button
            type="submit"
            form={formId}
            disabled={mut.isPending}
            className="text-sm bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white rounded-md px-4 py-2"
          >
            {mut.isPending ? "Zapisywanie…" : "Zakończ"}
          </button>
        </>
      }
    >
      <form
        id={formId}
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          mut.mutate();
        }}
      >
        <label className="block">
          <span className="text-xs text-muted-foreground">Powód zakończenia</span>
          <select
            value={reason}
            onChange={(e) =>
              setReason(e.target.value as ContractTerminationReason)
            }
            className="mt-1 w-full border border-border dark:border-border rounded-md px-3 py-2 text-sm bg-card dark:bg-gray-950"
          >
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
          {/* required (ticket #5): wyczyszczone pole przechodziło, a backend
              po cichu podstawiał dzisiaj. */}
          <input
            type="date"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
            required
            className="mt-1 w-full border border-border dark:border-border rounded-md px-3 py-2 text-sm bg-card dark:bg-gray-950"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">
            Wnioski / co zrobiliśmy źle albo dobrze (TAC only)
          </span>
          <textarea
            value={lessons}
            onChange={(e) => setLessons(e.target.value)}
            className="mt-1 w-full border border-border dark:border-border rounded-md px-3 py-2 text-sm bg-card dark:bg-gray-950"
            rows={4}
            placeholder="Np.: klient poprosił o konsultanta na 6 mies., potrzebowali 12 — zbadać wcześniej…"
          />
        </label>
        {mut.isError && (
          <p className="text-xs text-destructive">
            Błąd zapisu. Spróbuj ponownie.
          </p>
        )}
      </form>
    </AppModal>
  );
}
