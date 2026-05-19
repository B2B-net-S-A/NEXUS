"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Pin, X } from "lucide-react";
import {
  candidatePinsApi,
  type CandidatePinRow,
} from "@/lib/api";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";

interface PinnedCandidatesBarProps {
  /** Open the candidate's drawer when its chip is clicked. */
  onOpenCandidate: (candidateId: number) => void;
  className?: string;
}

/** Bar of pinned-candidate chips shown above the main candidates list.
 *
 *  Replaces Traffit's auto-recent "Otwarte karty" with an intentional
 *  short-list. Hidden when the user has zero pins so it doesn't take up
 *  space for the casual browsing flow. The bar updates reactively via the
 *  React Query "candidate-pins" key — the drawer's PinButton invalidates
 *  this key after every toggle, so the bar stays in sync.
 *
 *  Click a chip to re-open the candidate in the drawer. The × on each chip
 *  unpins without opening the drawer (handy for quickly clearing the bar). */
export function PinnedCandidatesBar({
  onOpenCandidate,
  className,
}: PinnedCandidatesBarProps) {
  const queryClient = useQueryClient();
  const { data: pins } = useQuery({
    queryKey: ["candidate-pins"],
    queryFn: () => candidatePinsApi.list().then((r) => r.data),
    staleTime: 30_000,
  });

  const unpinMutation = useMutation({
    mutationFn: (candidateId: number) =>
      candidatePinsApi.remove(candidateId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["candidate-pins"] });
    },
  });

  if (!pins || pins.length === 0) return null;

  return (
    <div
      className={cn(
        "flex items-center gap-2 px-3 py-2 rounded-lg border border-border bg-card/60 overflow-x-auto",
        className,
      )}
      role="region"
      aria-label="Przypięci kandydaci"
    >
      <Pin className="h-3.5 w-3.5 shrink-0 text-primary" />
      <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground shrink-0">
        Przypięci ({pins.length})
      </span>
      <div className="flex items-center gap-1.5 flex-wrap">
        {pins.map((pin) => (
          <PinnedChip
            key={pin.id}
            pin={pin}
            onOpen={() => onOpenCandidate(pin.candidate.id)}
            onUnpin={(e) => {
              e.stopPropagation();
              unpinMutation.mutate(pin.candidate.id);
            }}
          />
        ))}
      </div>
    </div>
  );
}

interface PinnedChipProps {
  pin: CandidatePinRow;
  onOpen: () => void;
  onUnpin: (e: React.MouseEvent) => void;
}

function PinnedChip({ pin, onOpen, onUnpin }: PinnedChipProps) {
  const fullName =
    `${pin.candidate.name ?? ""} ${pin.candidate.lastname ?? ""}`.trim() ||
    "Kandydat";
  const initials = fullName
    .split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <button
      type="button"
      onClick={onOpen}
      className="group inline-flex items-center gap-1.5 pl-1 pr-1.5 py-0.5 rounded-full border border-border bg-background hover:bg-primary/10 hover:border-primary transition-colors max-w-[200px]"
      title={fullName}
    >
      <Avatar size="sm" className="h-5 w-5 text-[9px]">
        <AvatarFallback>{initials}</AvatarFallback>
      </Avatar>
      <span className="text-xs text-foreground truncate">{fullName}</span>
      <span
        role="button"
        aria-label="Odepnij"
        title="Odepnij"
        onClick={onUnpin}
        className="inline-flex items-center justify-center h-4 w-4 rounded-full text-muted-foreground hover:bg-foreground/10 hover:text-foreground"
      >
        <X className="h-3 w-3" />
      </span>
    </button>
  );
}
