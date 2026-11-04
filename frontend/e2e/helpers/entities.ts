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

/** Profil Championa, który przechodzi bramkę przekazania do searchu. */
const READY_CHAMPION = {
  project: { about: "Platforma płatności B2B dla banku — rozwój usług." },
  screening_questions: [
    {
      id: "q1",
      question: "Doświadczenie z Pythonem?",
      deal_breaker: "Brak komercyjnego projektu w Pythonie.",
    },
    {
      id: "q2",
      question: "Doświadczenie z Postgres?",
      deal_breaker: "Nie pracował z relacyjną bazą.",
    },
  ],
  stack: { rows: [{ words: ["Python"], level: "must" }], critical: [] },
  basics: { rate_value: 150, work_mode: "zdalnie" },
  search: { requirements: [["Python"]] },
};

const RECRUITER_EMAIL = process.env.E2E_RECRUITER_EMAIL || "e2e-recruiter@example.com";

let cachedCategoryId: number | null = null;
let cachedRecruiterId: number | null = null;

async function firstCompetenceCategoryId(api: APIRequestContext): Promise<number> {
  if (cachedCategoryId !== null) return cachedCategoryId;
  const categories = await jsonOf<Array<{ id: number }>>(
    await api.get("/api/competence-categories"),
    200,
    "GET /api/competence-categories"
  );
  if (!categories.length) throw new Error("Brak kategorii kompetencji na stacku E2E");
  cachedCategoryId = categories[0].id;
  return cachedCategoryId;
}

async function e2eRecruiterId(api: APIRequestContext): Promise<number> {
  if (cachedRecruiterId !== null) return cachedRecruiterId;
  const users = await jsonOf<Array<{ id: number; email: string }>>(
    await api.get("/api/users", { params: { roles: "recruiter", q: RECRUITER_EMAIL } }),
    200,
    "GET /api/users?roles=recruiter"
  );
  const recruiter = users.find((user) => user.email === RECRUITER_EMAIL);
  if (!recruiter) throw new Error(`Brak konta rekrutera E2E (${RECRUITER_EMAIL})`);
  cachedRecruiterId = recruiter.id;
  return cachedRecruiterId;
}

/**
 * Rekrutacja bez szkiców (04.10.2026): `POST /api/jobs` zakłada rekrutację od
 * razu przekazaną do searchu i opublikowaną — żądanie niesie komplet (Profil
 * Championa, decyzję o hiring managerze i terminie, kategorię, przekazanie).
 * `extra` nadpisuje pola najwyższego poziomu.
 */
export async function createJob(
  api: APIRequestContext,
  clientId: number,
  extra: Record<string, unknown> = {}
): Promise<CreatedJob> {
  const title = `E2E Rekrutacja ${uniqueSuffix()}`;
  const data = {
    title,
    client_id: clientId,
    auto_suggest_cc: false,
    competence_category_id: await firstCompetenceCategoryId(api),
    remote_policy: "remote",
    rate_budget_hourly: 150,
    headcount: 1,
    deadline_not_provided: true,
    hiring_manager: { not_provided: true },
    champion_profile: READY_CHAMPION,
    handoff: { assignment_mode: "manual", recruiter_id: await e2eRecruiterId(api) },
    ...extra,
  };
  return jsonOf<CreatedJob>(await api.post("/api/jobs", { data }), 201, "POST /api/jobs");
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
