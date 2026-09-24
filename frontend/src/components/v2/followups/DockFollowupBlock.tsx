"use client";

/**
 * Blok „Kontakt z kandydatem” w doku osoby na Tablicy (0371) — makieta C.
 *
 * Rekruter, który NIE dzwoni, widzi tu, kto dzwoni i dlaczego, oraz może
 * przejąć rundę („Zrobię to ja”), gdy i tak rozmawia z kandydatem. Wynik
 * telefonu może zapisać każdy.
 */

import { useState } from "react";
import { PhoneCall } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCandidateFollowup,
  useClaimFollowup,
  type FollowupCardBadge,
} from "@/lib/api/candidateFollowups";
import {
  HISTORY_OUTCOME_LABEL,
  callerReasonSentence,
  followupDueLabel,
  shortDate,
  shortPersonName,
} from "@/lib/candidate-followup";
import { useAuthStore } from "@/store/auth";

import { CandidateFollowupDialog } from "./CandidateFollowupDialog";

export interface DockFollowupBlockProps {
  candidateId: number;
  badge: FollowupCardBadge;
}

export function DockFollowupBlock({ candidateId, badge }: DockFollowupBlockProps) {
  const viewerId = useAuthStore((s) => s.user?.id ?? null);
  const { showSuccess, showError } = useToast();
  const detail = useCandidateFollowup(candidateId);
  const claim = useClaimFollowup(candidateId);
  const [open, setOpen] = useState(false);
  const row = detail.data?.followup ?? null;
  const mine = badge.caller_id != null && badge.caller_id === viewerId;
  const caller = mine ? "Ty" : badge.caller_name ?? "nikt";

  return (
    <div className="rounded-lg bg-primary/5 p-3 text-xs" data-help="jobs.person.followup">
      <p className="mb-1 font-semibold uppercase tracking-wide text-muted-foreground">
        Kontakt z kandydatem
      </p>
      <p className="text-foreground">
        {badge.process_count > 1
          ? `Jest w ${badge.process_count} procesach, w których czekamy na klienta. `
          : "Klient milczy — co 14 dni telefon do kandydata, że dalej jest w procesie. "}
        Telefon robi <span className="font-semibold">{caller}</span>
        {row ? `, bo ${callerReasonSentence(row)}` : ""}. Termin: {followupDueLabel(badge)}.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button size="sm" variant={mine ? "primary" : "outline"} onClick={() => setOpen(true)}>
          <PhoneCall className="h-3.5 w-3.5" />
          Zapisz wynik telefonu
        </Button>
        {!mine && (
          <Button
            size="sm"
            variant="ghost"
            disabled={claim.isPending}
            onClick={() =>
              claim.mutate(undefined, {
                onSuccess: () => showSuccess("Ten follow-up robisz Ty."),
                onError: (error) =>
                  showError(apiErrorMessage(error, "Nie udało się przejąć follow-upu.")),
              })
            }
          >
            Zrobię to ja
          </Button>
        )}
      </div>
      {detail.data && detail.data.history.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-muted-foreground">
          {detail.data.history.slice(0, 2).map((h) => (
            <li key={`${h.created_at}-${h.outcome}`}>
              <span className="tabular-nums">{shortDate(h.created_at)}</span> ·{" "}
              {shortPersonName(h.user_name) || "ktoś z zespołu"} ·{" "}
              {HISTORY_OUTCOME_LABEL[h.outcome] ?? h.outcome}
              {h.note ? ` — „${h.note}”` : ""}
            </li>
          ))}
        </ul>
      )}
      <CandidateFollowupDialog candidateId={candidateId} open={open} onOpenChange={setOpen} />
    </div>
  );
}
