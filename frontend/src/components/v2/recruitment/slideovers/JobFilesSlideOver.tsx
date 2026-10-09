"use client";

/**
 * Okno „Pliki” z menu „⋯” rekrutacji (0428, 09.10.2026): request klienta
 * i załączniki, które Delivery Lead dodał przy zakładaniu rekrutacji albo
 * ktoś dołożył później. Otwiera je `?win=files`.
 */

import { JobFilesPanel } from "@/components/v2/jobs/files/JobFilesPanel";
import type { JobFilesResponse } from "@/lib/api/jobFiles";

import { RecruitmentSheet } from "./RecruitmentSheet";

export interface JobFilesSlideOverProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  /** Tryb tylko do odczytu strony (np. „podgląd jako”) — bez dodawania i usuwania. */
  readOnly?: boolean;
  /** Harness `/preview/*`: gotowe dane, zero zapytań. */
  seed?: JobFilesResponse;
}

export function JobFilesSlideOver({
  open,
  onOpenChange,
  jobId,
  readOnly = false,
  seed,
}: JobFilesSlideOverProps) {
  return (
    <RecruitmentSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Pliki"
      description="Request klienta i załączniki dodane do tej rekrutacji."
      data-testid="job-files-slideover"
    >
      <JobFilesPanel owner={{ kind: "job", id: jobId }} editable={!readOnly} seed={seed} />
    </RecruitmentSheet>
  );
}

export default JobFilesSlideOver;
