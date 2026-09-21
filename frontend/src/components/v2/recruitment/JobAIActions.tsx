"use client";

/**
 * Narzędzia AI administratora dla rekrutacji: podgląd/odświeżenie kryteriów,
 * przeliczenie scoringu, embedding ofert. Przeniesione ze strony rekrutacji
 * (dawna zakładka „AI Matching") — w widoku v3 siedzą w panelu propozycji,
 * za rozwinięciem „Narzędzia AI (administrator)".
 */

import { useState } from "react";

import { phase3Api, recommendationsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import { CriteriaPreviewV2 as CriteriaPreviewModal } from "@/components/v2/modals/CriteriaPreviewV2";

export function JobAIActions({
  jobId,
  onDone,
  readOnly = false,
}: {
  jobId: number;
  onDone: () => void;
  readOnly?: boolean;
}) {
  const [busy, setBusy] = useState<null | "criteria" | "recompute" | "embed-all">(null);
  const [last, setLast] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  const run = async (kind: "criteria" | "recompute" | "embed-all") => {
    if (readOnly) return;
    setBusy(kind);
    setLast(null);
    try {
      if (kind === "criteria") {
        const r = await recommendationsApi.refreshCriteria(jobId);
        const d = r.data as { must_skills: unknown[]; nice_skills: unknown[] };
        setLast(
          `Kryteria odświeżone: must=${d.must_skills.length}, nice=${d.nice_skills.length}`
        );
      } else if (kind === "recompute") {
        const r = await recommendationsApi.recomputeScores(jobId, 200);
        const d = r.data as { evaluated: number };
        setLast(`Przeliczono scoring dla ${d.evaluated} kandydatów`);
      } else {
        const r = await phase3Api.embedAllJobs(500);
        const d = r.data as { requested: number; embedded: number; failed: number };
        setLast(
          `Embedding rekrutacji: requested=${d.requested}, embedded=${d.embedded}, failed=${d.failed}`
        );
      }
      onDone();
    } catch (e: unknown) {
      const msg = apiErrorMessage(e, "Błąd");
      setLast(`Błąd: ${msg}`);
    } finally {
      setBusy(null);
    }
  };

  if (readOnly) return null;

  return (
    <div className="rounded-lg border border-dashed border-primary/30 bg-primary/10 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-2 text-xs font-semibold text-muted-foreground">AI / Scoring:</span>
        <Button size="sm" onClick={() => setShowPreview(true)} disabled={!!busy} data-testid="preview-criteria">
          Podgląd kryteriów (edytowalne)
        </Button>
        <Button size="sm" variant="outline" onClick={() => run("criteria")} disabled={!!busy} data-testid="refresh-criteria">
          {busy === "criteria" ? "Generuję…" : "Szybkie odświeżenie"}
        </Button>
        <Button size="sm" variant="outline" onClick={() => run("recompute")} disabled={!!busy} data-testid="recompute-scores">
          {busy === "recompute" ? "Liczę…" : "Przelicz scoring"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => run("embed-all")}
          disabled={!!busy}
          data-testid="embed-all-jobs"
          title="Jednorazowo: wylicza embeddingi dla wszystkich rekrutacji bez vector ID"
        >
          {busy === "embed-all" ? "Embedduję…" : "Embed all jobs"}
        </Button>
      </div>
      {last && <div className="mt-2 text-xs text-muted-foreground">{last}</div>}

      <CriteriaPreviewModal
        open={showPreview}
        onOpenChange={setShowPreview}
        jobId={jobId}
        onSaved={() => {
          setLast("Kryteria zaktualizowane. Uruchom 'Przelicz scoring' aby odświeżyć wyniki.");
          onDone();
        }}
      />
    </div>
  );
}
