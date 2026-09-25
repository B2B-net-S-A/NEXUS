// `/jobs/new` → „Ogłoszenie na portalach” (RocketJobs, JustJoin.IT).
//
// Kolejność z kontraktu (`docs/job-boards-rocketjobs-contract.md`), wołana PO
// utworzeniu i opublikowaniu rekrutacji: opis publiczny → zatwierdzenie →
// link aplikacyjny `/r/<slug>` → publikacja na każdym zaznaczonym portalu.
// Istniejące trasy, więc bramki uprawnień i kontrola opisu (nazwa klienta,
// kwoty, kontakty) zostają na serwerze. Moduł nie zna Reacta — strona
// dostaje wynik i decyduje o toaście i przejściu do rekrutacji.

import api from "@/lib/api";
import { careerLinksApi, findingsFromApproveError } from "@/lib/api/careerLinks";
import {
  EMPTY_LISTING_OPTIONS,
  publishToPortal,
  validateListingOptions,
  type JobPortal,
  type PortalListingOptions,
  type PublicDraftRequest,
} from "@/lib/api/jobPortals";
import { apiErrorMessage } from "@/lib/api-error";
import {
  buildChampionPayload,
  jobTitleFor,
  parseOnsiteDays,
  type IntakeForm,
} from "@/lib/job-request-intake";

export interface PortalAdDraft {
  publicTitle: string;
  subtitle: string;
  about: string;
}

export interface NewJobPortalPlan {
  portals: JobPortal[];
  /** `null` = DL jeszcze nie kliknął „Przygotuj ogłoszenie”. */
  draft: PortalAdDraft | null;
  options: PortalListingOptions;
}

const WORKPLACE: Record<string, string> = { remote: "remote", hybrid: "hybrid", onsite: "office" };

/**
 * Parametry ogłoszenia z pól rekrutacji. Kategoria zawsze pusta (słownik
 * portalu), widełki zawsze puste (decyzja 25.09.2026: nigdy z budżetu).
 */
export function listingDefaultsFromForm(form: IntakeForm): PortalListingOptions {
  const workplace = form.remotePolicy ? WORKPLACE[form.remotePolicy] : null;
  return {
    ...EMPTY_LISTING_OPTIONS,
    // Lustro `jjit_payload.default_options`: bez wskazania pracy na część etatu = pełny etat.
    working_time: "full_time",
    workplace_type: workplace,
    office_days: workplace === "hybrid" ? parseOnsiteDays(form.onsiteDays) : null,
    city: form.city.trim() || null,
  };
}

/** Ciało `POST /api/job-intake/public-draft` z tego, co strona już ma. */
export function publicDraftRequest(
  form: IntakeForm,
  opts: { clientId: number | null; requestText: string },
): PublicDraftRequest {
  const remote = form.remotePolicy || null;
  return {
    title: form.title.trim() || jobTitleFor(form),
    client_id: opts.clientId,
    description: opts.requestText.trim() || null,
    must_skills: form.must,
    nice_skills: form.nice,
    location: remote === "remote" ? null : form.city.trim() || null,
    remote_policy: remote,
    onsite_days_per_week: remote === "remote" ? null : parseOnsiteDays(form.onsiteDays),
    champion_profile: buildChampionPayload(form),
  };
}

/**
 * Co blokuje „Utwórz i przekaż do searchu”, gdy DL zaznaczył portale.
 * `null` = nic (także gdy żaden portal nie jest zaznaczony).
 */
export function portalPlanBlocker(plan: NewJobPortalPlan): string | null {
  if (plan.portals.length === 0) return null;
  if (!plan.draft) return "Kliknij „Przygotuj ogłoszenie” albo odznacz portale.";
  if (!plan.draft.about.trim()) return "Ogłoszenie nie ma opisu — uzupełnij „O projekcie”.";
  const problems = new Set<string>();
  for (const portal of plan.portals) {
    for (const problem of validateListingOptions(plan.options, { board: portal })) problems.add(problem);
  }
  return problems.size > 0 ? [...problems].join(" ") : null;
}

export interface PortalPublishDeps {
  saveProfile: (jobId: number, draft: PortalAdDraft) => Promise<unknown>;
  approveProfile: (jobId: number) => Promise<unknown>;
  createLink: (jobId: number) => Promise<unknown>;
  publish: (jobId: number, portal: JobPortal, options: PortalListingOptions) => Promise<unknown>;
}

export const DEFAULT_PORTAL_PUBLISH_DEPS: PortalPublishDeps = {
  // Kontrakt: PUT tylko z trzema polami — sekcje i widoczność zostają domyślne.
  saveProfile: (jobId, draft) =>
    api.put(`/api/jobs/${jobId}/public-profile`, {
      public_title: draft.publicTitle.trim() || null,
      subtitle: draft.subtitle.trim() || null,
      about: draft.about.trim() || null,
    }),
  approveProfile: (jobId) => careerLinksApi.approvePublicProfile(jobId),
  // Rekrutacja jest świeża, więc aktywnego linku jeszcze nie ma — tworzymy
  // go bez sprawdzania (backend i tak nie zwraca 409 dla duplikatu).
  createLink: (jobId) => careerLinksApi.createInviteLink({ job_id: jobId, expires_in_days: null }),
  publish: (jobId, portal, options) => publishToPortal(jobId, portal, options),
};

export type PortalPublishOutcome =
  | { ok: true; published: JobPortal[] }
  | { ok: false; published: JobPortal[]; message: string };

/**
 * Wykonuje kolejność z kontraktu. Awaria opisu, zatwierdzenia albo linku
 * zatrzymuje całość (bez nich portal nie ma czego pokazać ani dokąd prowadzić).
 * Portale idą po kolei; awaria jednego nie blokuje następnego.
 */
export async function publishNewJobToPortals(
  jobId: number,
  plan: NewJobPortalPlan,
  labels: Partial<Record<JobPortal, string>>,
  deps: PortalPublishDeps = DEFAULT_PORTAL_PUBLISH_DEPS,
): Promise<PortalPublishOutcome> {
  if (plan.portals.length === 0) return { ok: true, published: [] };
  if (!plan.draft) {
    return { ok: false, published: [], message: "ogłoszenie nie zostało przygotowane" };
  }
  try {
    await deps.saveProfile(jobId, plan.draft);
  } catch (e) {
    return { ok: false, published: [], message: `nie zapisano opisu publicznego: ${apiErrorMessage(e, "błąd zapisu")}` };
  }
  try {
    await deps.approveProfile(jobId);
  } catch (e) {
    const findings = findingsFromApproveError(e);
    const message = findings?.length
      ? `opis publiczny ma uwagi kontroli: ${findings.map((f) => f.message).join(" ")}`
      : `nie zatwierdzono opisu publicznego: ${apiErrorMessage(e, "błąd")}`;
    return { ok: false, published: [], message };
  }
  try {
    await deps.createLink(jobId);
  } catch (e) {
    return { ok: false, published: [], message: `nie utworzono linku aplikacyjnego: ${apiErrorMessage(e, "błąd")}` };
  }
  const published: JobPortal[] = [];
  const failures: string[] = [];
  for (const portal of plan.portals) {
    try {
      await deps.publish(jobId, portal, plan.options);
      published.push(portal);
    } catch (e) {
      failures.push(`${labels[portal] ?? portal}: ${apiErrorMessage(e, "błąd publikacji")}`);
    }
  }
  if (failures.length > 0) return { ok: false, published, message: failures.join(" · ") };
  return { ok: true, published };
}
