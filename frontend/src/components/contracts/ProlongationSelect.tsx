"use client";

/**
 * Status prolongaty kontraktu edytowany w wierszu — dawniej w rejestrze klienta
 * w module Kontrakty, od 18.11.2026 w zakładce „Konsultanci” profilu klienta.
 * Bez prawa edycji: kropka z etykietą.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { contractsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  PROLONGATION_LABEL,
  PROLONGATION_OPTIONS,
  PROLONGATION_VARIANT,
  type ProlongationStatus,
} from "@/lib/contract-register";
import type { ClientProfileResponse } from "@/types/client-profile";

// Kolory z tokenów (do 02.10.2026 surowe hexy, nieczytelne w ciemnym motywie).
const TEXT_CLASS: Record<string, string> = {
  soft: "text-muted-foreground",
  success: "text-success-muted-foreground",
  warning: "text-warning-muted-foreground",
  danger: "text-destructive",
  neutral: "text-foreground",
};

const DOT_CLASS: Record<string, string> = {
  soft: "bg-muted-foreground/40",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-destructive",
  neutral: "bg-foreground",
};

const DOT_TONE: Record<string, StatusDotTone> = {
  success: "success",
  warning: "warning",
  danger: "danger",
  info: "info",
};

interface Props {
  contractId: number;
  clientId: number;
  value: string | null | undefined;
  canEdit: boolean;
}

export function ProlongationSelect({ contractId, clientId, value, canEdit }: Props) {
  const queryClient = useQueryClient();
  const queryKey = ["client-profile", clientId];
  const current = (value ?? "unknown") as ProlongationStatus;

  const mutation = useMutation({
    mutationFn: (next: ProlongationStatus) =>
      contractsApi.update(contractId, { prolongation_status: next }),
    onMutate: async (next) => {
      await queryClient.cancelQueries({ queryKey });
      const prev = queryClient.getQueryData<ClientProfileResponse>(queryKey);
      queryClient.setQueryData<ClientProfileResponse>(queryKey, (old) => {
        if (!old) return old;
        const patch = <T extends { contract_id: number }>(rows: T[] | undefined) =>
          rows?.map((row) =>
            row.contract_id === contractId ? { ...row, prolongation_status: next } : row,
          );
        return {
          ...old,
          active_consultants: patch(old.active_consultants) ?? [],
          planned_consultants: patch(old.planned_consultants) ?? [],
          pending_consultants: patch(old.pending_consultants),
        };
      });
      return { prev };
    },
    onError: (_error, _next, context) => {
      if (context?.prev) queryClient.setQueryData(queryKey, context.prev);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey });
    },
  });

  const variant = PROLONGATION_VARIANT[current] ?? "soft";

  if (!canEdit) {
    return (
      <StatusDot tone={DOT_TONE[variant] ?? "neutral"}>
        {PROLONGATION_LABEL[current] ?? current}
      </StatusDot>
    );
  }

  return (
    <Select value={current} onValueChange={(next) => mutation.mutate(next as ProlongationStatus)}>
      <SelectTrigger
        aria-label="Prolongata"
        className={cn("h-8 w-[116px] font-medium", TEXT_CLASS[variant])}
      >
        <span className="flex items-center gap-2">
          <span className={cn("h-2 w-2 shrink-0 rounded-full", DOT_CLASS[variant])} />
          <SelectValue />
        </span>
      </SelectTrigger>
      <SelectContent>
        {PROLONGATION_OPTIONS.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
