"use client";

import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";
import { extractErrorMsg } from "@/lib/api";
import { searchFailed, searchIsRunning, type CandidateSearchPage } from "@/lib/full-candidate-search-api";
import { RequirementVerificationDialog } from "./RequirementVerificationDialog";
import { FullCandidateSearchStatus } from "./FullCandidateSearchStatus";

export function FullCandidateSearchResults({ data, error, loading, fetching, offset, onPage, onRetry, onRestart, needsNewRun = false, canOpenProfile, jobId, canVerify = false, onVerified }: {
  data?: CandidateSearchPage;
  error: unknown;
  loading: boolean;
  fetching: boolean;
  offset: number;
  onPage: (offset: number) => void;
  /** Re-read the current run (or start one when there is none yet). */
  onRetry: () => void;
  /** Start a NEW run; omitted while the form cannot start one. */
  onRestart?: () => void;
  /** The stored run can only be replaced — re-reading repeats the answer. */
  needsNewRun?: boolean;
  canOpenProfile: boolean;
  jobId?: number;
  canVerify?: boolean;
  onVerified?: () => void;
}) {
  // A transient read error while the scan is still running must not hide the
  // progress: the scan keeps going on the server and polling resumes by itself.
  if (error && !needsNewRun && data && searchIsRunning(data.state)) return <div className="space-y-4">
    <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-warning/40 bg-warning-muted p-3 text-sm text-warning-muted-foreground">
      <span>Chwilowo nie udało się odświeżyć postępu: {extractErrorMsg(error)}. Przegląd trwa dalej — ponawiamy automatycznie.</span>
      <Button variant="outline" size="sm" onClick={onRetry}>Spróbuj ponownie</Button>
    </div>
    <FullCandidateSearchStatus data={data} offset={offset} onPage={onPage} fetching={fetching} onRestart={onRestart} restarting={loading} />
  </div>;
  if (error) return <div role="alert" className="rounded-lg border p-4">
    <p>Nie udało się odczytać wyszukiwania: {extractErrorMsg(error)}</p>
    {!needsNewRun
      ? <Button onClick={onRetry}>Spróbuj ponownie</Button>
      : onRestart
        ? <Button onClick={onRestart}>Uruchom ponownie</Button>
        : <p className="text-sm text-muted-foreground">Uzupełnij formularz powyżej i uruchom wyszukiwanie ponownie.</p>}
  </div>;
  if (loading) return <p role="status">Wczytuję przegląd całej bazy…</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Sprawdź wymagania i uruchom wyszukiwanie w całej bazie.</p>;
  return <div className="space-y-4">
    <FullCandidateSearchStatus data={data} offset={offset} onPage={onPage} fetching={fetching} onRestart={onRestart} restarting={loading} />
    {!searchIsRunning(data.state) && !searchFailed(data.state) && <>
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
          {/* Konflikt z klientem = ostrzeżenie (17.09.2026); czerwień tylko dla weta HM. */}
          {row.eligibility && <p className={row.eligibility.assignment_allowed === false ? "text-sm text-destructive" : "text-sm text-warning-muted-foreground"}>{row.eligibility.reason}</p>}
          {jobId && canVerify && onVerified && <RequirementVerificationDialog jobId={jobId} candidateId={row.candidate.id} candidateName={[row.candidate.name, row.candidate.lastname].filter(Boolean).join(" ")} onSaved={onVerified} />}
          {canOpenProfile && <Link className={buttonVariants({ variant: "outline" })} href={`/candidates/${row.candidate.id}?from=talent-radar`}>Otwórz profil</Link>}
        </article>)}
      </div>
    </>}
  </div>;
}
