"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";

import { CvGenerator } from "@/components/v2/cv-generator/CvGenerator";
import { MyCvList } from "@/components/v2/cv-generator/MyCvList";
import type { GeneratedCvItem } from "@/lib/api";
import { canMutateSection } from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";

export interface CVGeneratorStandaloneV2Props {
  /** Osadzony w innym ekranie — bez nagłówka strony. */
  embedded?: boolean;
  prefillCandidateId?: number;
  prefillCandidateName?: string;
  /** Rekrutacja, z której otwarto generator — wybiera proces sama. */
  prefillJobId?: number;
  /** Zgodność z warsztatem wysyłki CV: „Użyj w rekrutacji” przy wierszu listy. */
  onSelectForRecruitment?: (item: { id: number; filename: string }) => void;
  selectedGeneratedId?: number | null;
}

/**
 * Strona `/cv-generator`: nagłówek, generator i lista „Moje CV”.
 * Cała logika formularza żyje w `components/v2/cv-generator/`.
 */
export function CVGeneratorStandaloneV2({
  embedded = false,
  prefillCandidateId,
  prefillCandidateName,
  prefillJobId,
  onSelectForRecruitment,
  selectedGeneratedId,
}: CVGeneratorStandaloneV2Props = {}) {
  const user = useAuthStore((state) => state.user);
  const impersonating = useAuthStore((state) => state.realUser !== null);
  const canWrite = canMutateSection(user, "sourcing", impersonating);
  // „Ponów” z listy wczytuje osobę i rekrutację do formularza (nowy klucz =
  // czysty formularz z tym prefillem).
  const [retry, setRetry] = useState<{ key: number; candidateId: number; name: string; jobId?: number } | null>(null);

  function retryFromList(item: GeneratedCvItem) {
    if (item.candidate_id == null) return;
    setRetry((prev) => ({
      key: (prev?.key ?? 0) + 1,
      candidateId: item.candidate_id!,
      name: item.candidate_name,
      jobId: item.job_id ?? undefined,
    }));
    requestAnimationFrame(() =>
      document.getElementById("cv-generator-form")?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  }

  return (
    <div className={embedded ? "space-y-6" : "mx-auto w-full max-w-6xl space-y-6 px-4 py-8"}>
      {!embedded ? (
        <header className="flex flex-wrap items-start gap-3">
          <div className="rounded-xl bg-primary/10 p-3 text-primary">
            <Sparkles aria-hidden className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold text-foreground">Generator CV</h1>
            <p className="text-sm text-muted-foreground">
              Wybierz osobę i proces. Klienta, Championa, notatki i plik CV weźmiemy z NEXUSA.
            </p>
          </div>
          <a href="#moje-cv" className="self-center text-sm font-medium text-primary hover:underline">
            Moje CV (30 dni)
          </a>
        </header>
      ) : null}

      <div id="cv-generator-form" className="scroll-mt-4">
        <CvGenerator
          key={retry?.key ?? 0}
          embedded={embedded}
          prefillCandidateId={retry?.candidateId ?? prefillCandidateId}
          prefillCandidateName={retry?.name ?? prefillCandidateName}
          prefillJobId={retry ? retry.jobId : prefillJobId}
        />
      </div>

      <div id="moje-cv" className="scroll-mt-4 space-y-3">
        <div>
          <h2 className="text-lg font-semibold text-foreground">
            {embedded && prefillCandidateId != null ? "CV tej osoby" : "Moje CV"}
          </h2>
          {!embedded ? (
            <p className="text-sm text-muted-foreground">Wygenerowane przez Ciebie albo przez zespół — z ostatnich 30 lub 90 dni.</p>
          ) : null}
        </div>
        <MyCvList
          candidateId={embedded ? prefillCandidateId : undefined}
          jobId={embedded ? prefillJobId : undefined}
          canWrite={canWrite}
          onRetry={canWrite ? retryFromList : undefined}
          onSelectForRecruitment={canWrite ? onSelectForRecruitment : undefined}
          selectedGeneratedId={selectedGeneratedId}
        />
      </div>
    </div>
  );
}
