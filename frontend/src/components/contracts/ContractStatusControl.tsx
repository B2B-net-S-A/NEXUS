"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { contractsApi, extractErrorMsg } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CONTRACT_STATUS_LABELS, contractStatusLabel } from "@/lib/status-labels";

/**
 * Statusy, które da się WYBRAĆ w rejestrze. „Do podpisu” i „Anulowany” mają
 * własne ścieżki (podpis, „Anuluj kontrakt”) — tylko je wyświetlamy.
 */
export const SELECTABLE_CONTRACT_STATUSES = ["draft", "active", "ending", "ended"] as const;

export const RECOVERY_HINT_ALLOWED =
  "Zakończony kontrakt przywracasz jedną z dwóch akcji poniżej: „Cofnij zakończenie” (pomyłka) albo „Powrót po przerwie” (nowy kontrakt).";
export const RECOVERY_HINT_FORBIDDEN =
  "Zakończony kontrakt przywraca Admin, Finanse albo Talent Community Manager: „Cofnij zakończenie” (pomyłka) albo „Powrót po przerwie”.";

export interface ContractStatusControlProps {
  contractId: number;
  status: string;
  canRecoverTermination: boolean;
  /** „Zakończony” wyłącznie przez okno „Zakończ współpracę” (kontrakt #674). */
  onRequestTermination: () => void;
  /** Podpowiedź przy próbie wyjścia z „Zakończony” (pusty tekst = schowaj). */
  onRecoveryHint: (hint: string) => void;
  onError: (message: string) => void;
  className?: string;
}

/**
 * Lista „Zmień status kontraktu” — ta sama na karcie kontraktu i w bocznym
 * panelu rejestru. Wybór „Zakończony” otwiera okno zakończenia współpracy,
 * a zakończonego kontraktu nie przywraca zwykła zmiana statusu (nie
 * przywróciłaby zamówień — zgłoszenie 09.2026). Lista jest kontrolowana
 * wartością z serwera, więc „Anuluj” w oknie zostawia poprzedni status.
 */
export function ContractStatusControl({
  contractId,
  status,
  canRecoverTermination,
  onRequestTermination,
  onRecoveryHint,
  onError,
  className,
}: ContractStatusControlProps) {
  const queryClient = useQueryClient();
  const statusMutation = useMutation({
    mutationFn: (next: string) => contractsApi.updateStatus(contractId, next),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contract", contractId] });
      queryClient.invalidateQueries({ queryKey: ["contracts"] });
      queryClient.invalidateQueries({ queryKey: ["contracts-v2"] });
      queryClient.invalidateQueries({ queryKey: ["contracts-expiring-v2"] });
      queryClient.invalidateQueries({ queryKey: ["contractors-v2"] });
      queryClient.invalidateQueries({ queryKey: ["contract-activities", contractId] });
      onError("");
    },
    onError: (err: unknown) => onError(extractErrorMsg(err)),
  });

  return (
    <select
      aria-label="Zmień status kontraktu"
      value={status}
      disabled={statusMutation.isPending}
      onChange={(event) => {
        const next = event.target.value;
        if (next === "ended") {
          onRecoveryHint("");
          onRequestTermination();
          return;
        }
        // „Zakończony → Aktywny” przestało być jedną akcją: pomyłka i powrót
        // po przerwie to dwie różne operacje.
        if (status === "ended") {
          onRecoveryHint(
            canRecoverTermination ? RECOVERY_HINT_ALLOWED : RECOVERY_HINT_FORBIDDEN,
          );
          return;
        }
        onRecoveryHint("");
        statusMutation.mutate(next);
      }}
      className={cn(
        "rounded-md border border-border bg-card px-2 py-1 text-sm font-medium",
        className,
      )}
    >
      {SELECTABLE_CONTRACT_STATUSES.map((value) => (
        <option key={value} value={value}>
          {CONTRACT_STATUS_LABELS[value]}
        </option>
      ))}
      {/* „Do podpisu” / „Anulowany” — wyświetlane, nie do wyboru. */}
      {!(SELECTABLE_CONTRACT_STATUSES as readonly string[]).includes(status) && (
        <option value={status} disabled>
          {contractStatusLabel(status)}
        </option>
      )}
    </select>
  );
}
