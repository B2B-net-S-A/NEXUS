"use client";

import { useState } from "react";
import { Flame } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { clearJobP0, extendJobP0, invalidateP0 } from "@/lib/api/jobP0";
import { isP0Active, p0UntilLabel, type P0Source } from "@/lib/job-p0";

import { useNow } from "./useNow";

export interface JobP0StripProps {
  jobId: number;
  job: P0Source;
  /** `can_set_p0` z `GET /api/jobs/{id}` — Head of Recruitment, administrator. */
  canSet: boolean;
}

/**
 * Pasek P0 nad tytułem rekrutacji (27.10.2026): do kiedy, kto i po co.
 * „Przedłuż o 24 h” i „Zdejmij P0” tylko dla osób, które ustawiają P0.
 */
export function JobP0Strip({ jobId, job, canSet }: JobP0StripProps) {
  const now = useNow();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [busy, setBusy] = useState<"extend" | "clear" | null>(null);
  if (!isP0Active(job, now) || !job.p0_until) return null;

  const run = async (kind: "extend" | "clear") => {
    if (kind === "clear") {
      const ok = await askConfirm({
        title: "Zdjąć P0?",
        description:
          "Rekrutacja zniknie z paska P0 i z panelu na pulpicie u wszystkich. Priorytet zostaje taki, jak był.",
        confirmLabel: "Zdejmij P0",
        variant: "destructive",
      });
      if (!ok) return;
    }
    setBusy(kind);
    try {
      await (kind === "extend" ? extendJobP0(jobId) : clearJobP0(jobId));
      invalidateP0(queryClient, jobId);
      toast.showSuccess(kind === "extend" ? "P0 przedłużone o 24 h." : "P0 zdjęte.");
    } catch (err) {
      toast.showError(
        apiErrorMessage(
          err,
          kind === "extend" ? "Nie udało się przedłużyć P0." : "Nie udało się zdjąć P0.",
        ),
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md bg-destructive-muted px-2.5 py-1.5 text-xs text-destructive-muted-foreground"
      data-testid="job-p0-strip"
    >
      <Flame className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span className="font-semibold">P0 — ultrapilne do {p0UntilLabel(job.p0_until, now)}</span>
      {job.p0_reason ? (
        <span className="min-w-0 break-words">
          · {job.p0_set_by_name ? `${job.p0_set_by_name}: ` : ""}„{job.p0_reason}”
        </span>
      ) : null}
      {canSet ? (
        <span className="ml-auto flex shrink-0 gap-1.5">
          <Button
            size="sm"
            variant="outline"
            className="h-7 bg-card"
            loading={busy === "extend"}
            disabled={busy !== null}
            onClick={() => void run("extend")}
          >
            Przedłuż o 24 h
          </Button>
          <Button
            size="sm"
            variant="quiet"
            className="h-7"
            loading={busy === "clear"}
            disabled={busy !== null}
            onClick={() => void run("clear")}
          >
            Zdejmij P0
          </Button>
        </span>
      ) : null}
      {confirmDialog}
    </div>
  );
}
