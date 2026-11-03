"use client";

/**
 * Treść panelu źródeł: ten sam podgląd kandydata co w screeningu i przeglądzie
 * Delivery Leada (CV oryginalne z „Szukaj w CV”, wymagania klienta, „Po
 * ludzku”) plus notatki z rekrutacji. Osobny plik, bo ciągnie pdf.js —
 * `CvEditorSources` ładuje go przez `next/dynamic`.
 */

import { JobNotesBlock, useJobNotes } from "@/components/v2/jobs/workbench-chrome";
import {
  CandidateCvPreview,
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
  /** „Pokaż w oryginale” z karty propozycji AI — wyszukanie cytatu w oryginalnym CV. */
  search?: CandidatePreviewPaneProps["searchRequest"];
  /** Sam podgląd CV, bez zakładek — okno stron CV. */
  cvOnly?: boolean;
}

export function CvEditorSourcesPane({ candidateId, jobId, stageId, loaders, search, cvOnly }: CvEditorSourcesPaneProps) {
  if (cvOnly) {
    return (
      <div className="flex h-full min-h-0 flex-col p-3">
        <CandidateCvPreview
          candidateId={candidateId}
          jobId={jobId}
          stageId={stageId}
          sources={EDITOR_SOURCES}
          loadDocumentBlob={loaders?.loadDocumentBlob}
          loadOriginalBlob={loaders?.loadOriginalBlob}
        />
      </div>
    );
  }
  return (
    <CandidatePreviewPane
      candidateId={candidateId}
      jobId={jobId}
      stageId={stageId}
      cvSources={EDITOR_SOURCES}
      // Edytor ma własne „Notatki” tej rekrutacji — historia osoby zostaje w panelu.
      showHistory={false}
      extraTab={{ label: "Notatki", content: <Notes candidateId={candidateId} jobId={jobId} /> }}
      loadDocumentBlob={loaders?.loadDocumentBlob}
      loadOriginalBlob={loaders?.loadOriginalBlob}
      searchRequest={search}
      className="h-full"
    />
  );
}
