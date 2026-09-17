"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { aiSettingsApi, type AutoMatchOverview as Overview } from "@/lib/api";

const DECISION_LABEL: Record<string, string> = {
  added: "dodany do pipeline'u",
  dry_run: "tryb próbny (bez dodania)",
  below_threshold: "poniżej progu",
  must_gap: "brak must-have",
  penalized: "kara (np. konflikt)",
  ineligible: "zablokowany (bramka przypisania)",
  capped: "limit dodań",
  already_in_pipeline: "już w pipeline",
};

const TRIGGER_LABEL: Record<string, string> = {
  cv_upload: "nowe CV",
  cv_refresh: "odświeżone CV",
  email: "CV z maila",
  public_apply: "link aplikacyjny",
  job_publish: "nowa rekrutacja",
  manual: "ręcznie",
};

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function Summary({ data }: { data: Overview }) {
  const added = data.decisions_7d.added ?? 0;
  const considered = Object.values(data.decisions_7d).reduce((a, b) => a + b, 0);
  const waiting = (data.queue_7d.pending ?? 0) + (data.queue_7d.processing ?? 0);
  const failed = (data.queue_7d.failed ?? 0) + (data.queue_7d.dead ?? 0);
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {[
        ["Dodani (7 dni)", added],
        ["Rozważone pary", considered],
        ["W kolejce", waiting],
        ["Błędy kolejki", failed],
      ].map(([label, value]) => (
        <div key={label as string} className="rounded-lg border border-border p-3">
          <div className="text-xs text-muted-foreground">{label}</div>
          <div className="text-lg font-semibold tabular-nums text-foreground">{value}</div>
        </div>
      ))}
    </div>
  );
}

/** Podgląd autonomicznego dopasowania CV ↔ rekrutacje (Ustawienia → AI). */
export function AutoMatchOverview() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["ai-settings", "auto-match"],
    queryFn: () => aiSettingsApi.autoMatch().then((r) => r.data),
  });

  return (
    <section className="mt-8 rounded-xl border border-border bg-card p-5" data-testid="auto-match-overview">
      <h2 className="text-base font-semibold text-foreground">Automatyczne dopasowania</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Po odczycie nowego CV system sam sprawdza opublikowane rekrutacje. Pasującego
        kandydata dodaje na etap „Ogłoszenia” z tagiem auto-match i powiadamia
        właściciela rekrutacji.
      </p>

      {isLoading && <p className="mt-4 text-sm text-muted-foreground">Wczytywanie…</p>}
      {isError && (
        <p className="mt-4 text-sm text-destructive">
          Nie udało się wczytać dziennika automatycznych dopasowań.
        </p>
      )}
      {data && (
        <div className="mt-4 space-y-4">
          <p className="text-sm text-foreground" data-testid="auto-match-state">
            {!data.enabled
              ? "Wyłączone."
              : data.dry_run
                ? `Tryb próbny: system ocenia i zapisuje decyzje, ale nikogo nie dodaje. Próg ${data.min_score} pkt.`
                : `Włączone. Próg ${data.min_score} pkt, do ${data.max_jobs_per_candidate} rekrutacji na kandydata i ${data.max_candidates_per_job} kandydatów na rekrutację.`}
          </p>
          <Summary data={data} />
          {data.recent.length === 0 ? (
            <p className="text-sm text-muted-foreground">Brak decyzji w dzienniku.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground">
                    <th className="px-3 py-2 font-medium">Kiedy</th>
                    <th className="px-3 py-2 font-medium">Kandydat</th>
                    <th className="px-3 py-2 font-medium">Rekrutacja</th>
                    <th className="px-3 py-2 font-medium">Wynik</th>
                    <th className="px-3 py-2 font-medium">Decyzja</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent.map((row) => (
                    <tr key={`${row.candidate_id}-${row.job_id}-${row.created_at}`} className="border-t border-border align-top">
                      <td className="whitespace-nowrap px-3 py-2 text-muted-foreground tabular-nums">
                        {formatDateTime(row.created_at)}
                        <div className="text-[11px]">{TRIGGER_LABEL[row.trigger] ?? row.trigger}</div>
                      </td>
                      <td className="px-3 py-2">
                        <Link href={`/candidates/${row.candidate_id}`} className="text-primary hover:underline">
                          #{row.candidate_id}
                        </Link>
                      </td>
                      <td className="px-3 py-2">
                        <Link href={`/jobs/${row.job_id}`} className="text-primary hover:underline">
                          {row.job_title}
                        </Link>
                      </td>
                      <td className="px-3 py-2 tabular-nums">{row.score == null ? "—" : Math.round(row.score)}</td>
                      <td className="px-3 py-2">
                        {DECISION_LABEL[row.decision] ?? row.decision}
                        {row.reason && <div className="text-[11px] text-muted-foreground">{row.reason}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
