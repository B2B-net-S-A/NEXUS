"use client";

/**
 * Karta „Pliki” na `/jobs/new` (0427, 09.10.2026). Plik requestu z kroku 1
 * zapisuje się tu sam, Delivery Lead dokłada kolejne. Do „Utwórz i przekaż”
 * pliki wiszą na niedokończonym formularzu; serwer przepina je na rekrutację
 * w transakcji tworzenia, a potem stoją w menu „⋯” → „Pliki”.
 */

import { JobFilesPanel } from "@/components/v2/jobs/files/JobFilesPanel";
import type { JobFilesOwner, JobFilesResponse } from "@/lib/api/jobFiles";

export interface NewJobFilesCardProps {
  /** Id zapisanego formularza; `null` = formularz zapisze się przy pierwszym pliku. */
  formId: number | null;
  /** Zapisuje formularz i oddaje jego id (albo `null`, gdy zapis się nie udał). */
  ensureFormId: () => Promise<number | null>;
  disabled?: boolean;
  /** Harness `/preview/new-job`: gotowe dane, zero zapytań. */
  seed?: JobFilesResponse;
}

export function NewJobFilesCard({ formId, ensureFormId, disabled, seed }: NewJobFilesCardProps) {
  const owner: JobFilesOwner | null =
    formId != null ? { kind: "form", id: formId } : seed ? { kind: "form", id: 0 } : null;
  return (
    <section
      aria-label="Pliki"
      className="rounded-xl border border-border bg-card p-4"
      data-testid="new-job-files-card"
    >
      <h3 className="text-sm font-semibold text-foreground">Pliki</h3>
      <p className="mt-1 mb-3 text-xs text-muted-foreground">
        Request klienta i załączniki. Po utworzeniu rekrutacji zespół znajdzie je w menu „⋯” →
        „Pliki”.
      </p>
      <JobFilesPanel
        owner={owner}
        ensureOwner={async () => {
          const id = await ensureFormId();
          return id != null ? { kind: "form", id } : null;
        }}
        seed={seed}
        disabled={disabled}
        emptyText="Nie dodano jeszcze żadnego pliku."
      />
    </section>
  );
}

export default NewJobFilesCard;
