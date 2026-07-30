"use client";

import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Database,
  Loader2,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ExpandableText } from "@/components/v2/ExpandableText";
import {
  activitySummaryApi,
  extractErrorMsg,
  type CandidateActivitySummary,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";
import {
  candidateQueryKeys,
  candidateViewerScopeKey,
} from "./candidate-query-keys";

interface CandidateActivitySummaryCardProps {
  candidateId: number;
}

const SOURCE_LABELS: Record<string, string> = {
  recruitments: "Rekrutacje",
  submissions: "Rekrutacje",
  jobs: "Rekrutacje",
  notes: "Notatki",
  feedback: "Feedback",
  screenings: "Screeningi",
  calls: "Rozmowy",
  candidate: "Profil",
  profile: "Profil",
  contracts: "Współpraca",
};

function requestStatus(error: unknown): number | null {
  if (!error || typeof error !== "object" || !("response" in error)) return null;
  return (
    error as {
      response?: { status?: number };
    }
  ).response?.status ?? null;
}

function containsFinancialAmount(text: string): boolean {
  const number = String.raw`(?:\d{1,3}(?:[\s.]\d{3})*(?:[,.]\d+)?|\d+(?:[,.]\d+)?)`;
  const range = String.raw`${number}(?:\s*(?:-|–|—|do)\s*${number})?`;
  const currency = String.raw`(?:PLN|EUR|USD|GBP|CHF|SEK|NOK|DKK|CZK|zł(?:otych)?|euro|€|£|\$)`;
  const unit = String.raw`(?:\/\s*(?:h|godz\.?|dzień|dzien|day|mies\.?|miesiąc)|netto|brutto)`;
  const financeKeyword = String.raw`(?:staw(?:ka|ki|kę)|wynagrodzeni(?:e|a|u)|pensj(?:a|i|ę)|salary|rate|budżet|budzet|marż(?:a|y|ę)|koszt(?:y|u)?|płac(?:a|y|ę)|zarob(?:ki|ków)|b2b|uop)`;
  return new RegExp(
    [
      String.raw`(?:${currency}\s*${range})`,
      String.raw`(?:${range}\s*(?:k\b\s*|tys\.?\s*)?(?:${currency}|${unit}))`,
      String.raw`(?:${financeKeyword}.{0,48}?${range}(?:\s*(?:k\b|tys\.?))?)`,
      String.raw`(?:${range}\s*(?:k\b|tys\.?\b))`,
    ].join("|"),
    "iu",
  ).test(text);
}

function formatGeneratedAt(value: string): string {
  const generatedAt = new Date(value);
  if (Number.isNaN(generatedAt.getTime())) return "Nieznany czas";
  return new Intl.DateTimeFormat("pl-PL", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(generatedAt);
}

function refreshErrorMessage(error: unknown): string {
  if (requestStatus(error) === 409) {
    return "Inna aktualizacja podsumowania już trwa. Spróbuj ponownie za chwilę.";
  }
  return extractErrorMsg(error) || "Nie udało się zaktualizować podsumowania";
}

function sourcePolicyCounts(data: CandidateActivitySummary) {
  const sources = data.source_manifest?.sources ?? [];
  return {
    redacted: sources.reduce(
      (total, source) =>
        total +
        (source.redacted_financial_fragments ?? 0) +
        (source.redacted_instruction_fragments ?? 0),
      0,
    ),
    truncated: sources.reduce(
      (total, source) => total + (source.truncated_items ?? 0),
      0,
    ),
  };
}

function SummarySources({ data }: { data: CandidateActivitySummary }) {
  const sources = data.source_manifest?.sources ?? [];
  const { redacted, truncated } = sourcePolicyCounts(data);

  if (!sources.length && !data.visibility_scope_hash) return null;

  return (
    <div className="mt-5 rounded-lg border border-border bg-muted/30 p-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground">
          <Database aria-hidden="true" className="size-3.5 text-primary" />
          Zakres źródeł
        </span>
        {sources.map((source) => (
          <Badge
            key={source.name}
            variant="neutral"
            size="sm"
            className="h-auto max-w-full whitespace-normal py-0.5 [overflow-wrap:anywhere]"
          >
            {SOURCE_LABELS[source.name] ?? source.name}:{" "}
            {source.included_items ?? 0}
          </Badge>
        ))}
        {data.visibility_scope_hash ? (
          <span
            className="max-w-full font-mono text-[11px] text-muted-foreground [overflow-wrap:anywhere]"
            title={data.visibility_scope_hash}
          >
            scope:{data.visibility_scope_hash.slice(0, 8)}
          </span>
        ) : null}
      </div>
      {truncated || redacted ? (
        <p className="mt-2 text-xs text-muted-foreground">
          {truncated
            ? `Pominięto ${truncated} elementów poza limitem źródeł. `
            : ""}
          {redacted
            ? `Polityka bezpieczeństwa odfiltrowała ${redacted} fragmentów.`
            : ""}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Wide, cache-only AI history summary. Generation is always explicit. The
 * backend owns visibility scoping and financial redaction; the UI additionally
 * refuses to display a response that still looks like it contains an amount.
 */
export function CandidateActivitySummaryCard({
  candidateId,
}: CandidateActivitySummaryCardProps) {
  const { showError, showSuccess } = useToast();
  const queryClient = useQueryClient();
  const currentUser = useAuthStore((state) => state.user);
  const viewerScope = candidateViewerScopeKey(currentUser);
  const queryKey = candidateQueryKeys.activitySummary(
    candidateId,
    viewerScope ?? "unauthenticated",
  );
  const activeRequestRef = React.useRef({ candidateId, viewerScope });
  activeRequestRef.current = { candidateId, viewerScope };
  const [refreshError, setRefreshError] = React.useState<string | null>(null);

  const query = useQuery<CandidateActivitySummary>({
    queryKey,
    queryFn: () => activitySummaryApi.get(candidateId).then((response) => response.data),
    enabled: candidateId > 0 && viewerScope !== null,
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });

  const refreshMutation = useMutation<
    CandidateActivitySummary,
    unknown,
    { candidateId: number; viewerScope: string }
  >({
    mutationFn: ({ candidateId: requestedCandidateId }) =>
      activitySummaryApi
        .refresh(requestedCandidateId)
        .then((response) => response.data),
    onMutate: (variables) => {
      if (
        activeRequestRef.current.candidateId === variables.candidateId &&
        activeRequestRef.current.viewerScope === variables.viewerScope
      ) {
        setRefreshError(null);
      }
    },
    onSuccess: (data, variables) => {
      if (
        activeRequestRef.current.candidateId !== variables.candidateId ||
        activeRequestRef.current.viewerScope !== variables.viewerScope
      ) {
        return;
      }
      queryClient.setQueryData(
        candidateQueryKeys.activitySummary(
          variables.candidateId,
          variables.viewerScope,
        ),
        data,
      );
      showSuccess(
        data.refreshed === false
          ? "Podsumowanie jest aktualne — brak nowych danych"
          : "Podsumowanie zaktualizowane",
      );
    },
    onError: (error, variables) => {
      if (
        activeRequestRef.current.candidateId !== variables.candidateId ||
        activeRequestRef.current.viewerScope !== variables.viewerScope
      ) {
        return;
      }
      const message = refreshErrorMessage(error);
      setRefreshError(message);
      showError(message);
    },
  });

  React.useEffect(() => {
    setRefreshError(null);
  }, [candidateId, viewerScope]);

  const refreshSummary = () => {
    if (!viewerScope) return;
    refreshMutation.mutate({ candidateId, viewerScope });
  };

  const data = query.data;
  const unsafeSummary = Boolean(
    data?.summary && containsFinancialAmount(data.summary),
  );
  const hasSummary = Boolean(data?.summary) && !unsafeSummary;
  const errorStatus = requestStatus(query.error);
  const policyCounts = data
    ? sourcePolicyCounts(data)
    : { redacted: 0, truncated: 0 };
  const isPartial = policyCounts.redacted > 0 || policyCounts.truncated > 0;

  return (
    <Card aria-labelledby="candidate-activity-summary-title">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle
              id="candidate-activity-summary-title"
              className="flex items-center gap-2"
            >
              <Sparkles aria-hidden="true" className="size-4 text-primary" />
              Podsumowanie historii AI
            </CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              Zwięzły obraz aktywności widocznej w Twoim zakresie uprawnień.
            </p>
          </div>
          {hasSummary ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="min-h-11 min-w-11"
              onClick={refreshSummary}
              disabled={refreshMutation.isPending || !viewerScope}
            >
              <RefreshCw
                aria-hidden="true"
                className={cn(
                  "size-3.5",
                  refreshMutation.isPending && "animate-spin",
                )}
              />
              {refreshMutation.isPending ? "Aktualizuję…" : "Aktualizuj"}
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent
        aria-live="polite"
        aria-busy={
          query.isPending || query.isFetching || refreshMutation.isPending
        }
      >
        {refreshError ? (
          <p
            role="alert"
            className="mb-3 rounded-lg border border-destructive/30 bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground [overflow-wrap:anywhere]"
          >
            {refreshError}
          </p>
        ) : null}
        {query.isPending || query.isFetching ? (
          <div
            role="status"
            className="flex min-h-28 items-center justify-center gap-2 text-sm text-muted-foreground"
          >
            <Loader2 aria-hidden="true" className="size-4 animate-spin" />
            Ładowanie podsumowania…
          </div>
        ) : query.isError ? (
          <div
            role={errorStatus === 403 || errorStatus === 503 ? "status" : "alert"}
            className="rounded-lg border border-border bg-muted/30 p-4"
          >
            {errorStatus === 403 ? (
              <p className="flex items-start gap-2 text-sm text-muted-foreground">
                <LockKeyhole
                  aria-hidden="true"
                  className="mt-0.5 size-4 shrink-0"
                />
                Nie masz dostępu do podsumowania historii tego kandydata.
              </p>
            ) : errorStatus === 503 ? (
              <p className="flex items-start gap-2 text-sm text-muted-foreground">
                <ShieldCheck
                  aria-hidden="true"
                  className="mt-0.5 size-4 shrink-0"
                />
                Podsumowania AI są teraz wyłączone. Dane profilu pozostają
                dostępne.
              </p>
            ) : (
              <div className="space-y-3">
                <p className="flex items-start gap-2 text-sm text-muted-foreground">
                  <AlertTriangle
                    aria-hidden="true"
                    className="mt-0.5 size-4 shrink-0 text-warning"
                  />
                  Podsumowanie historii jest chwilowo niedostępne.
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
                    className={cn(
                      "size-3.5",
                      query.isFetching && "animate-spin",
                    )}
                  />
                  Spróbuj ponownie
                </Button>
              </div>
            )}
          </div>
        ) : unsafeSummary ? (
          <div
            role="alert"
            className="space-y-3 rounded-lg border border-destructive/30 bg-destructive-muted p-4 text-sm text-destructive-muted-foreground"
          >
            <p className="flex items-start gap-2">
              <ShieldCheck
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0"
              />
              Podsumowanie zostało ukryte, ponieważ nie przeszło kontroli
              bezpieczeństwa treści. Odśwież je po usunięciu problemu u źródła.
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="min-h-11 min-w-11"
              onClick={refreshSummary}
              disabled={refreshMutation.isPending || !viewerScope}
            >
              <RefreshCw
                aria-hidden="true"
                className={cn(
                  "size-3.5",
                  refreshMutation.isPending && "animate-spin",
                )}
              />
              {refreshMutation.isPending
                ? "Odświeżam…"
                : "Wygeneruj bezpiecznie ponownie"}
            </Button>
          </div>
        ) : hasSummary && data ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={data.is_stale ? "warning" : "success"} size="sm">
                {data.is_stale ? "Wymaga aktualizacji" : "Aktualne"}
              </Badge>
              {isPartial ? (
                <Badge variant="warning" size="sm">
                  Częściowe
                </Badge>
              ) : null}
              {data.generated_at ? (
                <time
                  dateTime={data.generated_at}
                  className="text-xs text-muted-foreground"
                >
                  Wygenerowano {formatGeneratedAt(data.generated_at)}
                </time>
              ) : null}
              {data.model ? (
                <span className="text-xs text-muted-foreground">
                  Model: {data.model}
                </span>
              ) : null}
            </div>
            <div className="mt-4 text-sm leading-6 text-foreground">
              <ExpandableText text={data.summary!} maxLines={6} />
            </div>
            <div
              className={cn(
                "mt-4 flex items-start gap-2 rounded-lg border px-3 py-2 text-sm",
                data.is_stale
                  ? "border-warning/30 bg-warning-muted text-warning-muted-foreground"
                  : "border-border bg-muted/30 text-muted-foreground",
              )}
            >
              <AlertTriangle
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0"
              />
              <span>
                Zweryfikuj przed decyzją. Podsumowanie AI nie jest źródłem
                prawdy i celowo nie zawiera informacji finansowych.
              </span>
            </div>
            <SummarySources data={data} />
          </>
        ) : (
          <div className="rounded-lg border border-dashed border-border px-4 py-6 text-center">
            <Sparkles
              aria-hidden="true"
              className="mx-auto size-5 text-primary"
            />
            <p className="mx-auto mt-2 max-w-xl text-sm text-muted-foreground">
              AI może streścić wysyłki do projektów, feedback, screening i
              rozmowy dostępne w Twoim zakresie. Kwoty i pozostałe dane
              finansowe są wykluczone.
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-4 min-h-11 min-w-11"
              onClick={refreshSummary}
              disabled={refreshMutation.isPending || !viewerScope}
            >
              {refreshMutation.isPending ? (
                <Loader2
                  aria-hidden="true"
                  className="size-3.5 animate-spin"
                />
              ) : (
                <Sparkles aria-hidden="true" className="size-3.5" />
              )}
              {refreshMutation.isPending
                ? "Generuję podsumowanie…"
                : "Wygeneruj podsumowanie"}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default CandidateActivitySummaryCard;
