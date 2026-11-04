"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import {
  scoringWeightsApi,
  type RankingPanelWeights,
  type RankingPreview,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";

import {
  displayScore,
  engineWeights,
  proposalEligible,
  rankPeople,
  type RankedPerson,
} from "./rankingMath";

const LIST = 10;

interface LivePreviewProps {
  published: RankingPanelWeights;
  local: RankingPanelWeights;
}

/**
 * Podgląd na żywo: składniki oceny 200 pierwszych osób zamkniętej rekrutacji
 * przychodzą raz, a kolejność dla suwaków liczy przeglądarka (bez AI).
 */
export function LivePreview({ published, local }: LivePreviewProps) {
  const jobs = useQuery({
    queryKey: ["scoring-panel-preview-jobs"],
    queryFn: () => scoringWeightsApi.previewJobs().then((r) => r.data.jobs),
    staleTime: 10 * 60 * 1000,
  });
  const [picked, setPicked] = useState<number | null>(null);
  const jobId = picked ?? jobs.data?.[0]?.job_id ?? null;
  const preview = useQuery({
    queryKey: ["scoring-panel-preview", jobId],
    queryFn: () => scoringWeightsApi.preview(jobId as number).then((r) => r.data),
    enabled: jobId !== null,
    staleTime: 15 * 60 * 1000,
  });

  return (
    <section
      aria-labelledby="ranking-preview"
      className="flex min-w-0 flex-[1.3_1_32rem] flex-col gap-3.5 rounded-xl border border-border bg-card p-5"
    >
      <div className="flex flex-col gap-1">
        <h2 id="ranking-preview" className="text-base font-semibold text-foreground">
          Podgląd na żywo
        </h2>
        <label htmlFor="ranking-preview-job" className="text-xs text-muted-foreground">
          Zamknięta rekrutacja do sprawdzenia
        </label>
        {jobs.isLoading && <p className="text-sm text-muted-foreground">Ładuję rekrutacje…</p>}
        {jobs.isError && (
          <QueryStateNotice
            state="error"
            description={apiErrorMessage(jobs.error, "Nie udało się pobrać listy rekrutacji.")}
            onRetry={() => jobs.refetch()}
          />
        )}
        {jobs.isSuccess && jobs.data.length === 0 && (
          <p className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-muted-foreground">
            Brak zamkniętych rekrutacji z co najmniej dwiema osobami zweryfikowanymi albo
            wysłanymi do klienta — podgląd nie ma na czym pokazać zmiany.
          </p>
        )}
        {jobs.isSuccess && jobs.data.length > 0 && (
          <select
            id="ranking-preview-job"
            value={jobId ?? ""}
            onChange={(event) => setPicked(Number(event.target.value))}
            className="min-h-10 w-full rounded-lg border border-border bg-card px-2.5 py-2 text-sm text-foreground"
          >
            {jobs.data.map((job) => (
              <option key={job.job_id} value={job.job_id}>
                {[job.title, job.location, `${job.positives} os. zweryfikowanych lub wysłanych`]
                  .filter(Boolean)
                  .join(" · ")}
              </option>
            ))}
          </select>
        )}
      </div>

      {jobId !== null && preview.isLoading && (
        <p className="text-sm text-muted-foreground" role="status">
          Liczę składniki oceny 200 pierwszych osób (kilka sekund)…
        </p>
      )}
      {preview.isError && (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(preview.error, "Nie udało się policzyć podglądu tej rekrutacji.")}
        </p>
      )}
      {preview.isSuccess && (
        <PreviewList preview={preview.data} published={published} local={local} />
      )}

      <p className="text-xs text-muted-foreground">
        Podgląd liczy się w przeglądarce z zapisanych składników oceny 200 pierwszych osób tej
        rekrutacji — natychmiast, bez AI. Dokładny wynik na wielu rekrutacjach daje „Sprawdź
        na historii”.
      </p>
    </section>
  );
}

function PreviewList({
  preview,
  published,
  local,
}: {
  preview: RankingPreview;
  published: RankingPanelWeights;
  local: RankingPanelWeights;
}) {
  const { before, after } = useMemo(
    () => ({
      before: rankPeople(preview.people, engineWeights(published), preview.renormalize),
      after: rankPeople(preview.people, engineWeights(local), preview.renormalize),
    }),
    [preview, published, local],
  );
  const beforeById = useMemo(
    () => new Map(before.map((item) => [item.person.candidate_id, item])),
    [before],
  );
  if (preview.people.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border px-3 py-3 text-sm text-muted-foreground">
        Nikogo z tej rekrutacji nie udało się zmierzyć — wybierz inną.
      </p>
    );
  }
  const positives = preview.people.filter((p) => p.positive).length;
  const positivesIn = (list: RankedPerson[]) =>
    list.slice(0, LIST).filter((item) => item.person.positive).length;
  const proposals = (list: RankedPerson[], threshold: number) =>
    list.filter((item) => proposalEligible(item.person, item.value, threshold)).length;
  const top = after.slice(0, LIST);
  const moved = top.filter(
    (item) => beforeById.get(item.person.candidate_id)?.rank !== item.rank,
  ).length;

  return (
    <>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        <Tile
          label={`Właściwe osoby w top ${LIST}`}
          value={`${positivesIn(after)} z ${positives}`}
          now={`teraz: ${positivesIn(before)}`}
        />
        <Tile
          label="Trafią do propozycji"
          value={`${proposals(after, local.threshold)} z ${preview.people.length}`}
          now={`teraz: ${proposals(before, published.threshold)}`}
        />
        <Tile label="Osób zmienia miejsce" value={String(moved)} now={`z ${LIST} na liście`} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[34rem] border-collapse text-sm">
          <thead>
            <tr className="text-xs text-muted-foreground">
              <th scope="col" className="border-b border-border px-2 py-1.5 text-left font-medium">Miejsce</th>
              <th scope="col" className="border-b border-border px-2 py-1.5 text-left font-medium">Kandydat</th>
              <th scope="col" className="border-b border-border px-2 py-1.5 text-right font-medium">Teraz</th>
              <th scope="col" className="border-b border-border px-2 py-1.5 text-right font-medium">Po zmianie</th>
              <th scope="col" className="border-b border-border px-2 py-1.5 text-right font-medium">Ruch</th>
            </tr>
          </thead>
          <tbody>
            {top.map((item) => {
              const was = beforeById.get(item.person.candidate_id);
              const delta = was ? was.rank - item.rank : 0;
              const below = item.value < local.threshold;
              return (
                <tr
                  key={item.person.candidate_id}
                  className={cn("border-b border-border last:border-0", item.rank <= 5 && "bg-primary/5")}
                >
                  <td className="px-2 py-2 font-bold tabular-nums text-foreground">{item.rank}</td>
                  <td className="min-w-0 px-2 py-2">
                    <span className="flex flex-wrap items-center gap-1.5 font-semibold text-foreground">
                      {item.person.name}
                      {item.person.positive && (
                        <span className="rounded-full bg-success-muted px-1.5 py-px text-[11px] font-semibold text-success-muted-foreground">
                          zweryfikowany lub wysłany
                        </span>
                      )}
                      {below && (
                        <span className="rounded-full bg-muted px-1.5 py-px text-[11px] text-muted-foreground">
                          poniżej progu
                        </span>
                      )}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {[
                        item.person.city,
                        item.person.must_total
                          ? `${item.person.matched_must} z ${item.person.must_total} wymaganych`
                          : null,
                      ]
                        .filter(Boolean)
                        .join(" · ") || "—"}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-muted-foreground">
                    {was ? `${displayScore(was.value)}%` : "—"}
                  </td>
                  <td className="px-2 py-2 text-right font-bold tabular-nums text-foreground">
                    {displayScore(item.value)}%
                  </td>
                  <td
                    className={cn(
                      "px-2 py-2 text-right font-bold tabular-nums",
                      delta > 0
                        ? "text-success"
                        : delta < 0
                          ? "text-warning-muted-foreground"
                          : "text-muted-foreground",
                    )}
                  >
                    {delta > 0 ? `▲ ${delta}` : delta < 0 ? `▼ ${-delta}` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Tile({ label, value, now }: { label: string; value: string; now: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-border p-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xl font-bold tabular-nums text-foreground">{value}</span>
      <span className="text-xs text-muted-foreground">{now}</span>
    </div>
  );
}
