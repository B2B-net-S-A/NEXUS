"use client";

import { Button } from "@/components/ui/button";
import { searchIsRunning, type CandidateSearchPage } from "@/lib/full-candidate-search-api";

const exclusionLabels: Record<string, string> = {
  over_budget: "Powyżej budżetu",
  missing_must: "Brak potwierdzenia must-have — wybrano wykluczanie",
  office_days_exceeded: "Za dużo wymaganych dni w biurze",
  office_city_mismatch: "Niezgodne miasto biura",
  remote_only: "Wyłącznie praca zdalna",
  eligibility_hidden: "Wykluczenie według reguł dopuszczalności",
  unknown: "Brak zapisanej szczegółowej przyczyny",
};

/** Same population/coverage vocabulary in Radar and the recruitment pipeline. */
export function FullCandidateSearchStatus({ data, offset, onPage, fetching = false }: {
  data: CandidateSearchPage;
  offset: number;
  onPage: (offset: number) => void;
  fetching?: boolean;
}) {
  const { counts } = data;
  const active = searchIsRunning(data.state);
  return <section className="space-y-2 rounded-lg border p-4" aria-label="Zakres wyszukiwania">
    <p role="status">{active ? "Przeglądamy bazę" : "Przegląd zakończony"}: {counts.evaluated} z {counts.population} kandydatów sprawdzonych.
      {counts.failed > 0 && ` Nie udało się ocenić: ${counts.failed}.`}</p>
    {active && <progress className="w-full" aria-label="Postęp przeglądu" value={counts.population - counts.pending} max={counts.population || 1} />}
    {!active && <>
      <p>Widoczni po filtrach: {counts.eligible}. Wykluczeni: {counts.excluded}. Ocena niepełna: {counts.needs_verification}.</p>
      {counts.exclusion_reasons && <ul aria-label="Przyczyny wykluczenia" className="text-sm text-muted-foreground">
        {Object.entries(counts.exclusion_reasons).filter(([, count]) => count > 0).map(([reason, count]) =>
          <li key={reason}>{exclusionLabels[reason] ?? exclusionLabels.unknown}: {count}</li>
        )}
      </ul>}
      {!data.ranking_complete && <p className="text-amber-700">Ranking nie jest kompletny. Niepełna ocena nie oznacza zerowego dopasowania.</p>}
      {data.data_changed && <p className="text-amber-700">Dane zmieniły się od przeglądu. Uruchom wyszukiwanie ponownie, aby uzyskać aktualny ranking.</p>}
      {data.brief_status === "title_only" && <p className="text-amber-700">Ocena wstępna — request zawiera tylko nazwę roli. Uzupełnij wymagania.</p>}
      {data.metrics && <p className="text-xs text-muted-foreground">
        {data.metrics.elapsed_ms != null && `Czas przeglądu: ${(data.metrics.elapsed_ms / 1000).toFixed(1)} s. `}
        {data.metrics.cost_complete && data.metrics.estimated_cost_usd != null
          ? `Szacowany koszt API: ${data.metrics.estimated_cost_usd.toFixed(6)} USD.`
          : "Koszt API niepełny — brak pełnych danych o zużyciu lub taryfie."}
      </p>}
      <div className="flex items-center gap-3">
        <Button variant="outline" disabled={offset === 0 || fetching} onClick={() => onPage(Math.max(0, offset - 20))}>Poprzednia</Button>
        <span>Strona {Math.floor(offset / 20) + 1} · wyników po progu: {data.total_after_threshold ?? 0}</span>
        <Button variant="outline" disabled={data.next_offset == null || fetching} onClick={() => { if (data.next_offset != null) onPage(data.next_offset); }}>Następna</Button>
      </div>
    </>}
  </section>;
}
