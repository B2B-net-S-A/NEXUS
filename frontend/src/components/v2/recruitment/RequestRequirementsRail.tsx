"use client";

/**
 * „Wymagania z requestu" — dawna lewa kolumna warsztatu AI Matching.
 *
 * Lista „Musi mieć" / „Mile widziane" z zapisanych wymagań wyszukiwania
 * (ten sam klucz `["matching-requirements", jobId]` co Talent Radar i ręczna
 * wyszukiwarka) oraz TO SAMO wejście edycji co dotąd: `SavedRequestRequirements`
 * za bramką `job.update`. W widoku v3 siedzi w rozwinięciu „Dopasuj kryteria"
 * segmentu propozycji.
 */

import { useQuery } from "@tanstack/react-query";
import { Target } from "lucide-react";

import { SavedRequestRequirements } from "@/components/talent-radar/SavedRequestRequirements";
import { useCapability } from "@/hooks/useCapability";
import { apiErrorMessage } from "@/lib/api-error";
import { matchingRequirementsApi, requirementLabels } from "@/lib/matching-requirements";

export interface RequestRequirementsRailProps {
  jobId: number;
  readOnly?: boolean;
  /** Po zapisie wymagań zapisany przegląd bazy jest nieaktualny — jak w AI Matching. */
  onSaved: () => void;
}

function Chips({ items, dashed = false }: { items: string[]; dashed?: boolean }) {
  return (
    <ul className="flex flex-wrap gap-1">
      {items.map((label) => (
        <li
          key={label}
          className={
            dashed
              ? "rounded-full border border-dashed border-border bg-background px-2 py-0.5 text-[11px] text-muted-foreground"
              : "rounded-full border border-border bg-background px-2 py-0.5 text-[11px] text-foreground"
          }
        >
          {label}
        </li>
      ))}
    </ul>
  );
}

export function RequestRequirementsRail({ jobId, readOnly = false, onSaved }: RequestRequirementsRailProps) {
  // Ta sama bramka co dawna zakładka: PATCH /api/jobs/{id} (capability `job.update`).
  const canEdit = useCapability("job.update") && !readOnly;
  const query = useQuery({
    queryKey: ["matching-requirements", jobId],
    queryFn: () => matchingRequirementsApi.get(jobId),
  });
  const must = requirementLabels(query.data, "must");
  const nice = requirementLabels(query.data, "nice");

  return (
    <section aria-label="Wymagania z requestu" className="space-y-3 md:col-span-2 xl:col-span-4">
      <div className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
        <Target className="h-4 w-4 text-primary" aria-hidden />
        Wymagania
        <span className="text-[10px] font-normal uppercase tracking-wide text-muted-foreground">z requestu</span>
      </div>
      {query.isPending ? (
        <p role="status" className="text-[11px] text-muted-foreground">Wczytuję wymagania…</p>
      ) : query.isError ? (
        // Awaria to nie „brak wymagań" — pustka czytałaby się jak pusty request.
        <p role="alert" className="text-[11px] text-destructive">
          Nie udało się wczytać wymagań: {apiErrorMessage(query.error, "błąd serwera")}
        </p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">Musi mieć · {must.length}</div>
            {must.length > 0 ? (
              <Chips items={must} />
            ) : (
              <p className="text-[11px] text-muted-foreground">Brak — uzupełnij profil Championa lub wymagania rekrutacji.</p>
            )}
          </div>
          {nice.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[11px] font-medium text-muted-foreground">Mile widziane · {nice.length}</div>
              <Chips items={nice} dashed />
            </div>
          )}
        </div>
      )}
      <SavedRequestRequirements jobId={jobId} canEdit={canEdit} onSaved={onSaved} />
    </section>
  );
}
