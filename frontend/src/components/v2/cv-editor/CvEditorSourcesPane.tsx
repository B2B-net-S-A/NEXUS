"use client";

/**
 * Treść panelu źródeł: ten sam podgląd kandydata co w screeningu i przeglądzie
 * Delivery Leada (CV oryginalne z „Szukaj w CV”, wymagania klienta, „Po
 * ludzku”) plus notatki z rekrutacji. Osobny plik, bo ciągnie pdf.js —
 * `CvEditorSources` ładuje go przez `next/dynamic`.
 */

import { JobNotesBlock, useJobNotes } from "@/components/v2/jobs/workbench-chrome";
import {
  CandidatePreviewPane,
  type CandidatePreviewPaneProps,
  type PreviewCvSource,
} from "@/components/v2/screening-form/CandidatePreviewPane";

// CV firmowe to dokument otwarty w edytorze — tu zostają źródła, z których powstał.
const EDITOR_SOURCES: ReadonlyArray<PreviewCvSource> = ["original", "files"];

function Notes({ candidateId, jobId }: { candidateId: number; jobId: number }) {
  const query = useJobNotes(candidateId, jobId);
  return (
    <JobNotesBlock
      candidateId={candidateId}
      query={query}
      readOnly
      emptyText="Brak notatek w tej rekrutacji."
    />
  );
}

export interface CvEditorSourcesPaneProps {
  candidateId: number;
  jobId: number;
  stageId: number | null;
  /** Harness: bajty plików bez sieci. */
  loaders?: Pick<CandidatePreviewPaneProps, "loadDocumentBlob" | "loadOriginalBlob">;
}

export function CvEditorSourcesPane({ candidateId, jobId, stageId, loaders }: CvEditorSourcesPaneProps) {
  return (
    <CandidatePreviewPane
      candidateId={candidateId}
      jobId={jobId}
      stageId={stageId}
      cvSources={EDITOR_SOURCES}
      extraTab={{ label: "Notatki", content: <Notes candidateId={candidateId} jobId={jobId} /> }}
      loadDocumentBlob={loaders?.loadDocumentBlob}
      loadOriginalBlob={loaders?.loadOriginalBlob}
      className="h-full"
    />
  );
}
