// Wynik zamkniętego projektu w Rekrutacjach klienta (prośba DL 26.11.2026,
// decyzja Artura: wariant „B + chipy”, wygrana jak w hit ratio). Wynik liczy
// backend (`services/job_outcome.py`, pole `outcome` z `/api/jobs`) — tu tylko
// słowa do wiersza i chipów, żeby ekran nie miał własnej definicji wygranej.

import { closeReasonLabel } from "@/lib/job-close-reasons";
import type { JobCloseReason } from "@/types/client-profile";

export type ProjectOutcome = "won" | "lost" | "neutral" | "unreviewed";
export type OutcomeFilter = "all" | ProjectOutcome;
export type OutcomeCounts = Record<ProjectOutcome, number>;

export interface OutcomeSource {
  outcome?: ProjectOutcome | null;
  close_reason?: JobCloseReason | null;
  hired_names?: string[] | null;
}

/** Kolejność chipów: najpierw to, o co pytała DL, potem to, co trzeba uzupełnić. */
export const OUTCOME_CHIPS: { value: OutcomeFilter; label: string }[] = [
  { value: "all", label: "Wszystkie" },
  { value: "won", label: "Wygrane" },
  { value: "unreviewed", label: "Bez wyniku" },
  { value: "neutral", label: "Nie liczy się" },
  { value: "lost", label: "Przegrane" },
];

export function outcomeTotal(counts: OutcomeCounts): number {
  return counts.won + counts.lost + counts.neutral + counts.unreviewed;
}

/** „Zatrudniony: Piotr K.” / „Zatrudnieni: Michał P., Paweł S.”. */
export function hiredLine(names: readonly string[] | null | undefined): string | null {
  if (!names || names.length === 0) return null;
  return `${names.length > 1 ? "Zatrudnieni" : "Zatrudniony"}: ${names.join(", ")}`;
}

/**
 * Druga linia pod „Zamknięta” dla projektu, który nie jest wygraną. `null`
 * przy „bez wyniku” — tam stoi przycisk „Uzupełnij wynik” albo tekst
 * z `UNREVIEWED_NOTE`, zależnie od uprawnień.
 */
export function closedOutcomeNote(job: OutcomeSource): string | null {
  const reason = closeReasonLabel(job.close_reason ?? null).toLowerCase();
  switch (job.outcome) {
    case "neutral":
      return `Nie liczy się: ${reason}`;
    case "lost":
      // Hit ratio liczy wygraną z zatrudnienia: sam powód bez osoby na
      // „Zatrudniony” to w Lidze DL przegrana — mówimy wprost dlaczego.
      return job.close_reason === "filled_by_us"
        ? "Obsadzone przez nas, ale nikt nie jest na „Zatrudniony”"
        : `Przegrana: ${reason}`;
    default:
      return null;
  }
}

export const UNREVIEWED_NOTE = "Bez powodu zamknięcia";
