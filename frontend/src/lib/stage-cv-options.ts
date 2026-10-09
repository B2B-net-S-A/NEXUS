/**
 * Gotowe CV z profilu kandydata, które można wybrać jako CV firmowe rekrutacji
 * (screening, 09.10.2026). Czyste funkcje — komponent tylko renderuje.
 *
 * Źródła są dwa i oba profil już pokazuje w grupie „CV dla klientów”:
 *  - CV z generatora tej osoby (także z innych rekrutacji i „bez procesu”),
 *  - pliki Word „…B2B…” z teczki kandydata (PDF-ów nie da się wczytać do
 *    edytora, więc ich tu nie ma).
 *
 * CV spoza generatora TEJ rekrutacji jest kopią odłączoną: nie da się do niej
 * dołączyć zrzutu zgody RODO. Klient, który go wymaga (dziś PKO BP), dostaje
 * takie opcje wyszarzone ze zdaniem, co zrobić — serwer i tak odmawia (422).
 */

import {
  fileAddedLabel,
  formatFileDate,
  sortCandidateFiles,
  splitClientCvFiles,
  type CandidateFileListItem,
} from "@/lib/candidate-files";

export const CONSENT_CLIENT_REASON =
  "Klient tej rekrutacji wymaga zrzutu zgody kandydata w CV — wygeneruj CV w generatorze.";

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

export interface StageCvOption {
  kind: "generated" | "document";
  id: number;
  /** Klucz Reacta i stan „w toku” (id generatora i pliku mogą się pokryć). */
  key: string;
  title: string;
  detail: string;
  /** „ta rekrutacja” / „inna rekrutacja” / „bez rekrutacji”; pliki — `null`. */
  origin: string | null;
  disabledReason: string | null;
}

export interface StageCvOptions {
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
  generated,
  documents,
  jobId,
  consentClient,
}: {
  generated: readonly StageCvGeneratedSource[] | undefined;
  documents: readonly StageCvDocumentSource[] | undefined;
  jobId: number;
  /** Klient rekrutacji wymaga zrzutu zgody RODO w CV. */
  consentClient: boolean;
}): StageCvOptions {
  const ready = (generated ?? []).filter((row) => row.status === "ready");
  const sameJob = (row: StageCvGeneratedSource) => row.job_id === jobId;
  const generatedOptions = [...ready]
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
        disabledReason: !own && consentClient ? CONSENT_CLIENT_REASON : null,
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
      disabledReason: consentClient ? CONSENT_CLIENT_REASON : null,
    }));

  return {
    generated: generatedOptions,
    documents: documentOptions,
    total: generatedOptions.length + documentOptions.length,
  };
}
