"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pin, PinOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { candidatePinsApi } from "@/lib/api";
import { cn } from "@/lib/utils";

interface PinButtonProps {
  candidateId: number;
  /** Inline icon-only mode for tight spaces (drawer header). When false
   *  the button renders as a labeled chip in the action row. */
  iconOnly?: boolean;
  className?: string;
}

/** Toggle button for the per-user candidate pin (short-list).
 *
 *  Mounts in `CandidateDetailV2` next to the action buttons. On click it
 *  flips the pin state via `POST /api/candidates/{id}/pin` (server side
 *  is idempotent toggle) and invalidates two cache keys so:
 *    - The drawer's pin icon reflects the new state immediately.
 *    - The PinnedCandidatesBar above the list re-fetches and re-renders.
 *
 *  Errors are handled by react-query's `isError` state — the button stays
 *  enabled so the user can retry. We don't surface toast spam for this
 *  micro-action, but disabling on `isPending` prevents double-click double-pin. */
export function PinButton({
  candidateId,
  iconOnly = false,
  className,
}: PinButtonProps) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["candidate-pin-state", candidateId],
    queryFn: () =>
      candidatePinsApi.getState(candidateId).then((r) => r.data),
    staleTime: 30_000,
  });

  const isPinned = Boolean(data?.pinned);

  const toggleMutation = useMutation({
    mutationFn: () => candidatePinsApi.toggle(candidateId).then((r) => r.data),
    onSuccess: (resp) => {
      // Optimistically update the per-candidate state so the icon flips
      // immediately — saves a round-trip to the next refetch.
      queryClient.setQueryData(["candidate-pin-state", candidateId], resp);
      // Top-of-list bar reads from the list endpoint; invalidate so it
      // re-fetches the full set (we don't try to surgically merge there).
      void queryClient.invalidateQueries({ queryKey: ["candidate-pins"] });
    },
  });

  if (iconOnly) {
    return (
      <button
        type="button"
        onClick={() => toggleMutation.mutate()}
        disabled={isLoading || toggleMutation.isPending}
        aria-pressed={isPinned}
        title={isPinned ? "Odepnij" : "Przypnij"}
        className={cn(
          "p-1.5 rounded-md transition-colors",
          isPinned
            ? "text-primary bg-primary/10 hover:bg-primary/20"
            : "text-muted-foreground hover:bg-primary/10 hover:text-foreground",
          className,
        )}
      >
        {isPinned ? (
          <PinOff className="h-4 w-4" />
        ) : (
          <Pin className="h-4 w-4" />
        )}
      </button>
    );
  }

  return (
    <Button
      size="sm"
      variant={isPinned ? "primary" : "outline"}
      onClick={() => toggleMutation.mutate()}
      disabled={isLoading || toggleMutation.isPending}
      title={isPinned ? "Odepnij kandydata" : "Przypnij do short-listy"}
      aria-pressed={isPinned}
      className={className}
    >
      {isPinned ? (
        <>
          <PinOff className="h-4 w-4" />
          Przypięty
        </>
      ) : (
        <>
          <Pin className="h-4 w-4" />
          Przypnij
        </>
      )}
    </Button>
  );
}
