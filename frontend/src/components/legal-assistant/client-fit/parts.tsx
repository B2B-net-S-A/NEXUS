"use client";

// Wspólne kawałki panelu i okna zgodności z umową ramową klienta (część G).

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleHelp, Gavel, Quote } from "lucide-react";

import { useOptionalToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  legalClientFitApi,
  legalClientFitKeys,
  type ClientFitResponse,
  type ClientFitState,
} from "@/lib/api/legalClientFit";
import { cn } from "@/lib/utils";

export const STATE_ICON = {
  gap: AlertTriangle,
  decide: CircleHelp,
  ok: CheckCircle2,
} as const;

export const STATE_TONE: Record<ClientFitState, string> = {
  gap: "text-destructive",
  decide: "text-warning",
  ok: "text-success",
};

/** Odnośnik do źródła: umowa klienta (`client`) albo nasz wzór (`ours`). */
export function RefChip({ kind, label }: { kind: "client" | "ours"; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded border px-1.5 py-px align-baseline text-[11px] font-medium",
        kind === "client"
          ? "border-border bg-muted/60 text-foreground"
          : "border-primary/25 bg-primary/5 text-primary",
      )}
    >
      <CheckCircle2 className="h-3 w-3 shrink-0" aria-label="cytat sprawdzony ze źródłem" />
      <span className="truncate">{label}</span>
    </span>
  );
}

/** Cytat dosłowny ze źródła (sprawdzony kodem po stronie serwera). */
export function QuoteText({
  text,
  className,
  clamp = false,
}: {
  text: string;
  className?: string;
  /** Panel: najwyżej trzy wiersze cytatu (całość w oknie szczegółów). */
  clamp?: boolean;
}) {
  return (
    <p className={cn("flex gap-1.5 text-[12.5px] leading-5 text-muted-foreground", className)}>
      <Quote className="mt-1 size-3 shrink-0 opacity-60" aria-hidden />
      <span className={cn("min-w-0", clamp && "line-clamp-3")} title={clamp ? text : undefined}>
        „{text}”
      </span>
    </p>
  );
}

export function LawyerBadge({ reasons }: { reasons: readonly string[] }) {
  if (!reasons.length) return null;
  return (
    <span
      className="inline-flex items-center gap-1 rounded border border-warning/25 bg-warning-muted px-1.5 py-px text-[11px] font-medium text-warning-muted-foreground"
      title={reasons.join(", ")}
    >
      <Gavel className="h-3 w-3" aria-hidden />
      do prawnika: {reasons.join(", ")}
    </span>
  );
}

/** „Sprawdź ponownie” — bieg w tle; odpowiedź od razu przestawia stan na kolejkę. */
export function useRecheck(clientId: number) {
  const queryClient = useQueryClient();
  const toast = useOptionalToast();
  return useMutation({
    mutationFn: () => legalClientFitApi.check(clientId),
    onSuccess: (res) => {
      queryClient.setQueryData<ClientFitResponse>(legalClientFitKeys.client(clientId), (prev) =>
        prev ? { ...prev, status: res.status, status_message: null } : prev,
      );
      void queryClient.invalidateQueries({ queryKey: legalClientFitKeys.client(clientId) });
    },
    onError: (error) =>
      toast?.showError(apiErrorMessage(error, "Nie udało się uruchomić sprawdzenia.")),
  });
}
