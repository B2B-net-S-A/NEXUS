"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  BriefcaseBusiness,
  Loader2,
  LockKeyhole,
  RefreshCw,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  candidateFactsApi,
  type CandidateRecentRecruitment,
} from "@/lib/api";
import { formatRelativeTime } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";
import { candidateRecruitmentFocusHref } from "./candidate-profile-navigation";
import {
  candidateQueryKeys,
  candidateViewerScopeKey,
} from "./candidate-query-keys";

interface CandidateRecentRecruitmentsCardProps {
  candidateId: number;
}

function requestStatus(error: unknown): number | null {
  if (!error || typeof error !== "object" || !("response" in error)) return null;
  return (
    error as {
      response?: { status?: number };
    }
  ).response?.status ?? null;
}

function RecruitmentRow({
  candidateId,
  recruitment,
}: {
  candidateId: number;
  recruitment: CandidateRecentRecruitment;
}) {
  const href = candidateRecruitmentFocusHref(
    candidateId,
    recruitment.job_id,
  );
  const recruitmentTitle =
    recruitment.job_title?.trim() || `Rekrutacja #${recruitment.job_id}`;
  const content = (
    <>
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 break-words text-sm font-medium leading-5 text-foreground [overflow-wrap:anywhere]">
          {recruitmentTitle}
        </p>
        {href ? (
          <ArrowUpRight
            aria-hidden="true"
            className="mt-0.5 size-4 shrink-0 text-muted-foreground"
          />
        ) : null}
      </div>
      {recruitment.client_name ? (
        <p className="mt-0.5 min-w-0 truncate text-xs text-muted-foreground">
          {recruitment.client_name}
        </p>
      ) : null}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <Badge
          variant="neutral"
          size="sm"
          className="h-auto max-w-full whitespace-normal py-0.5 [overflow-wrap:anywhere]"
        >
          {recruitment.stage_label || recruitment.stage || "Etap nieznany"}
        </Badge>
        <span className="text-xs text-muted-foreground">
          {recruitment.last_activity_at
            ? formatRelativeTime(recruitment.last_activity_at)
            : "Brak daty aktywności"}
        </span>
      </div>
    </>
  );

  if (!href) {
    return (
      <div className="min-w-0 rounded-lg border border-border bg-background/40 p-3 [overflow-wrap:anywhere]">
        {content}
      </div>
    );
  }

  return (
    <Link
      href={href}
      className="block min-h-11 min-w-0 rounded-lg border border-border bg-background/40 p-3 transition-colors [overflow-wrap:anywhere] hover:border-primary/40 hover:bg-primary/5 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
      aria-label={`Otwórz rekrutację ${recruitmentTitle}`}
    >
      {content}
    </Link>
  );
}

export function CandidateRecentRecruitmentsCard({
  candidateId,
}: CandidateRecentRecruitmentsCardProps) {
  const currentUser = useAuthStore((state) => state.user);
  const viewerScope = candidateViewerScopeKey(currentUser);
  const query = useQuery({
    queryKey: candidateQueryKeys.recentRecruitments(
      candidateId,
      5,
      viewerScope ?? "unauthenticated",
    ),
    queryFn: () => candidateFactsApi.getRecentRecruitments(candidateId, 5),
    enabled: candidateId > 0 && viewerScope !== null,
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });

  const status = requestStatus(query.error);
  const items = query.data?.items ?? [];

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2">
            <BriefcaseBusiness
              aria-hidden="true"
              className="size-4 text-primary"
            />
            Ostatnie rekrutacje
          </CardTitle>
          {!query.isPending &&
          !query.isFetching &&
          !query.isError &&
          items.length ? (
            <Badge variant="neutral" size="sm">
              {items.length}
            </Badge>
          ) : null}
        </div>
      </CardHeader>
      <CardContent aria-live="polite">
        {query.isPending || query.isFetching ? (
          <div
            role="status"
            className="flex items-center gap-2 py-4 text-sm text-muted-foreground"
          >
            <Loader2 aria-hidden="true" className="size-4 animate-spin" />
            Ładowanie rekrutacji…
          </div>
        ) : query.isError ? (
          status === 403 ? (
            <div
              role="status"
              className="rounded-lg border border-border bg-muted/40 p-3 text-sm text-muted-foreground"
            >
              <p className="flex items-start gap-2">
                <LockKeyhole
                  aria-hidden="true"
                  className="mt-0.5 size-4 shrink-0"
                />
                Nie masz dostępu do rekrutacji tego kandydata.
              </p>
            </div>
          ) : (
            <div
              role="alert"
              className="space-y-3 rounded-lg border border-border bg-muted/40 p-3"
            >
              <p className="text-sm text-muted-foreground">
                Nie udało się pobrać ostatnich rekrutacji.
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="min-h-11 min-w-11"
                onClick={() => query.refetch()}
                disabled={query.isFetching}
              >
                <RefreshCw
                  aria-hidden="true"
                  className={query.isFetching ? "size-4 animate-spin" : "size-4"}
                />
                Spróbuj ponownie
              </Button>
            </div>
          )
        ) : items.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-4 py-6 text-center">
            <BriefcaseBusiness
              aria-hidden="true"
              className="mx-auto size-5 text-muted-foreground"
            />
            <p className="mt-2 text-sm text-muted-foreground">
              Kandydat nie ma widocznej historii rekrutacji.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {items.slice(0, 5).map((recruitment) => (
              <RecruitmentRow
                key={`${recruitment.job_id}-${recruitment.latest_stage_id}`}
                candidateId={candidateId}
                recruitment={recruitment}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default CandidateRecentRecruitmentsCard;
