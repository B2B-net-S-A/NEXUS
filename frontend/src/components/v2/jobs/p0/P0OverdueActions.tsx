"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { clearJobP0, extendJobP0, invalidateP0 } from "@/lib/api/jobP0";
import { cn } from "@/lib/utils";

export interface P0OverdueActionsProps {
  jobId: number;
  /** Head of Recruitment i administrator — ci, którzy ustawiają P0. */
  canDecide: boolean;
  className?: string;
}

/**
 * P0 po terminie (prośba Olafa, 06.11.2026): nie znika samo. Head of
 * Recruitment albo admin wybiera „Przedłuż o 24 h” (od teraz) albo
 * „Zakończ P0”; reszta zespołu widzi, że P0 trwa do tej decyzji.
 * Samo kliknięcie jest potwierdzeniem — bez drugiego okna.
 */
export function P0OverdueActions({
  jobId,
  canDecide,
  className,
}: P0OverdueActionsProps) {
  if (!canDecide) {
    return (
      <p
        className={cn(
          "text-[11px] font-medium text-destructive-muted-foreground",
          className,
        )}
        data-testid="p0-overdue-waiting"
      >
        Termin minął — P0 trwa, dopóki Head of Recruitment go nie przedłuży albo
        nie zakończy.
      </p>
    );
  }
  return <DecideButtons jobId={jobId} className={className} />;
}

/** Przyciski osobno: zapytania i toasty tylko u tych, którzy decydują. */
function DecideButtons({
  jobId,
  className,
}: {
  jobId: number;
  className?: string;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState<"extend" | "clear" | null>(null);

  const run = async (kind: "extend" | "clear") => {
    setBusy(kind);
    try {
      await (kind === "extend" ? extendJobP0(jobId) : clearJobP0(jobId));
      invalidateP0(queryClient, jobId);
      toast.showSuccess(
        kind === "extend" ? "P0 przedłużone o 24 h." : "P0 zakończone.",
      );
    } catch (err) {
      toast.showError(
        apiErrorMessage(
          err,
          kind === "extend"
            ? "Nie udało się przedłużyć P0."
            : "Nie udało się zakończyć P0.",
        ),
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      className={cn("flex flex-wrap items-center gap-1.5", className)}
      data-testid="p0-overdue-actions"
      data-tour="p0.overdue-actions"
    >
      <Button
        size="sm"
        variant="outline"
        className="h-6 bg-card px-1.5 text-[11px]"
        loading={busy === "extend"}
        disabled={busy !== null}
        onClick={() => void run("extend")}
      >
        Przedłuż o 24 h
      </Button>
      <Button
        size="sm"
        variant="outline"
        className="h-6 border-destructive/50 bg-card px-1.5 text-[11px] text-destructive"
        loading={busy === "clear"}
        disabled={busy !== null}
        onClick={() => void run("clear")}
      >
        Zakończ P0
      </Button>
    </div>
  );
}
