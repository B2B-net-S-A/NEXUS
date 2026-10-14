"use client";

/**
 * „N rzeczy do sprawdzenia przed wysłaniem” — jedna liczba na karcie „CV do
 * klienta” (PR 4 „CV w procesie”, 13.10.2026).
 *
 * Wcześniej karta liczyła tylko uwagi kontroli AI z listy wygenerowanych CV,
 * dok — tylko blokady QC, a edytor — wszystko razem. Teraz karta liczy to samo
 * co „Do poprawy (N)” w edytorze (`cvChecksBeforeSending`): QC (bez zapisu
 * przebiegu), uwagi generatora i kontrolę AI, po pominięciach „To nieprawda”.
 * „Sprawdź i popraw” otwiera edytor od razu na panelu „Do poprawy”.
 *
 * Awaria któregokolwiek źródła nie wygląda jak zero: zero pokazujemy tylko,
 * gdy oba odczyty się udały.
 */

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ListChecks, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { networkIssuesApi } from "@/lib/api/cvEditorIssues";
import { thingsLabel } from "@/lib/cv-qc";
import {
  cvChecksBeforeSending,
  cvToClientIssuesQueryKey,
  cvToClientQcQueryKey,
} from "@/lib/cv-to-client";
import { isForbiddenError } from "@/lib/view-state";

export interface CvToClientChecksProps {
  /** Wiersz etapu, na którym leży CV pary (ten sam, który otwiera edytor). */
  stageId: number;
  /** Wersja szkicu — po zapisie albo podpięciu nowego CV liczymy od nowa. */
  revision: number | null;
  readOnly: boolean;
  onReview: () => void;
}

export interface CvChecksCount {
  status: "loading" | "failed" | "forbidden" | "ready";
  count: number;
  retry: () => void;
}

/**
 * Liczba rzeczy do sprawdzenia przed wysłaniem — te same dwa odczyty (i klucze)
 * co karta, więc blok postępu po przekazaniu (14.10.2026) nie pyta drugi raz.
 */
export function useCvChecksCount(stageId: number, revision: number | null, enabled = true): CvChecksCount {
  const qcQuery = useQuery({
    queryKey: cvToClientQcQueryKey(stageId, revision),
    queryFn: () => networkIssuesApi.qc(stageId),
    staleTime: 30_000,
    enabled,
  });
  const issuesQuery = useQuery({
    queryKey: cvToClientIssuesQueryKey(stageId, revision),
    queryFn: () => networkIssuesApi.issues(stageId),
    staleTime: 30_000,
    enabled,
  });
  const retry = () => {
    if (qcQuery.isError) void qcQuery.refetch();
    if (issuesQuery.isError) void issuesQuery.refetch();
  };
  // QC tej rekrutacji jest tylko dla zespołu — bez dostępu karta o nim milczy.
  if (isForbiddenError(qcQuery.error) || isForbiddenError(issuesQuery.error)) {
    return { status: "forbidden", count: 0, retry };
  }
  if (qcQuery.isPending || issuesQuery.isPending) return { status: "loading", count: 0, retry };
  if (qcQuery.isError || issuesQuery.isError) return { status: "failed", count: 0, retry };
  const qc = qcQuery.data;
  const issues = issuesQuery.data;
  // QC bierze zatwierdzone CV pary; gdy opisuje inny wiersz etapu, jego lista
  // nie dotyczy tego CV (tak samo liczy panel w edytorze).
  const checks = qc.cv != null && qc.cv.stage_id === stageId ? qc.checks : [];
  const count = cvChecksBeforeSending({
    checks,
    warnings: issues.generator_warnings,
    findings: issues.content_review.findings,
  });
  return { status: "ready", count, retry };
}

export function CvToClientChecks({ stageId, revision, readOnly, onReview }: CvToClientChecksProps) {
  const { status, count, retry } = useCvChecksCount(stageId, revision);

  if (status === "forbidden") return null;

  if (status === "loading") {
    return (
      <p role="status" className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="size-3 animate-spin" aria-hidden /> Sprawdzam CV przed wysłaniem…
      </p>
    );
  }
  if (status === "failed") {
    return (
      <p role="alert" className="text-xs text-destructive-muted-foreground">
        Nie udało się policzyć rzeczy do sprawdzenia — to nie znaczy, że ich nie ma.{" "}
        <button type="button" className="font-medium underline underline-offset-2" onClick={retry}>
          Ponów
        </button>
      </p>
    );
  }

  if (count === 0) {
    return (
      <p
        role="status"
        data-testid="cv-checks-count"
        className="flex items-center gap-1.5 rounded-md border border-success/30 bg-success-muted px-2.5 py-1.5 text-xs text-success-muted-foreground"
      >
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0" aria-hidden />
        Nic do sprawdzenia przed wysłaniem
      </p>
    );
  }
  return (
    <div
      role="note"
      data-testid="cv-checks-count"
      className="flex flex-wrap items-center gap-2 rounded-md border border-warning/30 bg-warning-muted px-2.5 py-1.5 text-xs text-warning-muted-foreground"
    >
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 flex-1 font-medium">{thingsLabel(count)} do sprawdzenia przed wysłaniem</span>
      {readOnly ? null : (
        <Button size="sm" variant="outline" onClick={onReview}>
          <ListChecks className="h-3.5 w-3.5" aria-hidden /> Sprawdź i popraw
        </Button>
      )}
    </div>
  );
}
