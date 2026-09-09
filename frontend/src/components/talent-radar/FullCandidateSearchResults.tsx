"use client";

import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";
import { extractErrorMsg } from "@/lib/api";
import { searchIsRunning, type CandidateSearchPage } from "@/lib/full-candidate-search-api";
import { FullCandidateSearchStatus } from "./FullCandidateSearchStatus";

export function FullCandidateSearchResults({ data, error, loading, fetching, offset, onPage, onRetry, canOpenProfile }: {
  data?: CandidateSearchPage;
  error: unknown;
  loading: boolean;
  fetching: boolean;
  offset: number;
  onPage: (offset: number) => void;
  onRetry: () => void;
  canOpenProfile: boolean;
}) {
  if (error) return <div role="alert" className="rounded-lg border p-4">
    <p>Nie udało się odczytać wyszukiwania: {extractErrorMsg(error)}</p>
    <Button onClick={onRetry}>Spróbuj ponownie</Button>
  </div>;
  if (loading) return <p role="status">Wczytuję przegląd całej bazy…</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Sprawdź wymagania i uruchom wyszukiwanie w całej bazie.</p>;
  return <div className="space-y-4">
    <FullCandidateSearchStatus data={data} offset={offset} onPage={onPage} fetching={fetching} />
    {!searchIsRunning(data.state) && <>
      {data.results.length === 0 && <p>Na tej stronie nie ma dostępnych wyników. {data.ranking_complete ? "Zmień wymagania lub próg dopasowania." : "Przegląd wymaga uzupełnienia lub ponownego uruchomienia."}</p>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {data.results.map(row => <article key={row.candidate.id} className="space-y-3 rounded-lg border bg-card p-5">
          <h3 className="font-semibold">{[row.candidate.name, row.candidate.lastname].filter(Boolean).join(" ") || `Kandydat #${row.candidate.id}`}</h3>
          {row.candidate.location && <p className="text-sm text-muted-foreground">{row.candidate.location}</p>}
          <p className="font-medium">{row.fit_score === null ? "Ocena niepełna" : `Dopasowanie: ${row.fit_score.toFixed(1)}/100`}</p>
          {row.fit_score !== null && <progress className="w-full" aria-label="Dopasowanie" value={row.fit_score} max={100} />}
          <ul className="space-y-1 text-sm">
            {row.requirements.filter(r => r.level === "must" || r.level === "nice").map((r, i) => <li key={`${r.level}-${i}`}>
              {r.any_of.join(" lub ")} ({r.level === "must" ? "obowiązkowe" : "dodatkowe"}): {r.status === "met" ? (r.evidence_basis === "reviewed" ? "potwierdzone w weryfikacji" : "sygnał w profilu") : r.status === "not_met" ? "niespełnione" : "brak potwierdzenia"}
              {r.status === "met" && !r.verified_at && " — do weryfikacji"}
              {r.verified_at && ` — weryfikacja ${new Date(r.verified_at).toLocaleDateString("pl-PL")}`}
              {r.stale && " — dane zmienione"}
            </li>)}
          </ul>
          {row.eligibility && <p className="text-sm text-amber-700">{row.eligibility.reason}</p>}
          {canOpenProfile && <Link className={buttonVariants({ variant: "outline" })} href={`/candidates/${row.candidate.id}?from=talent-radar`}>Otwórz profil</Link>}
        </article>)}
      </div>
    </>}
  </div>;
}
