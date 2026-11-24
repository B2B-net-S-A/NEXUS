"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { jobsApi } from "@/lib/api";
import { changeWorkStates } from "@/lib/api/requestAllocation";
import { apiErrorMessage } from "@/lib/api-error";
import { warsawToday } from "@/lib/warsaw-date";

export interface JobOverdueBannerProps {
  jobId: number;
  /** `jobs.deadline` (YYYY-MM-DD). */
  deadline: string | null | undefined;
  /** „Klient milczy” zapisuje stan pracy — Delivery Lead, HoR, admin. */
  canMarkClientSilent: boolean;
  onClose: () => void;
  /** Po zapisie: odśwież rekrutację (stan, termin). */
  onChanged: () => void;
  /** Tylko dla testów. */
  today?: string;
}

function dayMonth(iso: string): string {
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
}

/** Dni kalendarza między dwiema datami YYYY-MM-DD. */
export function daysBetween(from: string, to: string): number {
  return Math.round(
    (Date.parse(`${to.slice(0, 10)}T00:00:00Z`) - Date.parse(`${from.slice(0, 10)}T00:00:00Z`)) /
      86_400_000,
  );
}

export function overdueAgoText(deadline: string, today: string): string {
  const days = daysBetween(deadline, today);
  return days <= 1 ? "wczoraj" : `${days} dni temu`;
}

/**
 * Pasek nad Tablicą rekrutacji „Po terminie” (decyzja Artura 24.11.2026,
 * wariant B z makiet https://claude.ai/artifact/LkYoGLn6JG8w67pAKU7Lv7).
 * Serwer daje `request_stage = "overdue"` dzień po terminie przy „Szukamy”;
 * Delivery Lead wybiera: nowy termin (wraca „Szukamy”), „Klient milczy”
 * (znika z daily i przydziału) albo zamknięcie.
 */
export function JobOverdueBanner({
  jobId,
  deadline,
  canMarkClientSilent,
  onClose,
  onChanged,
  today = warsawToday(),
}: JobOverdueBannerProps) {
  const { showError, showSuccess } = useToast();
  const [picking, setPicking] = useState(false);
  const [newDeadline, setNewDeadline] = useState("");

  const saveDeadline = useMutation({
    mutationFn: (value: string) => jobsApi.update(jobId, { deadline: value }),
    onSuccess: (_data, value) => {
      showSuccess(`Nowy termin ${dayMonth(value)} — rekrutacja wraca do „Szukamy”.`);
      setPicking(false);
      onChanged();
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać terminu.")),
  });
  const markSilent = useMutation({
    mutationFn: () => changeWorkStates([{ job_id: jobId, state: "client_silent" }]),
    onSuccess: () => {
      showSuccess("Ustawiono „Klient milczy”. Rekrutacja zniknęła z daily.");
      onChanged();
    },
    onError: (error) =>
      showError(apiErrorMessage(error, "Nie udało się ustawić „Klient milczy”.")),
  });

  if (!deadline) return null;
  const busy = saveDeadline.isPending || markSilent.isPending;
  const validDate = newDeadline !== "" && newDeadline >= today;

  return (
    <div
      role="status"
      data-testid="job-overdue-banner"
      className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-2.5 text-sm"
    >
      <p className="min-w-0 flex-1 text-destructive">
        <strong>
          Termin minął {dayMonth(deadline)} ({overdueAgoText(deadline, today)}).
        </strong>{" "}
        Rekrutacja nie jest już „Szukamy”, tylko „Po terminie”. Klient dalej przyjmuje CV?
      </p>
      {picking ? (
        <form
          className="flex items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (validDate) saveDeadline.mutate(newDeadline);
          }}
        >
          <Input
            id={`job-${jobId}-new-deadline`}
            type="date"
            min={today}
            value={newDeadline}
            onChange={(event) => setNewDeadline(event.target.value)}
            className="h-8 w-[150px]"
            aria-label="Nowy termin od klienta"
            autoFocus
          />
          <Button type="submit" size="sm" disabled={!validDate || busy}>
            {saveDeadline.isPending ? "Zapisuję…" : "Zapisz termin"}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setPicking(false)}>
            Anuluj
          </Button>
        </form>
      ) : (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setPicking(true)}
          disabled={busy}
        >
          Klient przedłużył…
        </Button>
      )}
      {canMarkClientSilent ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => markSilent.mutate()}
          disabled={busy}
        >
          {markSilent.isPending ? "Zapisuję…" : "Klient milczy"}
        </Button>
      ) : null}
      <Button type="button" size="sm" variant="outline" onClick={onClose} disabled={busy}>
        Zamknij…
      </Button>
    </div>
  );
}
