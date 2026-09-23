/**
 * Publiczne API strony kariery — typy i adresy API (odczyt serwerowy: `./server`).
 *
 * Kontrakt: `/api/public/career/*` (bez logowania). Odpowiedź NIGDY nie niesie
 * nazwy klienta ani stawek — strona renderuje wyłącznie to, co tu przyjdzie.
 * Odczyt idzie z serwera (RSC) po `INTERNAL_API_URL` (sieć compose), a wysyłka
 * formularza z przeglądarki po `NEXT_PUBLIC_API_URL`.
 */

export type RemotePolicy = "remote" | "hybrid" | "onsite";
export type WorkMode = "any" | "remote" | "hybrid" | "onsite";

export interface CareerRecruiter {
  first_name: string;
  slug: string | null;
}

export interface CareerJobParams {
  city: string | null;
  remote_policy: RemotePolicy | null;
  onsite_days_per_week: number | null;
  seniority: string | null;
  contract: string | null;
  start: string | null;
  duration: string | null;
}

export interface CareerJob {
  slug: string;
  title: string;
  subtitle: string | null;
  about: string | null;
  must: { name: string; note: string | null }[];
  nice: string[];
  params: CareerJobParams | null;
  show: { must: boolean; nice: boolean; params: boolean; process: boolean } | null;
}

export interface CareerJobResponse {
  status: "open" | "closed";
  recruiter: CareerRecruiter;
  job: CareerJob;
}

export interface CareerRecruiterJob {
  slug: string;
  title: string;
  city: string | null;
  remote_policy: RemotePolicy | null;
}

export interface CareerRecruiterResponse {
  recruiter: { first_name: string; slug: string };
  jobs: CareerRecruiterJob[];
}

/** Adres API dla odczytu z serwera (RSC, grafiki OG). */
export function serverApiBase(): string {
  return (
    process.env.INTERNAL_API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://localhost:8000"
  ).replace(/\/+$/, "");
}

/** Adres API dla wysyłki z przeglądarki. */
export function browserApiBase(): string {
  return (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");
}

export type FetchResult<T> =
  | { ok: true; data: T }
  | { ok: false; notFound: boolean };
