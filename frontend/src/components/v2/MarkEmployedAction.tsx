"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BriefcaseBusiness, CheckCircle2, Loader2 } from "lucide-react";

import { phase5Api, extractErrorMsg } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/Toast";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import type { EmploymentInfo } from "@/components/v2/CandidateHighlights";

interface MarkEmployedActionProps {
  candidateId: number;
  /** Current derived employment snapshot; the action hides when already
   *  flagged at a client (the badge/banner already communicates it). */
  employment?: EmploymentInfo | null;
  size?: "sm" | "md";
  variant?: "primary" | "outline" | "ghost";
  className?: string;
  /** Fired after a successful mark, so the host can refetch its own data. */
  onMarked?: () => void;
}

/**
 * One-click "mark this consultant as employed at a client". Creates a
 * `current_employment` conflict, which `_derive_employment` (backend) turns
 * into the loud "U klienta" badge + the do-not-send-profile banner — the
 * structured replacement for the legacy `[zatrudniony]` name hack.
 *
 * A client is required (the conflict is candidate↔client), so the popover
 * asks for one plus an optional note.
 */
export function MarkEmployedAction({
  candidateId,
  employment,
  size = "sm",
  variant = "outline",
  className,
  onMarked,
}: MarkEmployedActionProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [open, setOpen] = React.useState(false);
  const [clientId, setClientId] = React.useState("");
  const [reason, setReason] = React.useState("");

  const clientsQuery = useQuery({
    queryKey: ["clients-lookup"],
    queryFn: () => phase5Api.clientsLookup().then((response) => response.data),
    enabled: open,
    staleTime: 5 * 60_000,
  });

  const markMutation = useMutation({
    mutationFn: () =>
      phase5Api.conflicts.create(candidateId, {
        client_id: Number(clientId),
        type: "current_employment",
        reason: reason.trim() || undefined,
      }),
    onSuccess: () => {
      showSuccess("Oznaczono jako zatrudnionego u klienta");
      setOpen(false);
      setClientId("");
      setReason("");
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.detail(candidateId),
      });
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.quickView(candidateId),
      });
      queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
      onMarked?.();
    },
    onError: (error) =>
      showError(extractErrorMsg(error) || "Nie udało się oznaczyć kandydata"),
  });

  // Already employed at one of our clients — nothing to add.
  if (employment?.state === "employed_at_client") return null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button size={size} variant={variant} className={className}>
          <BriefcaseBusiness className="h-4 w-4" />
          Oznacz jako zatrudnionego
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 space-y-3">
        <div className="space-y-1">
          <h4 className="text-sm font-semibold text-foreground">
            Oznacz jako zatrudnionego
          </h4>
          <p className="text-xs text-muted-foreground">
            Ustawia „U klienta” na profilu i chroni przed wysłaniem kandydata do
            tego klienta.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="mark-employed-client" className="text-xs">
            Klient
          </Label>
          <select
            id="mark-employed-client"
            value={clientId}
            onChange={(event) => setClientId(event.target.value)}
            className="w-full rounded-md border border-border bg-card px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">— wybierz klienta —</option>
            {clientsQuery.data?.map((client) => (
              <option key={client.id} value={client.id}>
                {client.name}
              </option>
            ))}
          </select>
          {clientsQuery.isPending && open ? (
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> Ładowanie klientów…
            </p>
          ) : null}
          {clientsQuery.error ? (
            <p className="text-xs text-destructive">
              Nie udało się pobrać listy klientów.
            </p>
          ) : null}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="mark-employed-reason" className="text-xs">
            Notatka (opcjonalnie)
          </Label>
          <Input
            id="mark-employed-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="np. projekt u klienta od 06.2026"
          />
        </div>

        <div className="flex justify-end gap-2 pt-1">
          <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
            Anuluj
          </Button>
          <Button
            size="sm"
            onClick={() => markMutation.mutate()}
            loading={markMutation.isPending}
            disabled={!clientId}
          >
            <CheckCircle2 className="h-4 w-4" />
            Oznacz
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
