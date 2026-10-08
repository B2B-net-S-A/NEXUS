"use client";

/**
 * Środkowa kolumna przeglądu Delivery Leada (D9, 08.10.2026): CV firmowe
 * (to, co pójdzie do klienta — po QC) albo oryginał i inne pliki kandydata,
 * z wynikiem QC i „Otwórz QC”.
 *
 * CV firmowe renderuje `StageCvPreview` jak dotąd. Oryginał i inne pliki to
 * zakładka CV z podglądu formularza screeningu (0424) — pdf.js i
 * `docx-preview` ładują się za `next/dynamic` (pilnuje
 * `heavy-bundle-boundaries.test.ts`), dopiero gdy DL przełączy podgląd.
 */

import dynamic from "next/dynamic";
import { useState } from "react";
import { Loader2, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StageCvPreview } from "@/components/v2/person/StageCvPreview";
import { QcStatusBadge } from "@/components/v2/recruitment/QcStatusBadge";
import type { BoardTaskRow } from "@/lib/api/boardTasks";
import { cn } from "@/lib/utils";

const CandidateCvPreview = dynamic(
  () =>
    import("@/components/v2/screening-form/CandidatePreviewPane").then(
      (m) => m.CandidateCvPreview,
    ),
  {
    ssr: false,
    loading: () => (
      <p className="flex items-center gap-1.5 py-6 text-xs text-muted-foreground" role="status">
        <Loader2 className="size-3.5 animate-spin" aria-hidden /> Wczytywanie podglądu CV…
      </p>
    ),
  },
);

type CvView = "company" | "original";

const VIEWS: ReadonlyArray<{ value: CvView; label: string }> = [
  { value: "company", label: "CV firmowe" },
  { value: "original", label: "CV oryginalne" },
];

export interface CvColumnProps {
  task: BoardTaskRow;
  onOpenQc: () => void;
}

export function CvColumn({ task, onOpenQc }: CvColumnProps) {
  const [view, setView] = useState<CvView>("company");
  return (
    <section aria-label="CV kandydata" className="flex min-w-0 flex-col gap-2" data-testid="dl-review-cv">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Które CV pokazać" className="inline-flex rounded-md border border-border bg-muted/30 p-0.5">
          {VIEWS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={view === option.value}
              onClick={() => setView(option.value)}
              className={cn(
                "rounded px-2.5 py-1 text-xs font-medium transition-colors pointer-coarse:py-2",
                view === option.value
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
        <QcStatusBadge row={task} />
        <Button size="sm" variant="outline" onClick={onOpenQc}>
          <ShieldCheck className="size-3.5" aria-hidden />
          Otwórz QC
        </Button>
      </div>
      {view === "company" ? (
        <StageCvPreview candidateId={task.candidate_id} jobId={task.job_id} cvStageId={task.cv_stage_id} />
      ) : (
        <div className="flex min-h-[28rem] flex-col">
          <CandidateCvPreview
            candidateId={task.candidate_id}
            jobId={task.job_id}
            stageId={task.stage_id}
            defaultSource="original"
            sources={["original", "files"]}
          />
        </div>
      )}
    </section>
  );
}
