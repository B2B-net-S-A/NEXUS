/**
 * „Praca w tle" rekrutacji — co automaty zrobiły BEZ człowieka
 * (backend: `GET /api/jobs/{id}/background-events` w `job_proposals.py`).
 *
 * Serwer oddaje rodzaj zdarzenia, liczby i kody; polskie zdanie dla AWARII
 * (`message`) przychodzi gotowe, pozostałe składamy tutaj — w jednym miejscu,
 * żeby okno „Historia i czat" i sekcja CV panelu osoby mówiły to samo.
 */

import api from "@/lib/api";
import { countPl } from "@/lib/plural-pl";

export type JobBackgroundEventKind =
  | "auto_full_review"
  | "auto_full_review_failed"
  | "new_cv_proposals"
  | "new_cv_proposals_failed"
  | "cv_auto_generate"
  | "cv_auto_generate_skipped"
  | "cv_auto_generate_failed";

export interface JobBackgroundEvent {
  id: number;
  /** `string` w unii: nowy rodzaj z backendu nie może wywrócić listy. */
  kind: JobBackgroundEventKind | (string & {});
  created_at: string | null;
  run_id?: string | null;
  proposals?: number | null;
  eligible?: number | null;
  count?: number | null;
  trigger?: string | null;
  /** Kod powodu (pominięcie albo awaria). */
  reason?: string | null;
  /** Gotowe polskie zdanie — serwer dokłada je przy awariach. */
  message?: string | null;
  /** Komunikat walidacji generatora (po polsku) przy pominięciu auto-CV. */
  detail?: string | null;
  /** `name: null` = rola bez odczytu kandydatów. */
  candidate?: { id: number; name: string | null } | null;
  generated_id?: number | null;
  document_status?: "processing" | "ready" | "failed" | "deleted" | (string & {}) | null;
}

export interface JobBackgroundEventsPage {
  job_id: number;
  items: JobBackgroundEvent[];
  limit: number;
}

/** Serwer przyjmuje najwyżej 100 i nie stronicuje — „Pokaż więcej" podnosi limit. */
export const BACKGROUND_EVENTS_STEP = 30;
export const BACKGROUND_EVENTS_MAX = 100;

export const jobBackgroundEventsQueryKey = (jobId: number, limit: number) =>
  ["job-background-events", jobId, limit] as const;

export const jobBackgroundEventsApi = {
  list: (jobId: number, limit: number = BACKGROUND_EVENTS_STEP) =>
    api
      .get<JobBackgroundEventsPage>(`/api/jobs/${jobId}/background-events`, {
        params: { limit },
      })
      .then((r) => r.data),
};

export type BackgroundEventTone = "neutral" | "skipped" | "failed";

export function backgroundEventTone(event: JobBackgroundEvent): BackgroundEventTone {
  if (event.kind.endsWith("_failed")) return "failed";
  if (event.kind === "cv_auto_generate" && event.document_status === "failed") return "failed";
  if (event.kind === "cv_auto_generate_skipped") return "skipped";
  return "neutral";
}

const SKIP_REASON_PL: Record<string, string> = {
  no_client: "rekrutacja nie ma przypisanego klienta",
  no_permission: "osoba, która przesunęła kartę, nie ma prawa generować CV",
  no_cv_document: "kandydat nie ma w profilu pliku CV",
  consent_screenshot_required: "reguła klienta wymaga zrzutu zgody RODO",
  client_rule_inputs_missing: "reguła klienta wymaga danych, których automat nie ma",
  generation_unavailable: "generator CV był niedostępny",
  // AI-06 (audyt 22.09 r2): powrót karty na „Zweryfikowany” z tym samym CV.
  already_generated:
    "CV z tego samego pliku już wygenerowano w tej rekrutacji — nowego nie tworzono",
};

/** Polski powód pominięcia auto-CV; nieznany kod nie udaje znanego. */
export function autoCvSkipReason(event: Pick<JobBackgroundEvent, "reason" | "detail">): string {
  const known = event.reason ? SKIP_REASON_PL[event.reason] : undefined;
  const detail = event.detail?.trim().replace(/[.\s]+$/, "");
  if (known) {
    // Walidacja generatora mówi DOKŁADNIE, czego brakuje — dopowiadamy ją.
    return detail && event.reason === "client_rule_inputs_missing" ? `${known} (${detail})` : known;
  }
  if (detail) return detail;
  return event.reason ? `powód: ${event.reason}` : "powód nieznany";
}

function personLabel(event: JobBackgroundEvent): string {
  if (!event.candidate) return "";
  return event.candidate.name?.trim() || `Kandydat #${event.candidate.id}`;
}

function withPerson(event: JobBackgroundEvent, sentence: string): string {
  const person = personLabel(event);
  return person ? `${person}: ${sentence}` : sentence;
}

/** Jedno polskie zdanie na zdarzenie. */
export function backgroundEventMessage(event: JobBackgroundEvent): string {
  switch (event.kind) {
    case "auto_full_review": {
      const proposals = event.proposals ?? 0;
      const head =
        proposals > 0
          ? `Automatyczny przegląd bazy: ${countPl(proposals, "nowa propozycja", "nowe propozycje", "nowych propozycji")}`
          : "Automatyczny przegląd bazy: bez nowych propozycji";
      return event.eligible != null
        ? `${head} (wymagania spełnia ${countPl(event.eligible, "osoba", "osoby", "osób")}).`
        : `${head}.`;
    }
    case "new_cv_proposals": {
      const source =
        event.trigger === "job_publish" ? "Po publikacji rekrutacji" : "Nowe CV w bazie";
      return `${source}: ${countPl(event.count ?? 0, "propozycja", "propozycje", "propozycji")}.`;
    }
    case "cv_auto_generate": {
      const status = event.document_status;
      const sentence =
        status === "ready"
          ? "CV wygenerowane automatycznie — sprawdź przed wysyłką."
          : status === "failed"
            ? "automatyczna generacja CV nie powiodła się."
            : status === "deleted"
              ? "CV wygenerowane automatycznie zostało usunięte."
              : "CV generuje się automatycznie po weryfikacji…";
      return withPerson(event, sentence);
    }
    case "cv_auto_generate_skipped":
      return withPerson(
        event,
        `CV nie zostało wygenerowane automatycznie: ${autoCvSkipReason(event)}.`,
      );
    case "cv_auto_generate_failed":
      return withPerson(
        event,
        `automatyczna generacja CV nie powiodła się. ${event.message ?? ""}`.trim(),
      );
    case "auto_full_review_failed":
      return `Automatyczny przegląd bazy nie powiódł się. ${event.message ?? ""}`.trim();
    case "new_cv_proposals_failed":
      return `Propozycje z nowych CV nie powstały. ${event.message ?? ""}`.trim();
    default:
      return event.message?.trim() || "Zdarzenie automatu.";
  }
}

/**
 * Ostatnie pominięcie auto-CV tej osoby, o ile PÓŹNIEJ automat nie zadziałał.
 * Lista jest od najnowszego, więc pierwsze zdarzenie auto-CV osoby rozstrzyga:
 * stary powód nie może wisieć nad dokumentem, który już powstał.
 */
export function latestAutoCvSkip(
  events: readonly JobBackgroundEvent[],
  candidateId: number,
): JobBackgroundEvent | null {
  const latest = events.find(
    (event) => event.candidate?.id === candidateId && event.kind.startsWith("cv_auto_generate"),
  );
  return latest?.kind === "cv_auto_generate_skipped" ? latest : null;
}
