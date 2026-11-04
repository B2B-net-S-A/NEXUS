"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { cn } from "@/lib/utils";
import { insightsApi, insightsQueryKeys, type InFlightAcceptance } from "@/lib/insights-api";
import { daysLabel, forecastSentence } from "@/lib/insights-in-flight";
import { countPl } from "@/lib/plural-pl";
import { hasSectionAccess } from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";
import { SectionError } from "@/components/insights/sections/_shared";

import { PanelLoading } from "./ViewKit";

/**
 * Tabela akceptacji do domknięcia — raport i lista na widoku Firma.
 * Bez kandydatów; rekrutacja jest linkiem tylko z dostępem do Rekrutacji
 * (Rada nadzorcza dostaje tekst, jak w „Rekrutacjach bez ruchu”).
 */
export function AcceptancesTable({
  acceptances,
  staleDays,
}: {
  acceptances: readonly InFlightAcceptance[];
  staleDays: number;
}) {
  const canOpenJobs = useAuthStore((s) => hasSectionAccess(s.user, "pipeline"));
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="py-2 pr-3 font-semibold">Klient</th>
            <th className="py-2 pr-3 font-semibold">Rekrutacja</th>
            <th className="py-2 pr-3 font-semibold">W akceptacji od</th>
            <th className="py-2 pr-3 font-semibold">Umowa</th>
            <th className="py-2 font-semibold">Delivery Lead</th>
          </tr>
        </thead>
        <tbody>
          {acceptances.map((a) => (
            <tr key={`${a.job_id}-${a.since}-${a.stage_key}`} className="border-b border-border/60">
              <td className="py-2 pr-3 text-foreground">{a.client_name ?? "—"}</td>
              <td className="py-2 pr-3">
                {canOpenJobs ? (
                  <Link
                    href={`/jobs/${a.job_id}`}
                    className="font-medium text-foreground hover:text-primary hover:underline"
                  >
                    {a.job_title}
                  </Link>
                ) : (
                  <span className="text-foreground">{a.job_title}</span>
                )}
              </td>
              <td
                className={cn(
                  "py-2 pr-3 tabular-nums",
                  a.days > staleDays
                    ? "font-semibold text-warning-muted-foreground"
                    : "text-muted-foreground",
                )}
              >
                {daysLabel(a.days)}
              </td>
              <td className="py-2 pr-3 text-muted-foreground">
                {a.stage_key === "acceptance" ? "—" : a.stage_label.replace("Umowa ", "")}
              </td>
              <td className="py-2 text-muted-foreground">{a.delivery_lead_name ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Raport „Akceptacje w toku” — pełna lista z „W drodze”, stan na dziś. */
export function AcceptancesReport() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.inFlight(),
    queryFn: () => insightsApi.inFlight(),
    staleTime: 60 * 1000,
  });
  if (isPending) return <PanelLoading />;
  if (isError || !data) {
    return (
      <SectionError label="Akceptacje w toku" error={error} onRetry={() => void refetch()} />
    );
  }
  const acceptances = data.acceptances ?? [];
  if (data.acceptances === null) {
    return (
      <p className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
        Listę akceptacji widzą liderzy zespołu, Finanse i Rada nadzorcza — ma
        klientów i Delivery Leadów. Liczbę akceptacji widać w widoku Zespół.
      </p>
    );
  }
  return (
    <div className="space-y-3 rounded-xl border border-border bg-card p-5 shadow-xs">
      <p className="text-sm text-foreground">
        {acceptances.length === 0
          ? "Nie ma akceptacji do domknięcia."
          : `${countPl(acceptances.length, "akceptacja", "akceptacje", "akceptacji")} do domknięcia. ${forecastSentence(data.forecast)}`}
      </p>
      {acceptances.length > 0 ? (
        <AcceptancesTable acceptances={acceptances} staleDays={data.stale_days} />
      ) : null}
      <p className="text-xs text-muted-foreground">{data.definitions.columns}</p>
    </div>
  );
}
