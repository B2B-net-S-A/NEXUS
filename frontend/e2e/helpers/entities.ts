/**
 * Zakładanie danych scenariusza przez API (stack E2E, `@stack`).
 *
 * Każdy scenariusz tworzy WŁASNEGO klienta, rekrutację i kandydata — żaden nie
 * zakłada, że w bazie istnieje rekord o konkretnym id (dawne `SAMPLE_JOB_ID = 1`).
 * Kontrakty endpointów (wymagane pola, statusy) sprawdzone w backend/app/api.
 */
import type { APIRequestContext } from "@playwright/test";
import { jsonOf, uniqueSuffix } from "./api";

export interface CreatedClient {
  id: number;
  name: string;
}

export interface CreatedJob {
  id: number;
  title: string;
  pipeline_template_id: number | null;
}

export interface CreatedCandidate {
  id: number;
  name: string;
  lastname: string;
  email: string;
}

export async function createClient(api: APIRequestContext): Promise<CreatedClient> {
  const name = `E2E Klient ${uniqueSuffix()}`;
  return jsonOf<CreatedClient>(
    await api.post("/api/clients", { data: { name, status: "active" } }),
    201,
    "POST /api/clients"
  );
}

export async function createJob(
  api: APIRequestContext,
  clientId: number,
  extra: Record<string, unknown> = {}
): Promise<CreatedJob> {
  const title = `E2E Rekrutacja ${uniqueSuffix()}`;
  return jsonOf<CreatedJob>(
    await api.post("/api/jobs", { data: { title, client_id: clientId, ...extra } }),
    201,
    "POST /api/jobs"
  );
}

export async function createCandidate(
  api: APIRequestContext,
  extra: Record<string, unknown> = {}
): Promise<CreatedCandidate> {
  const suffix = uniqueSuffix();
  const data = {
    name: "Ewa",
    lastname: `E2E${suffix}`,
    email: `e2e-${suffix}@example.com`,
    ...extra,
  };
  return jsonOf<CreatedCandidate>(
    await api.post("/api/candidates", { data }),
    201,
    "POST /api/candidates"
  );
}
