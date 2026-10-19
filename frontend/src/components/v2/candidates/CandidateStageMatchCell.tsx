import { candidateJobNames, jobNameText } from "@/lib/job-name-text";
import { stageMatchHeadline, stageMatchMover, type StageMatch } from "@/lib/stage-filter";

/**
 * Kolumna „Dodany na etap” (19.10.2026): przy filtrze etapu — na którą
 * kolumnę Tablicy, kiedy i kto przesunął osobę oraz w jakiej rekrutacji.
 * Serwer podaje najnowsze przejście spełniające filtr (`stage_match`).
 */
export function CandidateStageMatchCell({ match }: { match: StageMatch | null | undefined }) {
  if (!match) return <span className="text-sm text-muted-foreground">—</span>;
  const headline = stageMatchHeadline(match);
  const mover = stageMatchMover(match);
  const job = jobNameText(candidateJobNames(match));
  const where = match.client_name ? `${job} · ${match.client_name}` : job;
  return (
    <div className="min-w-0" title={`Na etap ${headline} · ${mover}\n${where}`}>
      <p className="truncate text-sm text-foreground">{headline}</p>
      <p className="truncate text-xs text-muted-foreground">
        {mover} · {where}
      </p>
    </div>
  );
}
