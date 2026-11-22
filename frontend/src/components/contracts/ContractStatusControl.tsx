"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { contractsApi, extractErrorMsg } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  CONTRACT_STATUS_LABELS,
  contractStatusLabel,
  contractStatusVariant,
  type StatusVariant,
} from "@/lib/status-labels";

/**
 * Statusy, które da się WYBRAĆ w rejestrze. „Do podpisu” i „Anulowany” mają
 * własne ścieżki (podpis, „Anuluj kontrakt”) — tylko je wyświetlamy.
 */
export const SELECTABLE_CONTRACT_STATUSES = ["draft", "active", "ending", "ended"] as const;

export const RECOVERY_HINT_ALLOWED =
  "Zakończony kontrakt przywracasz jedną z dwóch akcji poniżej: „Cofnij zakończenie” (pomyłka) albo „Powrót po przerwie” (nowy kontrakt).";
export const RECOVERY_HINT_FORBIDDEN =
  "Zakończony kontrakt przywraca Admin, Finanse albo Talent Community Manager: „Cofnij zakończenie” (pomyłka) albo „Powrót po przerwie”.";

const DOT: Record<StatusVariant, string> = {
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-destructive",
  soft: "bg-info",
  neutral: "bg-muted-foreground/50",
};

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
 * Status kontraktu jako kropka z etykietą i menu (przebudowa strony kontraktu
 * 19.11.2026; dawniej natywna lista) — ta sama na karcie kontraktu i w bocznym
 * panelu rejestru. Wybór „Zakończony” otwiera okno zakończenia współpracy,
 * a zakończonego kontraktu nie przywraca zwykła zmiana statusu (nie
 * przywróciłaby zamówień — zgłoszenie 09.2026). Menu pokazuje wartość
 * z serwera, więc „Anuluj” w oknie zostawia poprzedni status.
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
      queryClient.invalidateQueries({ queryKey: ["client-register"] });
      queryClient.invalidateQueries({ queryKey: ["contracts-quick-counts"] });
      queryClient.invalidateQueries({ queryKey: ["contract-activities", contractId] });
      onError("");
    },
    onError: (err: unknown) => onError(extractErrorMsg(err)),
  });

  const choose = (next: string) => {
    if (next === status) return;
    if (next === "ended") {
      onRecoveryHint("");
      onRequestTermination();
      return;
    }
    // „Zakończony → Aktywny” przestało być jedną akcją: pomyłka i powrót
    // po przerwie to dwie różne operacje.
    if (status === "ended") {
      onRecoveryHint(canRecoverTermination ? RECOVERY_HINT_ALLOWED : RECOVERY_HINT_FORBIDDEN);
      return;
    }
    onRecoveryHint("");
    statusMutation.mutate(next);
  };

  const selectable = (SELECTABLE_CONTRACT_STATUSES as readonly string[]).includes(status);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={`Zmień status kontraktu (teraz: ${contractStatusLabel(status)})`}
          disabled={statusMutation.isPending}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-0.5 text-xs font-medium text-foreground hover:bg-muted disabled:opacity-60",
            className,
          )}
        >
          <span aria-hidden className={cn("size-1.5 rounded-full", DOT[contractStatusVariant(status)])} />
          {contractStatusLabel(status)}
          <ChevronDown className="size-3 text-muted-foreground" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel className="text-xs text-muted-foreground">Zmień status</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={status} onValueChange={choose}>
          {SELECTABLE_CONTRACT_STATUSES.map((value) => (
            <DropdownMenuRadioItem key={value} value={value}>
              {value === "ended" ? `${CONTRACT_STATUS_LABELS[value]}…` : CONTRACT_STATUS_LABELS[value]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {/* „Do podpisu” / „Anulowany” — wyświetlane, nie do wyboru. */}
        {!selectable ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem disabled>{contractStatusLabel(status)} (bieżący)</DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
