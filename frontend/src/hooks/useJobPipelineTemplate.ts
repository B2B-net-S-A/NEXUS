"use client";

/**
 * Fakty rekrutacji, których potrzebuje KAŻDY widok ruszający etapy: słownik
 * powodów odrzucenia, etapy ze scorecardem, nazwa szablonu, budżet PLN/h
 * i prawo zapisu stawki do klienta.
 *
 * Wyniesione z `KanbanBoardV2` bez zmiany zachowania (te same trasy, ta sama
 * kolejność, ten sam fallback), żeby tablica i widok „rekrutacja = jedna
 * tabela" nie hodowały dwóch kopii reguły „skąd wziąć powody odrzucenia".
 *
 * `job` — strona rekrutacji ma już odpowiedź `GET /api/jobs/{id}`; podana tu
 * oszczędza drugie zapytanie. Tablica jej nie podaje i pyta sama, jak dotąd.
 */

import { useEffect, useState } from "react";

import api, { pipelineTemplatesApi, type RejectionReasonDef } from "@/lib/api";
import {
  jobBudgetHourly as resolveJobBudgetHourly,
  type JobBudgetSource,
} from "@/lib/job-budget";
import type { PipelineRejectionReasonOption } from "@/hooks/usePipelineMove";

interface JobFacts extends JobBudgetSource {
  pipeline_template_id?: number | null;
  can_write_client_rate?: boolean | null;
}

export interface UseJobPipelineTemplateOptions {
  /** Już pobrana rekrutacja. `undefined` = hook pyta `GET /api/jobs/{id}` sam. */
  job?: JobFacts | null;
  /** `false` = nic nie pobieraj (widok, który tych faktów nie potrzebuje). */
  enabled?: boolean;
}

export interface JobPipelineTemplateFacts {
  rejectionReasons: PipelineRejectionReasonOption[];
  stagesWithScorecard: Set<number>;
  templateName: string | null;
  budgetHourly: number | null;
  canWriteClientRate: boolean;
}

const EMPTY_STAGES: Set<number> = new Set();

function mapReasons(reasons: readonly RejectionReasonDef[]): PipelineRejectionReasonOption[] {
  return reasons.map((r) => ({
    // Identyfikator jedzie do API bez zmian (liczba z szablonu); typ opcji
    // okna odrzucenia jest historycznie tekstowy.
    id: r.id as unknown as string,
    label: r.name,
    applies_to: [r.category as "rejected" | "withdrawn"],
  }));
}

export function useJobPipelineTemplate(
  jobId: number,
  { job, enabled = true }: UseJobPipelineTemplateOptions = {},
): JobPipelineTemplateFacts {
  const [rejectionReasons, setRejectionReasons] = useState<PipelineRejectionReasonOption[]>([]);
  const [stagesWithScorecard, setStagesWithScorecard] = useState<Set<number>>(EMPTY_STAGES);
  const [templateName, setTemplateName] = useState<string | null>(null);
  const [budgetHourly, setBudgetHourly] = useState<number | null>(null);
  const [canWriteClientRate, setCanWriteClientRate] = useState(false);

  // Podana rekrutacja: efekt zależy od WARTOŚCI, nie od tożsamości obiektu —
  // react-query oddaje nową referencję przy każdym odświeżeniu w tle.
  const jobProvided = job !== undefined;
  const providedTemplateId = job?.pipeline_template_id ?? null;
  const providedBudget = job ? resolveJobBudgetHourly(job) : null;
  const providedCanWriteRate = job?.can_write_client_rate === true;
  const jobReady = !jobProvided || job != null;

  useEffect(() => {
    if (!enabled || !jobReady) return;
    let cancelled = false;
    (async () => {
      try {
        let tid: number | null | undefined;
        if (jobProvided) {
          tid = providedTemplateId;
          setBudgetHourly(providedBudget);
          setCanWriteClientRate(providedCanWriteRate);
        } else {
          const jobRes = await api.get(`/api/jobs/${jobId}`);
          if (cancelled) return;
          setBudgetHourly(resolveJobBudgetHourly(jobRes.data));
          setCanWriteClientRate(jobRes.data?.can_write_client_rate === true);
          tid = jobRes.data?.pipeline_template_id;
        }

        let reasons: PipelineRejectionReasonOption[] = [];
        if (tid) {
          const detail = await pipelineTemplatesApi.get(tid);
          if (cancelled) return;
          reasons = mapReasons(detail.data.rejection_reasons ?? []);
          // Nazwa szablonu do nagłówka lewej kolumny — z odpowiedzi, która i tak
          // tu leci po rejection-reasons.
          const tname = (detail.data as { name?: string | null }).name;
          setTemplateName(typeof tname === "string" && tname.trim() ? tname : null);
          const withScorecard = new Set<number>();
          for (const stage of detail.data.stages ?? []) {
            const s = stage as { id: number; scorecard_schema?: { questions?: unknown } | null };
            const schema = s.scorecard_schema;
            if (schema && Array.isArray(schema.questions) && schema.questions.length > 0) {
              withScorecard.add(s.id);
            }
          }
          setStagesWithScorecard(withScorecard);
        }

        // Legacy joby (np. import z Traffit) nie mają pipeline_template_id, więc
        // ich szablon nie dostarcza powodów odrzucenia. Bez fallbacku dialog
        // "Odrzuć kandydata" miałby pustą listę powodów, a przycisk "Potwierdź"
        // byłby trwale zablokowany. Dociągamy powody z szablonu domyślnego, aby
        // zachować kontrolowany słownik (raporty lejka) zamiast wolnego tekstu.
        if (reasons.length === 0) {
          try {
            const templates = await pipelineTemplatesApi.list();
            const def = templates.data.find((t) => t.is_default);
            if (def) {
              const defDetail = await pipelineTemplatesApi.get(def.id);
              reasons = mapReasons(defDetail.data.rejection_reasons ?? []);
            }
          } catch (e) {
            console.error("Default rejection-reasons fallback failed", e);
          }
        }
        if (!cancelled) setRejectionReasons(reasons);
      } catch (e) {
        console.error("Pipeline template load failed", e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    jobId,
    enabled,
    jobReady,
    jobProvided,
    providedTemplateId,
    providedBudget,
    providedCanWriteRate,
  ]);

  return { rejectionReasons, stagesWithScorecard, templateName, budgetHourly, canWriteClientRate };
}
