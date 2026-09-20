"use client";

import { Button } from "@/components/ui/button";
import { searchFailed, searchIsRunning, type CandidateSearchPage } from "@/lib/full-candidate-search-api";

const exclusionLabels: Record<string, string> = {
  over_budget: "Powyżej budżetu",
  // Domyślnie: znane umiejętności nie obejmują technologii must-have. Brak
  // danych o umiejętnościach wyklucza tylko przy polityce „Wyklucz z wyników”.
  missing_must: "Brak technologii must-have w profilu",
  office_days_exceeded: "Za dużo wymaganych dni w biurze",
  office_city_mismatch: "Niezgodne miasto biura",
  remote_only: "Wyłącznie praca zdalna",
  eligibility_hidden: "Wykluczenie według reguł dopuszczalności",
  unknown: "Brak zapisanej szczegółowej przyczyny",
};

const failureReasons: Record<string, string> = {
  candidate_erased: "z bazy usunięto kandydata objętego tym przeglądem",
  stalled: "przegląd przestał robić postępy",
};

/** Same population/coverage vocabulary in Radar and the recruitment pipeline. */
export function FullCandidateSearchStatus({ data, offset, onPage, fetching = false, onRestart, restarting = false }: {
  data: CandidateSearchPage;
  offset: number;
  onPage: (offset: number) => void;
  fetching?: boolean;
  /** Starts a NEW run — offered only for a failed one, never as a re-read. */
  onRestart?: () => void;
  restarting?: boolean;
}) {
  const { counts } = data;
  if (searchFailed(data.state)) {
    // Terminal: no ranking exists, so no pages, totals or "completed" wording —
    // a failed scan must not read as an empty result.
    const reason = failureReasons[data.error_code ?? ""] ?? "nie udało się dokończyć przeglądu bazy";
    return <section className="space-y-2 rounded-lg border border-destructive/40 p-4" aria-label="Zakres wyszukiwania">
      <p role="status" className="font-medium text-destructive">Przegląd przerwany — {reason}. Wyników nie pokazujemy, bo przegląd nie objął całej bazy.</p>
      <p className="text-sm text-muted-foreground">Sprawdzono {counts.evaluated} z {counts.population} kandydatów.</p>
      {onRestart && <Button disabled={restarting} onClick={onRestart}>Uruchom ponownie</Button>}
    </section>;
  }
  const active = searchIsRunning(data.state);
  return <section className="space-y-2 rounded-lg border p-4" aria-label="Zakres wyszukiwania">
    <p role="status">{active ? "Przeglądamy bazę" : "Przegląd zakończony"}: {counts.evaluated} z {counts.population} kandydatów sprawdzonych.
      {counts.failed > 0 && ` Nie udało się ocenić: ${counts.failed}.`}</p>
    {active && <progress className="w-full" aria-label="Postęp przeglądu" value={counts.population - counts.pending} max={counts.population || 1} />}
    {!active && <>
      <p>Stan z chwili przeglądu — widoczni po filtrach: {counts.eligible}. Wykluczeni: {counts.excluded}. Ocena niepełna: {counts.needs_verification}.</p>
      {counts.exclusion_reasons && <ul aria-label="Przyczyny wykluczenia" className="text-sm text-muted-foreground">
        {Object.entries(counts.exclusion_reasons).filter(([, count]) => count > 0).map(([reason, count]) =>
          <li key={reason}>{exclusionLabels[reason] ?? exclusionLabels.unknown}: {count}</li>
        )}
      </ul>}
      {!data.ranking_complete && <p className="text-amber-700">Ranking nie jest kompletny. Niepełna ocena nie oznacza zerowego dopasowania.</p>}
      {data.data_changed && <p className="text-amber-700">Dane zmieniły się od przeglądu. Uruchom wyszukiwanie ponownie, aby uzyskać aktualny ranking.</p>}
      {data.brief_status === "title_only" && <p className="text-amber-700">Ocena wstępna — request zawiera tylko nazwę roli. Uzupełnij wymagania.</p>}
      {/* Koszt API świadomie poza widokiem (decyzja 17.09.2026) — rekruterowi
          nic nie mówi, a czytał się jak rachunek za kliknięcie. */}
      {data.metrics?.elapsed_ms != null && <p className="text-xs text-muted-foreground">
        {`Czas przeglądu: ${(data.metrics.elapsed_ms / 1000).toFixed(1)} s.`}
      </p>}
      <div className="flex items-center gap-3">
        <Button variant="outline" disabled={offset === 0 || fetching} onClick={() => onPage(Math.max(0, offset - 20))}>Poprzednia</Button>
        <span>Strona {Math.floor(offset / 20) + 1} · wyników w przeglądzie po progu: {data.total_after_threshold ?? 0}</span>
        <Button variant="outline" disabled={data.next_offset == null || fetching} onClick={() => { if (data.next_offset != null) onPage(data.next_offset); }}>Następna</Button>
      </div>
    </>}
  </section>;
}
