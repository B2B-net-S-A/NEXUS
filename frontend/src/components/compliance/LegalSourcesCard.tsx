"use client";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useLegalSources } from "@/lib/api/legalSources";
import { apiErrorMessage } from "@/lib/api-error";
import { resolveViewState } from "@/lib/view-state";

import { actLine, legalSourceGroups, reviewLine } from "./legal-sources-model";

/**
 * Skąd asystent prawny bierze tekst i z którego dnia (część H planu,
 * `docs/asystent-prawny-plan.md`). Dane z `GET /api/legal/sources`; bramka
 * trasy to Generator umów B2B. Osoba bez tego dostępu (Płace, Kadry, Finanse)
 * nie dostaje karty wcale — 403 to nie awaria, a karta z odmową w jej
 * Przepisach byłaby szumem. Błąd i ładowanie mają własne stany.
 */
export function LegalSourcesCard() {
  const sources = useLegalSources();
  const state = resolveViewState({
    isLoading: sources.isLoading,
    isError: sources.isError,
    error: sources.error,
    isSuccess: sources.isSuccess,
    isEmpty: false,
  });
  const data = sources.data;
  if (state === "forbidden") return null;

  return (
    <section className="min-w-0 rounded-lg border border-border bg-card lg:col-span-2" aria-labelledby="legal-sources-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border/70 px-3.5 py-2">
        <h2 id="legal-sources-title" className="text-[13px] font-semibold">
          Źródła asystenta prawnego
        </h2>
        {data ? <p className="text-xs text-muted-foreground">{reviewLine(data.template_review)}</p> : null}
      </div>
      {state === "loading" ? (
        <p className="px-3.5 py-4 text-sm text-muted-foreground">Wczytywanie źródeł…</p>
      ) : state === "error" || state === "not_found" || !data ? (
        <QueryStateNotice
          state="error"
          description={apiErrorMessage(sources.error, "Nie udało się pobrać źródeł asystenta prawnego.")}
          onRetry={() => sources.refetch()}
          className="m-3 py-6"
        />
      ) : (
        <>
          <div className="grid gap-x-5 gap-y-3 px-3.5 py-3 md:grid-cols-3">
            {legalSourceGroups(data).map((group) => (
              <div key={group.title} className="min-w-0">
                <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
                  {group.title}
                </h3>
                {group.empty ? <p className="py-1.5 text-xs text-muted-foreground">{group.empty}</p> : null}
                <ul className="divide-y divide-border/60">
                  {group.rows.map((row) => (
                    <li key={row.name} className="flex items-center justify-between gap-2 py-1.5">
                      <div className="min-w-0">
                        <div className="text-[13px] font-medium">{row.name}</div>
                        <div className="truncate text-[11.5px] text-muted-foreground" title={row.from}>
                          {row.from}
                        </div>
                      </div>
                      <StatusDot tone={row.tone} className="shrink-0">
                        {row.state}
                      </StatusDot>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          {data.acts.length ? (
            <details className="border-t border-border/60 px-3.5 py-2 text-xs">
              <summary className="cursor-pointer text-muted-foreground">
                Akty w korpusie ({data.acts_ready} z {data.acts_total}) · {data.provisions_total.toLocaleString("pl-PL")} jednostek
              </summary>
              <ul className="mt-1.5 grid gap-x-5 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
                {data.acts.map((act) => {
                  const line = actLine(act);
                  return (
                    <li key={act.key} className="flex min-w-0 items-baseline justify-between gap-2">
                      <span className="truncate font-medium" title={act.title}>
                        {line.name}
                      </span>
                      <StatusDot tone={line.tone} className="shrink-0">
                        {line.detail}
                      </StatusDot>
                    </li>
                  );
                })}
              </ul>
            </details>
          ) : null}
        </>
      )}
    </section>
  );
}
