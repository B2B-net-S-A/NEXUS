"use client";

import { useState, type MouseEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Building2 } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { useCareClients, type CareClientRow } from "@/lib/api/care";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { warsawToday } from "@/lib/warsaw-date";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { HEALTH_BAR, HEALTH_LABELS, healthSegments } from "../health-format";
import {
  CLIENT_FILTERS,
  clientFilterCounts,
  endingNames,
  gapsText,
  healthCountsText,
  lastFeedbackText,
  leadsText,
  managersSubline,
  managersText,
  mapFreshnessText,
  matchesClientFilter,
  openJobsText,
  pendingFeedbackText,
  sortClients,
  type ClientFilter,
} from "./clients-format";

function HealthCell({ row }: { row: CareClientRow }) {
  const segments = row.health ? healthSegments(row.health) : [];
  const text = healthCountsText(row.consultants, row.health);
  return (
    <div className="min-w-28 space-y-1">
      <span className="block whitespace-nowrap tabular-nums">{text}</span>
      {segments.length ? (
        <span
          className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted"
          role="img"
          aria-label={segments.map((s) => `${HEALTH_LABELS[s.level]}: ${s.count}`).join(", ")}
        >
          {segments.map((segment) => (
            <span
              key={segment.level}
              className={HEALTH_BAR[segment.level]}
              style={{ width: `${segment.percent}%` }}
            />
          ))}
        </span>
      ) : null}
    </div>
  );
}

function stop(event: MouseEvent) {
  event.stopPropagation();
}

interface ClientsPanelProps {
  scope: "mine" | "all";
  /** Otwiera kartę konsultanta (`?contract=`) z kolumny „Kończą w 60 dni”. */
  onOpenContract: (contractId: number) => void;
}

/**
 * „Opieka · Klienci” (decyzja 9): portfel klientów z kompletnością wiedzy
 * (menedżerowie, opinie, mapa), zdrowiem naszych konsultantów, popytem
 * i kończącymi w 60 dni. Klik w wiersz prowadzi do „Ludzi i technologii”
 * klienta. Liczy serwer jednym zapytaniem; awaria ≠ pusta lista.
 */
export function ClientsPanel({ scope, onOpenContract }: ClientsPanelProps) {
  const router = useRouter();
  const query = useCareClients(scope);
  const [filter, setFilter] = useState<ClientFilter>("all");
  const all = query.data?.rows ?? [];
  const counts = clientFilterCounts(all);
  const rows = sortClients(all.filter((row) => matchesClientFilter(row, filter)));
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: rows.length === 0,
  });
  const showHealth = query.data?.health_visible ?? all.some((row) => row.health != null);
  const today = query.data?.today ?? warsawToday();

  return (
    <div className="space-y-3">
      <div role="group" aria-label="Filtr klientów" className="flex flex-wrap gap-1">
        {CLIENT_FILTERS.map((item) => (
          <button
            key={item.value}
            type="button"
            aria-pressed={filter === item.value}
            onClick={() => setFilter(item.value)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs transition-colors",
              filter === item.value
                ? "border-primary bg-primary/10 text-foreground"
                : "border-border text-muted-foreground hover:bg-muted",
            )}
          >
            {item.label}
            {query.isSuccess ? (
              <>
                {" "}
                <span className="tabular-nums">{counts[item.value]}</span>
              </>
            ) : null}
          </button>
        ))}
      </div>

      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie klientów…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          description={state === "error" ? "Nie udało się wczytać listy klientów." : undefined}
          onRetry={() => query.refetch()}
        />
      ) : state === "empty" ? (
        <EmptyState
          icon={Building2}
          title={filter === "all" ? "Brak klientów z naszymi konsultantami" : "Żaden klient nie pasuje do filtra"}
          description={
            filter === "all" && scope === "mine"
              ? "W zakresie „Moi” są klienci Twoich podopiecznych — przełącz na „Mój zakres”."
              : undefined
          }
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full min-w-[900px] text-sm" aria-label="Klienci i wiedza o nich">
            <thead>
              <tr className={CALM_ROW}>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Klient</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>
                  {showHealth ? "Nasi i zdrowie" : "Nasi"}
                </th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")} title="Konsultanci ze wskazanym menedżerem u klienta">
                  Menedżerowie u klienta
                </th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Opinie</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Mapa technologii</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Popyt</th>
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Kończą w 60 dni</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const href = `/clients/${row.client_id}?tab=ludzie`;
                const gaps = gapsText(row.map?.gaps ?? null);
                const jobs = openJobsText(row.demand.open_jobs);
                const managers = managersSubline(row);
                const lastFeedback = lastFeedbackText(row.last_feedback_on);
                const pending = pendingFeedbackText(row.feedback_pending, row.feedback_pending_since);
                const ending = endingNames(row.ending_60);
                return (
                  <tr
                    key={row.client_id}
                    className={cn(CALM_ROW, "cursor-pointer hover:bg-muted/40")}
                    onClick={() => router.push(href)}
                  >
                    <td className="px-3 py-1.5 align-top">
                      <Link href={href} className="font-medium hover:underline" onClick={stop}>
                        {row.name}
                      </Link>
                      <span className={CALM_SUBLINE}>{leadsText(row)}</span>
                    </td>
                    <td className="px-3 py-1.5 align-top">
                      <HealthCell row={row} />
                    </td>
                    <td className="px-3 py-1.5 align-top">
                      <span className="tabular-nums">{managersText(row)}</span>
                      {managers ? <span className={CALM_SUBLINE}>{managers}</span> : null}
                    </td>
                    <td className="px-3 py-1.5 align-top">
                      {lastFeedback ? (
                        <span className="tabular-nums">{lastFeedback}</span>
                      ) : (
                        <span className={CALM_EMPTY}>brak</span>
                      )}
                      {pending ? (
                        <span className={CALM_SUBLINE}>
                          <Badge variant="warning" size="sm">
                            {pending}
                          </Badge>
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-1.5 align-top">
                      {row.map ? (
                        <>
                          <span className={cn(!row.map.last_source_on && "text-muted-foreground")}>
                            {mapFreshnessText(row.map.last_source_on, today)}
                          </span>
                          {gaps ? <span className={CALM_SUBLINE}>{gaps}</span> : null}
                        </>
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                    </td>
                    <td className="max-w-56 px-3 py-1.5 align-top">
                      {row.demand.skills.length ? (
                        <span className="flex flex-wrap gap-1">
                          {row.demand.skills.slice(0, 3).map((skill) => (
                            <span key={skill} className="rounded-md border border-border bg-muted/40 px-1.5 text-xs">
                              {skill}
                            </span>
                          ))}
                          {row.demand.skills.length > 3 ? (
                            <span className="text-xs text-muted-foreground">+{row.demand.skills.length - 3}</span>
                          ) : null}
                        </span>
                      ) : null}
                      {row.demand.hiring_signal ? (
                        <Badge variant="info" size="sm" className="mt-1">
                          klient zatrudnia (z rozmowy)
                        </Badge>
                      ) : null}
                      {jobs ? <span className={CALM_SUBLINE}>{jobs}</span> : null}
                      {!row.demand.skills.length && !row.demand.hiring_signal && !jobs ? (
                        <span className={CALM_EMPTY}>—</span>
                      ) : null}
                    </td>
                    <td className="max-w-60 px-3 py-1.5 align-top">
                      {row.ending_60.length ? (
                        <>
                          <span className="font-medium tabular-nums">{row.ending_60.length}</span>
                          <span className={CALM_SUBLINE}>
                            {ending.shown.map((item, index) => (
                              <span key={item.contractId}>
                                {index ? " · " : null}
                                <button
                                  type="button"
                                  className="hover:underline"
                                  aria-label={`Karta konsultanta: ${item.name}`}
                                  onClick={(event) => {
                                    stop(event);
                                    onOpenContract(item.contractId);
                                  }}
                                >
                                  {item.label}
                                </button>
                              </span>
                            ))}
                            {ending.more ? ` · +${ending.more}` : null}
                          </span>
                        </>
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {query.isSuccess && all.length && !showHealth ? (
        <p className="text-xs text-muted-foreground">
          Zdrowie relacji widzą opiekun, Delivery Lead klienta, Head of Recruitment i administrator.
        </p>
      ) : null}
    </div>
  );
}
