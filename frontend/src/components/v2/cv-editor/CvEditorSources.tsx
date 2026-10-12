"use client";

/**
 * Panel źródeł w edytorze CV: z czego to CV powstało i czego chce klient.
 * Edytor zna tylko etap (albo wynik generatora), więc parę kandydat–rekrutacja
 * bierze z kopii CV ze zgłoszenia — to samo zapytanie co dok osoby i karta CV.
 */

import type { ReactNode } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { candidateStageCvApi, type CVOriginalSnapshot } from "@/lib/api";

import type { CvEditorSourcesPaneProps } from "./CvEditorSourcesPane";

function Note({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
      <div className="max-w-xs space-y-3">{children}</div>
    </div>
  );
}

const CvEditorSourcesPane = dynamic(
  () => import("./CvEditorSourcesPane").then((module) => module.CvEditorSourcesPane),
  { ssr: false, loading: () => <Note>Wczytywanie źródeł…</Note> },
);

export interface CvEditorSourceContext {
  candidateId: number;
  jobId: number;
  stageId: number | null;
}

export interface CvEditorSourcesProps {
  /** Etap z edytowanym CV — z niego wynika kandydat i rekrutacja. */
  stageId?: number;
  /** Para podana wprost (wynik generatora, harness); `null` = CV bez rekrutacji. */
  context?: CvEditorSourceContext | null;
  loaders?: CvEditorSourcesPaneProps["loaders"];
  search?: CvEditorSourcesPaneProps["search"];
}

export function CvEditorSources({ stageId, context, loaders, search }: CvEditorSourcesProps) {
  const fromStage = !context && stageId != null;
  const original = useQuery<CVOriginalSnapshot>({
    queryKey: ["cv-original", stageId],
    queryFn: () => candidateStageCvApi.original.get(stageId as number).then((r) => r.data),
    enabled: fromStage,
  });
  const pair =
    context ??
    (fromStage && original.isSuccess
      ? { candidateId: original.data.candidate_id, jobId: original.data.job_id, stageId: stageId ?? null }
      : null);

  if (pair) return <CvEditorSourcesPane {...pair} loaders={loaders} search={search} />;
  if (!fromStage) {
    return (
      <Note>
        To CV powstało bez rekrutacji w NEXUSIE, więc nie ma tu oryginału, notatek ani wymagań klienta.
      </Note>
    );
  }
  if (original.isError) {
    return (
      <Note>
        <p>Nie udało się wczytać źródeł tego CV.</p>
        <Button type="button" variant="outline" size="sm" onClick={() => void original.refetch()}>
          Ponów
        </Button>
      </Note>
    );
  }
  return <Note>Wczytywanie źródeł…</Note>;
}
