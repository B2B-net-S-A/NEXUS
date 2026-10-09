"use client";

/**
 * Podgląd kandydata w lewej strefie panelu osoby dla sekcji „CV do klienta”
 * („Zweryfikowany”) i „Rozmowy” (D6, 09.10.2026). Ten sam podgląd co przy
 * formularzu screeningu, ale zaczyna od CV firmowego, gdy para już je ma —
 * na tych etapach rekruter i Delivery Lead patrzą na to, co pójdzie do klienta.
 *
 * W wąskim oknie (poniżej 1024 px) i bez powłoki panelu nie renderuje nic:
 * sekcje mają tam własne okna podglądu („Podgląd”, „Pokaż CV obok”).
 *
 * Podgląd (pdf.js, `docx-preview`) ładuje się za `next/dynamic` — pilnuje
 * tego `heavy-bundle-boundaries.test.ts`.
 */

import dynamic from "next/dynamic";
import type { ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { PersonPanelSide } from "@/components/v2/person/PersonPanelSide";

const CandidatePreviewPane = dynamic(
  () =>
    import("@/components/v2/screening-form/CandidatePreviewPane").then(
      (m) => m.CandidatePreviewPane,
    ),
  { ssr: false, loading: () => <Skeleton className="m-3 h-64 rounded-xl" /> },
);

export interface PersonSidePreviewProps {
  candidateId: number;
  jobId: number;
  /** Najnowszy wiersz etapu pary — kopia CV ze zgłoszenia i CV firmowe. */
  stageId: number | null;
  budgetHourly?: number | null;
  /** Dodatkowa zakładka sekcji (np. „Pytania klienta” przy rozmowach). */
  extraTab?: { label: string; content: ReactNode };
}

export function PersonSidePreview({ candidateId, jobId, stageId, budgetHourly = null, extraTab }: PersonSidePreviewProps) {
  return (
    <PersonPanelSide inline={() => null}>
      <CandidatePreviewPane
        candidateId={candidateId}
        jobId={jobId}
        stageId={stageId}
        preferCompanyCv
        extraTab={extraTab}
        budgetHourly={budgetHourly}
        className="flex-1"
      />
    </PersonPanelSide>
  );
}
