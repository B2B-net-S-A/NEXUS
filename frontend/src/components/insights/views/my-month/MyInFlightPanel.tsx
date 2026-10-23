"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { cn } from "@/lib/utils";
import {
  insightsApi,
  insightsQueryKeys,
  type InFlightColumn,
  type InFlightScope,
} from "@/lib/insights-api";
import { columnOf, daysLabel, forecastSentence } from "@/lib/insights-in-flight";
import { SectionError } from "@/components/insights/sections/_shared";

import { Panel, PanelLoading } from "../ViewKit";

const VISIBLE_ROWS = 5;

const COUNTERS: Record<InFlightScope, InFlightColumn["column"][]> = {
  mine: ["cv_sent", "client_interview", "contract"],
  portfolio: ["cv_qc", "cv_sent", "client_interview", "contract"],
};

/**
 * „Moje osoby w drodze” — stan na dziś: ile moich par czeka na klienta, jest
 * na rozmowie i w akceptacji, od kiedy, i lista (najbliżej placementu
 * najpierw). `mine` = pary, które zweryfikowałem; `portfolio` = rekrutacje
 * Delivery Leada.
 */
export function MyInFlightPanel({
  scope,
  note,
}: {
  scope: InFlightScope;
  /** Zdanie nad licznikami (np. kolejka „Do wysłania do klienta” DL). */
  note?: ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const query = useQuery({
    queryKey: insightsQueryKeys.inFlightMe(scope),
    queryFn: () => insightsApi.inFlightMe(scope),
    staleTime: 60 * 1000,
  });
  const title = scope === "portfolio" ? "W drodze u moich klientów" : "Moje osoby w drodze";
  if (query.isPending) return <PanelLoading />;
  if (query.isError || !query.data) {
    return (
      <SectionError label={title} error={query.error} onRetry={() => void query.refetch()} />
    );
  }
  const data = query.data;
  const people = data.people ?? [];
  const shown = expanded ? people : people.slice(0, VISIBLE_ROWS);
  const accepted = columnOf(data.columns, "contract");

  return (
    <Panel title={title} hint="stan na dziś">
      {note ? <p className="text-sm text-foreground">{note}</p> : null}
      <div
        className={cn(
          "grid grid-cols-1 gap-3 sm:grid-cols-3",
          scope === "portfolio" && "xl:grid-cols-4",
        )}
      >
        {COUNTERS[scope].map((key) => {
          const c = columnOf(data.columns, key);
          if (!c) return null;
          return (
            <div key={key} className="rounded-lg bg-muted/50 p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {c.label}
              </p>
              <p className="text-2xl font-bold tabular-nums text-foreground">{c.count}</p>
              <p
                className={cn(
                  "text-xs",
                  c.stale_count > 0 ? "font-semibold text-warning-muted-foreground" : "text-muted-foreground",
                )}
              >
                {c.count === 0
                  ? "—"
                  : c.stale_count > 0
                    ? `${c.stale_count} dłużej niż ${data.stale_days} dni`
                    : `najdłużej ${daysLabel(c.oldest_days ?? 0)}`}
              </p>
            </div>
          );
        })}
      </div>
      {accepted && accepted.count > 0 ? (
        <p className="text-sm text-foreground">{forecastSentence({ ...data.forecast, open: accepted.count })}</p>
      ) : null}
      {people.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nikt nie czeka teraz na klienta, rozmowę ani akceptację.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="py-2 pr-3 font-semibold">Osoba</th>
                <th className="py-2 pr-3 font-semibold">Rekrutacja · klient</th>
                <th className="py-2 pr-3 font-semibold">Etap</th>
                <th className="py-2 font-semibold">Od kiedy</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => (
                <tr key={`${p.job_id}-${p.candidate_id ?? p.since}`} className="border-b border-border/60">
                  <td className="py-2 pr-3 text-foreground">{p.candidate_name ?? "—"}</td>
                  <td className="py-2 pr-3">
                    <Link
                      href={`/jobs/${p.job_id}`}
                      className="font-medium text-foreground hover:text-primary hover:underline"
                    >
                      {p.job_title}
                    </Link>
                    {p.client_name ? (
                      <span className="text-muted-foreground"> · {p.client_name}</span>
                    ) : null}
                  </td>
                  <td className="py-2 pr-3 text-foreground">{p.stage_label}</td>
                  <td
                    className={cn(
                      "py-2 tabular-nums",
                      p.days > data.stale_days
                        ? "font-semibold text-warning-muted-foreground"
                        : "text-muted-foreground",
                    )}
                  >
                    {daysLabel(p.days)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {people.length > VISIBLE_ROWS ? (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
          className="min-h-9 w-fit text-sm font-semibold text-primary hover:underline"
        >
          {expanded ? "Pokaż mniej" : `Pokaż wszystkie (${people.length})`}
        </button>
      ) : null}
    </Panel>
  );
}
