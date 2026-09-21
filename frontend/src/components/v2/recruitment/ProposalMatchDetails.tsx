"use client";

/**
 * Pełne uzasadnienie dopasowania AI dla osoby z segmentu „Propozycje z bazy".
 *
 * To jedyna część dawnego doku „Dopasowanie" (AI Matching), której panel
 * propozycji nie niesie sam: rozbicie wyniku i opis mocnych stron/luk.
 * Liczy się DOPIERO po jawnym rozwinięciu — to płatne wywołanie modelu,
 * a strzałki ↑ ↓ przewijają listę po kilkanaście osób na minutę.
 */

import { useState } from "react";
import { Sparkles } from "lucide-react";

import { DopasowanieTab } from "@/components/v2/pages/DopasowanieTab";

export function ProposalMatchDetails({
  candidateId,
  jobId,
  jobTitle,
  readOnly,
}: {
  candidateId: number;
  jobId: number;
  jobTitle: string | null;
  readOnly: boolean;
}) {
  // Rozwinięcie jest przypięte do OSOBY: zmiana aktywnego wiersza zwija je,
  // bez efektu i bez jednej klatki z cudzym uzasadnieniem.
  const [openFor, setOpenFor] = useState<number | null>(null);
  if (openFor !== candidateId) {
    return (
      <button
        type="button"
        onClick={() => setOpenFor(candidateId)}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
      >
        <Sparkles className="size-3" aria-hidden /> Pełne uzasadnienie AI
      </button>
    );
  }
  return (
    <DopasowanieTab
      candidateId={candidateId}
      recruitments={[{ job_id: jobId, job_title: jobTitle ?? `Rekrutacja #${jobId}` }]}
      defaultJobId={jobId}
      readOnly={readOnly}
    />
  );
}
