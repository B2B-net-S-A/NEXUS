/**
 * Gotowe CV tej osoby, które można wybrać jako CV firmowe rekrutacji zamiast
 * generować nowe (screening 09.10.2026, karta „CV do klienta” 12.10.2026).
 * Czyste funkcje — komponent tylko renderuje.
 *
 * Źródła są trzy:
 *  - CV etapu z INNEJ rekrutacji tej osoby — w wersji po poprawkach rekrutera
 *    (zatwierdzona, a bez niej szkic);
 *  - CV z generatora tej osoby (ta rekrutacja, „bez procesu”, a z innej
 *    rekrutacji tylko wtedy, gdy nie ma tam CV etapu — inaczej ta sama treść
 *    stałaby na liście dwa razy, raz bez poprawek);
 *  - pliki Word „…B2B…” z teczki kandydata (PDF-ów nie da się wczytać do
 *    edytora, więc ich tu nie ma).
 *
 * CV spoza generatora TEJ rekrutacji jest kopią odłączoną. Do 12.10.2026
 * klient z wymogiem zrzutu zgody RODO (dziś PKO BP) miał takie opcje
 * wyszarzone. Teraz kopia powstaje, pobranie czeka na zrzut — opcja niesie
 * zdanie, co się stanie ze zgodą (`note`).
 */

import {
  fileAddedLabel,
  formatFileDate,
  sortCandidateFiles,
  splitClientCvFiles,
  type CandidateFileListItem,
} from "@/lib/candidate-files";

export const CONSENT_AFTER_CHOICE_NOTE =
  "Klient wymaga zrzutu zgody kandydata — po wyborze dołącz go w karcie „CV do klienta”.";
export const CONSENT_CARRIED_NOTE = "Zrzut zgody przejdzie razem z CV (ten sam klient).";

export interface StageCvGeneratedSource {
  id: number;
  status: string;
  job_id?: number | null;
  client_name?: string | null;
  position?: string | null;
  language?: string | null;
  created_at?: string | null;
  created_by_name?: string | null;
  filename?: string | null;
}

export interface StageCvDocumentSource extends CandidateFileListItem {
  filename: string;
}

/** CV etapu tej osoby z innej rekrutacji (`GET …/cv/branded/sources`). */
export interface StageCvStageSource {
  job_id: number;
  stage_id: number;
  job_title?: string | null;
  reference_number?: string | null;
  client_name?: string | null;
  status: "draft" | "finalized" | string;
  version?: number | null;
  language?: string | null;
  updated_at?: string | null;
  updated_by_name?: string | null;
  consent_carried?: boolean;
}

export interface StageCvOption {
  kind: "stage" | "generated" | "document";
  /** `stage` — id rekrutacji źródłowej; pozostałe — id dokumentu. */
  id: number;
  /** Klucz Reacta i stan „w toku” (id różnych źródeł mogą się pokryć). */
  key: string;
  title: string;
  detail: string;
  /** Plakietka: „ta rekrutacja”, „zatwierdzone · wersja 2”…; pliki — `null`. */
  origin: string | null;
  /** Co stanie się ze zrzutem zgody (klient z wymogiem) — inaczej `null`. */
  note: string | null;
  /** `stage` — wiersz etapu, z którego da się podejrzeć treść. */
  previewStageId?: number;
}

export interface StageCvOptions {
  stages: StageCvOption[];
  generated: StageCvOption[];
  documents: StageCvOption[];
  total: number;
}

function createdAt(value: string | null | undefined): number {
  const time = Date.parse(value ?? "");
  return Number.isFinite(time) ? time : 0;
}

function isWord(filename: string | null | undefined): boolean {
  return (filename ?? "").trim().toLowerCase().endsWith(".docx");
}

export function buildStageCvOptions({
  stages,
  generated,
  documents,
  jobId,
  consentClient,
}: {
  stages?: readonly StageCvStageSource[] | undefined;
  generated: readonly StageCvGeneratedSource[] | undefined;
  documents: readonly StageCvDocumentSource[] | undefined;
  jobId: number;
  /** Klient rekrutacji wymaga zrzutu zgody RODO w CV. */
  consentClient: boolean;
}): StageCvOptions {
  const copyNote = consentClient ? CONSENT_AFTER_CHOICE_NOTE : null;

  // Kolejność z serwera: zatwierdzone przed szkicami, w obrębie — najnowsze.
  const stageRows = (stages ?? []).filter((row) => row.job_id !== jobId);
  const stageJobIds = new Set(stageRows.map((row) => row.job_id));
  const stageOptions = stageRows.map<StageCvOption>((row) => ({
    kind: "stage",
    id: row.job_id,
    key: `stage:${row.job_id}`,
    title: row.job_title?.trim() || row.reference_number?.trim() || `Rekrutacja #${row.job_id}`,
    detail: [
      row.client_name?.trim(),
      row.job_title?.trim() ? row.reference_number?.trim() : null,
      row.language ? row.language.toUpperCase() : null,
      formatFileDate(row.updated_at),
      row.updated_by_name?.trim(),
    ]
      .filter(Boolean)
      .join(" · "),
    origin:
      row.status === "finalized" ? `zatwierdzone · wersja ${row.version ?? 1}` : "szkic",
    note: consentClient
      ? row.consent_carried
        ? CONSENT_CARRIED_NOTE
        : CONSENT_AFTER_CHOICE_NOTE
      : null,
    previewStageId: row.stage_id,
  }));

  const sameJob = (row: StageCvGeneratedSource) => row.job_id === jobId;
  const generatedOptions = (generated ?? [])
    .filter(
      (row) =>
        row.status === "ready" && !(row.job_id != null && stageJobIds.has(row.job_id)),
    )
    .sort((a, b) => {
      if (sameJob(a) !== sameJob(b)) return sameJob(a) ? -1 : 1;
      const byDate = createdAt(b.created_at) - createdAt(a.created_at);
      return byDate !== 0 ? byDate : b.id - a.id;
    })
    .map<StageCvOption>((row) => {
      const own = sameJob(row);
      return {
        kind: "generated",
        id: row.id,
        key: `generated:${row.id}`,
        title: row.position?.trim() || row.filename?.trim() || `CV #${row.id}`,
        detail: [
          row.client_name?.trim(),
          row.language ? row.language.toUpperCase() : null,
          formatFileDate(row.created_at),
          row.created_by_name?.trim(),
        ]
          .filter(Boolean)
          .join(" · "),
        origin: own ? "ta rekrutacja" : row.job_id == null ? "bez rekrutacji" : "inna rekrutacja",
        // CV z generatora TEJ rekrutacji ma własną zgodę (dołączaną w generatorze).
        note: own ? null : copyNote,
      };
    });

  const documentOptions = splitClientCvFiles(sortCandidateFiles(documents ?? []))
    .client.filter((doc) => isWord(doc.filename))
    .map<StageCvOption>((doc) => ({
      kind: "document",
      id: doc.id,
      key: `document:${doc.id}`,
      title: doc.filename,
      detail: fileAddedLabel(doc),
      origin: null,
      note: copyNote,
    }));

  return {
    stages: stageOptions,
    generated: generatedOptions,
    documents: documentOptions,
    total: stageOptions.length + generatedOptions.length + documentOptions.length,
  };
}

/**
 * Gotowe CV, które karta „CV do klienta” podpowiada zamiast generacji:
 * CV etapu z innej rekrutacji (ma poprawki rekrutera), potem plik Word
 * z profilu, na końcu CV z generatora spoza tej rekrutacji. CV z generatora
 * TEJ rekrutacji nie jest „innym CV” — kartę obsługuje „Użyj tej wersji”.
 */
export function bestReadyCv(options: StageCvOptions): StageCvOption | null {
  return (
    options.stages[0] ??
    options.documents[0] ??
    options.generated.find((option) => option.origin !== "ta rekrutacja") ??
    null
  );
}

/** Ile gotowych CV spoza tej rekrutacji ma osoba (licznik „Pokaż wszystkie”). */
export function otherReadyCvCount(options: StageCvOptions): number {
  return (
    options.stages.length +
    options.documents.length +
    options.generated.filter((option) => option.origin !== "ta rekrutacja").length
  );
}
