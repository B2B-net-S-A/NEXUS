"use client";

/**
 * „Wnioski i rady” (25.11.2026): wnioski z reguł kodu są zawsze, a model AI (F56)
 * dokłada wnioski, rady i pytania na spotkanie po kliknięciu. Wynik modelu to
 * dodatek — błąd nie chowa niczego z ekranu.
 */

import { useMutation } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import type { InsightsPeriodParams } from "@/lib/insights-api";
import { lostReviewApi, type LostReviewAiSummary, type LostReviewDlFilter } from "@/lib/lost-review";

import { Panel } from "./LostReviewCharts";

export function LostReviewAiPanel({
  period,
  dl = null,
  findings,
  hasLosses,
}: {
  period: InsightsPeriodParams;
  dl?: LostReviewDlFilter;
  findings: string[];
  hasLosses: boolean;
}) {
  const ai = useMutation<LostReviewAiSummary, unknown, boolean>({
    mutationFn: (refresh) => lostReviewApi.aiSummary(period, refresh, dl),
  });
  const data = ai.data;

  return (
    <Panel title="Wnioski i rady" lede="Wnioski z liczb liczy NEXUS. Rady i pytania na spotkanie dokłada model AI.">
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="min-w-0">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Z liczb</h4>
          <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm" data-testid="lost-review-findings">
            {findings.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
        <div className="min-w-0" data-testid="lost-review-ai">
          <div className="flex items-center justify-between gap-2">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Od AI</h4>
            {hasLosses ? (
              <Button
                type="button"
                size="sm"
                variant={data ? "outline" : "primary"}
                disabled={ai.isPending}
                onClick={() => ai.mutate(Boolean(data))}
              >
                <Sparkles className="mr-1.5 size-4" aria-hidden="true" />
                {ai.isPending ? "Liczę…" : data ? "Policz od nowa" : "Poproś o rady AI"}
              </Button>
            ) : null}
          </div>
          {ai.isError ? (
            <p className="mt-2 text-sm text-destructive">
              {apiErrorMessage(ai.error, "Nie udało się przygotować rad AI. Wnioski z liczb są obok.")}
            </p>
          ) : null}
          {!data && !ai.isError ? (
            <p className="mt-2 text-sm text-muted-foreground">
              {hasLosses
                ? "Model dostaje same liczby i powody z list — bez nazwisk, notatek i stawek."
                : "W tym okresie nie ma przegranych do omówienia."}
            </p>
          ) : null}
          {data ? (
            <div className="mt-2 space-y-3 text-sm">
              {data.conclusions.length ? (
                <ul className="list-disc space-y-1 pl-5">
                  {data.conclusions.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              ) : null}
              {data.advice.length ? (
                <div>
                  <p className="font-semibold">Co zmienić</p>
                  <ul className="mt-1 space-y-1">
                    {data.advice.map((a) => (
                      <li key={`${a.for}-${a.text}`}>
                        <span className="mr-1.5 rounded bg-muted px-1.5 py-0.5 text-xs">{a.for}</span>
                        {a.text}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {data.questions.length ? (
                <div>
                  <p className="font-semibold">Pytania na spotkanie</p>
                  <ul className="mt-1 list-disc space-y-1 pl-5">
                    {data.questions.map((q) => (
                      <li key={q}>{q}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <p className="text-xs text-muted-foreground">
                Model {data.model}
                {data.cached ? " · z pamięci (te same dane)" : ""}. Sprawdź liczby przed decyzją.
              </p>
            </div>
          ) : null}
        </div>
      </div>
    </Panel>
  );
}
