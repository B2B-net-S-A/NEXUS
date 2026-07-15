"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, RefreshCw } from "lucide-react";

import { TraffitStatusBadge } from "@/components/settings/TraffitStatusBadge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import api, {
  normalizeTraffitIntegrationStatus,
  traffitIntegrationApi,
  type TraffitIntegrationStatus,
} from "@/lib/api";
import {
  formatLagSeconds,
  getMaximumLagSeconds,
  getTraffitHealthPresentation,
} from "@/lib/traffit-integration";

type TraffitCardStatus =
  | { detail: TraffitIntegrationStatus; healthCheck: null }
  | { detail: null; healthCheck: string };

async function getCardStatus(): Promise<TraffitCardStatus> {
  try {
    return { detail: await traffitIntegrationApi.getStatus(), healthCheck: null };
  } catch {
    const response = await api.get<{
      checks?: { traffit?: string | { status?: string } };
    }>("/api/health");
    const check = response.data.checks?.traffit;
    return {
      detail: null,
      healthCheck:
        typeof check === "string" ? check : check?.status ?? "unknown",
    };
  }
}

function healthCheckPresentation(value: string) {
  if (value === "healthy") {
    return { kind: "healthy" as const, label: "Zdrowa" };
  }
  if (value === "unconfigured") {
    return { kind: "disabled" as const, label: "Wyłączona" };
  }
  if (value === "misconfigured") {
    return { kind: "error" as const, label: "Błąd konfiguracji" };
  }
  return { kind: "degraded" as const, label: "Wymaga uwagi" };
}

export function TraffitIntegrationCard({
  mockStatus,
}: {
  mockStatus?: TraffitIntegrationStatus;
}) {
  const query = useQuery({
    queryKey: ["traffit-integration", "card-status"],
    queryFn: getCardStatus,
    enabled: !mockStatus,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const detail = mockStatus
    ? normalizeTraffitIntegrationStatus(mockStatus)
    : query.data?.detail;
  const presentation = detail
    ? getTraffitHealthPresentation(detail)
    : healthCheckPresentation(query.data?.healthCheck ?? "unknown");
  const pending = detail
    ? detail.queues.inbox_pending + detail.queues.outbox_pending
    : null;

  return (
    <Card size="lg">
      <CardHeader className="flex-row items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <RefreshCw className="h-5 w-5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle>Traffit</CardTitle>
              {query.isLoading && !mockStatus ? (
                <Skeleton className="h-5 w-24" />
              ) : (
                <TraffitStatusBadge
                  kind={presentation.kind}
                  label={presentation.label}
                />
              )}
            </div>
            <CardDescription className="mt-1">
              Dwukierunkowa synchronizacja kandydatów, etapów, notatek i plików.
            </CardDescription>
          </div>
        </div>
      </CardHeader>

      <CardContent>
        {query.isError && !mockStatus ? (
          <p className="rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            Nie udało się pobrać stanu integracji.
          </p>
        ) : (
          <div className="grid grid-cols-3 gap-3 rounded-lg bg-muted p-4">
            <div>
              <p className="text-xs text-muted-foreground">Największy lag</p>
              <p className="mt-1 text-sm font-semibold tabular-nums text-foreground">
                {detail ? formatLagSeconds(getMaximumLagSeconds(detail)) : "—"}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">W kolejce</p>
              <p className="mt-1 text-sm font-semibold tabular-nums text-foreground">
                {pending ?? "—"}
              </p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Konflikty</p>
              <p className="mt-1 text-sm font-semibold tabular-nums text-foreground">
                {detail?.conflicts_open ?? "—"}
              </p>
            </div>
          </div>
        )}

        <div className="mt-4 flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            Cel operacyjny: zmiany widoczne po drugiej stronie do 15 minut.
          </p>
          <Button asChild variant="outline" size="sm">
            <Link href="/settings/traffit">
              Otwórz panel
              <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
