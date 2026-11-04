/**
 * Nazwa rekrutacji, w której osoba już jest, jako tekst — jak nagłówek
 * rekrutacji: numer u klienta i tytuł dla rekrutera (16.10.2026). Dla etykiet,
 * zdań i nagłówków grup; wiersze używają `JobNameLabel`.
 *
 * Tylko ekrany wewnętrzne. `job_title` odpowiedzi to nazwa od klienta
 * i zostaje dla wszystkiego, co idzie do klienta (CV, plik, Cpro, maile).
 */
import { clientReferenceParts, jobDisplayTitle, type JobNames } from "@/lib/job-names";

/** Rekrutacja osoby z odpowiedzi kandydata (`job_title`, `job_working_title`, `job_client_reference`). */
export interface CandidateJobNameFields {
  job_id?: number | null;
  job_title?: string | null;
  job_working_title?: string | null;
  job_client_reference?: string | null;
}

export function candidateJobNames(row: CandidateJobNameFields): JobNames {
  return {
    id: row.job_id ?? null,
    title: row.job_title ?? null,
    working_title: row.job_working_title ?? null,
    client_reference: row.job_client_reference ?? null,
  };
}

/** „ZOB-2984 Senior AI Engineer · Java, LLM” — pierwszy numer i „+N” jak znacznik. */
export function jobNameText(job: JobNames): string {
  const [first, ...rest] = clientReferenceParts(job.client_reference);
  const title = jobDisplayTitle(job);
  if (!first) return title;
  return `${first}${rest.length > 0 ? ` +${rest.length}` : ""} ${title}`;
}
