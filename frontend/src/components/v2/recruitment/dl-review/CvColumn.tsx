"use client";

/**
 * Strefa CV przeglądu Delivery Leada (D9, 08.10.2026; układ D4, 09.10.2026):
 * CV stoi po lewej jako pierwsze i największe — CV firmowe (to, co pójdzie do
 * klienta, po QC) albo oryginał i inne pliki kandydata.
 *
 * Dwa elementy, bo w siatce przeglądu to dwie osobne komórki:
 * - `CvToolbar` — pigułki „CV firmowe / CV oryginalne”, wynik QC i „Otwórz QC”;
 *   w układzie z zakładkami trzecia pigułka „Wymagania i ocena” zamienia CV na
 *   wymagania (z liczbą braków),
 * - `CvColumn` — samo CV. Który widok pokazać, trzyma rodzic (`view`).
 *
 * CV firmowe renderuje `StageCvPreview` jak dotąd. Oryginał i inne pliki to
 * zakładka CV z podglądu formularza screeningu (0424) — pdf.js i
 * `docx-preview` ładują się za `next/dynamic` (pilnuje
 * `heavy-bundle-boundaries.test.ts`), dopiero gdy DL przełączy podgląd.
 */

import dynamic from "next/dynamic";
import { Loader2, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StageCvPreview } from "@/components/v2/person/StageCvPreview";
import { QcStatusBadge } from "@/components/v2/recruitment/QcStatusBadge";
import type { BoardTaskRow } from "@/lib/api/boardTasks";
import { countPl } from "@/lib/plural-pl";
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

export type CvView = "company" | "original";

const VIEWS: ReadonlyArray<{ value: CvView; label: string }> = [
  { value: "company", label: "CV firmowe" },
  { value: "original", label: "CV oryginalne" },
];

/**
 * Harness: bajty plików bez sieci. Kształt jak w `CandidateCvPreview` — typ
 * spisany tutaj, bo ten plik nie może importować przeglądarki plików nawet
 * jako typu (granica `next/dynamic`).
 */
export interface CvPreviewLoaders {
  loadDocumentBlob?: (
    candidateId: number,
    docId: number,
    disposition: "attachment" | "inline",
  ) => Promise<Blob>;
  loadOriginalBlob?: (stageId: number) => Promise<Blob>;
}

function pillClass(active: boolean): string {
  return cn(
    "rounded px-2.5 py-1 text-xs font-medium transition-colors pointer-coarse:py-2",
    active ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
  );
}

export interface CvToolbarProps {
  task: BoardTaskRow;
  view: CvView;
  onViewChange: (view: CvView) => void;
  /**
   * Układ z zakładkami: trzecia pigułka pokazuje wymagania i ocenę w miejscu
   * CV. `missing` — ile wymagań, które serwer liczy do „X/Y”, ma status
   * „brak”. Bez tego pola pigułki nie ma.
   */
  requirements?: { active: boolean; missing: number; onSelect: () => void } | null;
  onOpenQc: () => void;
  className?: string;
}

export function CvToolbar({ task, view, onViewChange, requirements = null, onOpenQc, className }: CvToolbarProps) {
  const requirementsActive = requirements?.active ?? false;
  return (
    <div className={cn("flex min-w-0 flex-wrap items-center gap-2", className)} data-testid="dl-review-cv-toolbar">
      <div className="inline-flex flex-wrap rounded-md border border-border bg-muted/30 p-0.5">
        <div role="group" aria-label="Które CV pokazać" className="inline-flex">
          {VIEWS.map((option) => {
            const active = !requirementsActive && view === option.value;
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={active}
                onClick={() => onViewChange(option.value)}
                className={pillClass(active)}
              >
                {option.label}
              </button>
            );
          })}
        </div>
        {requirements ? (
          <button
            type="button"
            aria-pressed={requirements.active}
            onClick={requirements.onSelect}
            className={cn(pillClass(requirements.active), "inline-flex items-center gap-1.5")}
          >
            Wymagania i ocena
            {requirements.missing > 0 ? (
              <span className="rounded-full bg-destructive/10 px-1.5 text-[11px] font-semibold text-destructive">
                {countPl(requirements.missing, "brak", "braki", "braków")}
              </span>
            ) : null}
          </button>
        ) : null}
      </div>
      <QcStatusBadge row={task} />
      <Button size="sm" variant="outline" onClick={onOpenQc}>
        <ShieldCheck className="size-3.5" aria-hidden />
        Otwórz QC
      </Button>
    </div>
  );
}

export interface CvColumnProps {
  task: BoardTaskRow;
  view: CvView;
  /**
   * Komórka ma własną wysokość (układ obok decyzji): CV wypełnia ją całą
   * i przewija się w środku. Bez tego — limity jak dotąd (28 rem).
   */
  fill?: boolean;
  /** Zakładka „Wymagania i ocena” zajmuje miejsce CV — ukryte, nie odmontowane. */
  hidden?: boolean;
  previewLoaders?: CvPreviewLoaders;
  className?: string;
}

export function CvColumn({ task, view, fill = false, hidden = false, previewLoaders, className }: CvColumnProps) {
  return (
    <section
      aria-label="CV kandydata"
      hidden={hidden}
      className={cn("flex min-w-0 flex-col", fill && "min-h-0", className)}
      data-testid="dl-review-cv"
    >
      {view === "company" ? (
        // Ten sam `div` w każdym układzie: zmiana szerokości okna nie montuje
        // podglądu od nowa (plik CV pobiera się przy montowaniu).
        <div className={fill ? "relative min-h-0 flex-1 overflow-y-auto" : undefined}>
          <StageCvPreview
            candidateId={task.candidate_id}
            jobId={task.job_id}
            cvStageId={task.cv_stage_id}
            fill={fill}
          />
        </div>
      ) : (
        <div className={fill ? "flex min-h-0 flex-1 flex-col" : "flex min-h-[28rem] flex-col"}>
          <CandidateCvPreview
            candidateId={task.candidate_id}
            jobId={task.job_id}
            stageId={task.stage_id}
            defaultSource="original"
            sources={["original", "files"]}
            {...previewLoaders}
          />
        </div>
      )}
    </section>
  );
}
