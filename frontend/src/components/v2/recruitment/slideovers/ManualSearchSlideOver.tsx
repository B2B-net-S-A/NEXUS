"use client";

/**
 * Okno „Szukaj ręcznie" — szerokie, bo wyszukiwarka niesie szynę filtrów
 * i tabelę wyników; w standardowych 540 px kolumny by się nie zmieściły.
 */

import {
  ManualSearchPanel,
  type ManualSearchJob,
} from "@/components/v2/recruitment/ManualSearchPanel";

import { RecruitmentSheet } from "./RecruitmentSheet";

export interface ManualSearchSlideOverProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  /** `null` dopóki rekrutacja się nie wczytała — okno mówi to wprost. */
  job: ManualSearchJob | null;
  /** Po zbiorczym dodaniu: strona odświeża tabelę osób i dopasowania. */
  onBulkAdded?: () => void;
  readOnly?: boolean;
}

export function ManualSearchSlideOver({
  open,
  onOpenChange,
  jobId,
  job,
  onBulkAdded,
  readOnly = false,
}: ManualSearchSlideOverProps) {
  return (
    <RecruitmentSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Szukaj ręcznie"
      description={
        job
          ? `Filtry wypełnione z rekrutacji „${job.title}”. Osoby, które już w niej są, nie pojawią się w wynikach.`
          : "Wyszukiwarka kandydatów z filtrami tej rekrutacji."
      }
      width="wide"
      bodyClassName="px-3 sm:px-4"
      data-testid="manual-search-slideover"
    >
      {job ? (
        <ManualSearchPanel
          jobId={jobId}
          job={job}
          onBulkAdded={onBulkAdded}
          readOnly={readOnly}
        />
      ) : (
        <p className="p-6 text-sm text-muted-foreground">Ładowanie rekrutacji…</p>
      )}
    </RecruitmentSheet>
  );
}
