/**
 * Słownik powodów odrzucenia dla jednej rekrutacji.
 *
 * `RejectionV2` przyjmuje `{ id, label, applies_to }`, a backend zwraca
 * `{ id, name, category }` z szablonu procesu. Mapowanie i awaryjny fallback na
 * szablon domyślny żyły dotąd wyłącznie w efekcie wewnątrz `KanbanBoardV2`.
 * Dok „Decyzja" kroku 07 otwiera TEN SAM modal, więc potrzebuje tej samej
 * listy — a druga kopia mapowania rozjechałaby się przy pierwszej zmianie
 * kształtu (np. gdyby `applies_to` przestało być jednoelementowe).
 *
 * Fallback jest istotny: joby zaimportowane z Traffita nie mają
 * `pipeline_template_id`, więc bez niego lista powodów byłaby pusta, a przycisk
 * „Potwierdź" w modalu trwale zablokowany.
 */

import api, { pipelineTemplatesApi, type RejectionReasonDef } from "@/lib/api";

export interface RejectionReasonOption {
  id: string;
  label: string;
  applies_to: ("rejected" | "withdrawn")[];
  /**
   * Czy ten powód jest werdyktem o OSOBIE — tylko takie blokują ponowne
   * zgłoszenie kandydata do hiring managera, który go odrzucił. Karta rozmowy
   * pokazuje to obok wyboru, żeby „blokuje ponowne propozycje" było
   * odczytem stanu, a nie osobnym przełącznikiem bez pokrycia w backendzie.
   */
  disqualifies_person: boolean;
}

export function mapRejectionReasons(
  rows: readonly RejectionReasonDef[] | null | undefined,
): RejectionReasonOption[] {
  return (rows ?? [])
    .filter((r) => r.category === "rejected" || r.category === "withdrawn")
    .map((r) => ({
      id: String(r.id),
      label: r.name,
      applies_to: [r.category as "rejected" | "withdrawn"],
      disqualifies_person: Boolean(r.disqualifies_person),
    }));
}

/** Powody dla tej rekrutacji — z jej szablonu, awaryjnie z domyślnego. */
export async function loadJobRejectionReasons(
  jobId: number,
): Promise<RejectionReasonOption[]> {
  const job = await api.get(`/api/jobs/${jobId}`);
  const templateId: number | null | undefined = job.data?.pipeline_template_id;

  if (templateId) {
    const detail = await pipelineTemplatesApi.get(templateId);
    const mapped = mapRejectionReasons(detail.data.rejection_reasons);
    if (mapped.length > 0) return mapped;
  }

  const templates = await pipelineTemplatesApi.list();
  const fallback = templates.data.find((t) => t.is_default);
  if (!fallback) return [];
  const detail = await pipelineTemplatesApi.get(fallback.id);
  return mapRejectionReasons(detail.data.rejection_reasons);
}
