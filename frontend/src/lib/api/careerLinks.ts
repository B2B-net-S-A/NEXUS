// Kariera Dynaminds — okno „Udostępnij rekrutację" w NEXUSIE.
//
// Typy są lustrem kontraktu backendu (`/api/invite-links`, `/api/me/career-link`,
// `/api/jobs/{id}/public-profile`). Klucze zapytań są EKSPORTOWANYMI funkcjami:
// harness `/preview/career-share` zasiewa cache tymi samymi funkcjami, więc
// zmiana klucza w hooku nie może się rozjechać z zasiewem (niezasiany klucz =
// zapytanie → 401 → przerzut na /login).

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";

// ── Typy ─────────────────────────────────────────────────────────────────

export type InviteLinkStatus = "active" | "used" | "revoked" | "expired";

export interface InviteLink {
  token: string;
  /** = `public_url` (backend ustawia oba). */
  url: string;
  public_url?: string | null;
  kind?: "job" | "recruiter";
  slug?: string | null;
  job: { id: number; title: string } | null;
  label: string | null;
  /** `null` = ważny do zamknięcia rekrutacji. */
  expires_at: string | null;
  revoked: boolean;
  use_count: number;
  visit_count?: number;
  last_used_at: string | null;
  created_at: string;
  status: InviteLinkStatus;
}

export type ExpiryChoice = "none" | "7" | "14" | "30" | "90";

export interface CreateInviteLinkInput {
  job_id: number;
  label?: string;
  /** `null` = bez terminu (do zamknięcia rekrutacji). */
  expires_in_days: 7 | 14 | 30 | 90 | null;
}

export type PublicProfileStatus = "none" | "draft" | "approved";

export type FindingCode = "client_name" | "money" | "contact" | "person_name";

export interface PublicProfileFinding {
  code: FindingCode | string;
  message: string;
  excerpt: string | null;
}

export interface PublicProfileSections {
  must: boolean;
  nice: boolean;
  params: boolean;
  process: boolean;
}

export interface PublicJobParams {
  city: string | null;
  remote_policy: "remote" | "hybrid" | "onsite" | null;
  onsite_days_per_week: number | null;
  seniority: string | null;
  contract: string | null;
  start: string | null;
  duration: string | null;
}

export interface PublicJobPreview {
  slug: string;
  title: string;
  subtitle: string | null;
  about: string | null;
  must: { name: string; note: string | null }[];
  nice: string[];
  params: PublicJobParams | null;
  show: PublicProfileSections;
}

export interface JobPublicProfile {
  job_id: number;
  status: PublicProfileStatus;
  subtitle: string | null;
  about: string | null;
  sections: PublicProfileSections;
  show_on_recruiter_page: boolean;
  approved_at: string | null;
  approved_by_name: string | null;
  findings: PublicProfileFinding[];
  preview: PublicJobPreview | null;
}

export interface JobPublicProfileInput {
  subtitle: string | null;
  about: string | null;
  sections: PublicProfileSections;
  show_on_recruiter_page: boolean;
}

export interface PublicProfileDraft {
  subtitle: string;
  about: string;
}

export interface CareerLinkJob {
  job_id: number;
  title: string;
  profile_status: PublicProfileStatus;
  show_on_recruiter_page: boolean;
  has_link: boolean;
}

export interface CareerLinkState {
  link: {
    slug: string;
    public_url: string;
    created_at: string;
    visit_count: number | null;
  } | null;
  stats: {
    days: number;
    applications: number | null;
    new_candidates: number | null;
  } | null;
  suggested_slug: string | null;
  jobs: CareerLinkJob[];
}

export interface SlugAvailability {
  available: boolean;
  reason: string | null;
}

export interface PublishedJobLite {
  id: number;
  title: string;
  status?: string;
}

// ── Klucze ───────────────────────────────────────────────────────────────

export const careerLinkQueryKey = () => ["career-link", "me"] as const;
export const jobPublicProfileQueryKey = (jobId: number) =>
  ["job-public-profile", jobId] as const;
export const inviteLinksQueryKey = () => ["invite-links", "mine"] as const;
export const shareablePublishedJobsQueryKey = () =>
  ["career-share", "published-jobs"] as const;
export const slugAvailabilityQueryKey = (slug: string) =>
  ["career-link", "slug-available", slug] as const;

// ── Normalizacja (API bywa owinięte w {items}) ──────────────────────────

function asArray<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  const items = (data as { items?: unknown } | null)?.items;
  return Array.isArray(items) ? (items as T[]) : [];
}

const DEFAULT_SECTIONS: PublicProfileSections = {
  must: true,
  nice: true,
  params: true,
  process: true,
};

/** Profil z brakującymi polami nie może wywrócić formularza. */
export function normalizePublicProfile(
  jobId: number,
  raw: Partial<JobPublicProfile> | null | undefined,
): JobPublicProfile {
  const r = raw ?? {};
  return {
    job_id: typeof r.job_id === "number" ? r.job_id : jobId,
    status:
      r.status === "draft" || r.status === "approved" ? r.status : "none",
    subtitle: typeof r.subtitle === "string" ? r.subtitle : null,
    about: typeof r.about === "string" ? r.about : null,
    sections: { ...DEFAULT_SECTIONS, ...(r.sections ?? {}) },
    show_on_recruiter_page: r.show_on_recruiter_page ?? true,
    approved_at: r.approved_at ?? null,
    approved_by_name: r.approved_by_name ?? null,
    findings: Array.isArray(r.findings) ? r.findings : [],
    preview: r.preview ?? null,
  };
}

// ── Klient ───────────────────────────────────────────────────────────────

export const careerLinksApi = {
  listPublishedJobs: async (): Promise<PublishedJobLite[]> => {
    const res = await api.get("/api/jobs", {
      params: { status: "published", page_size: 100 },
    });
    return asArray<PublishedJobLite>(res.data).filter(
      (j) => !j.status || j.status === "published",
    );
  },
  listInviteLinks: async (): Promise<InviteLink[]> => {
    const res = await api.get("/api/invite-links", { params: { mine: true } });
    return asArray<InviteLink>(res.data);
  },
  createInviteLink: async (input: CreateInviteLinkInput): Promise<InviteLink> => {
    const res = await api.post("/api/invite-links", input);
    return res.data as InviteLink;
  },
  revokeInviteLink: async (token: string): Promise<void> => {
    await api.post(`/api/invite-links/${token}/revoke`);
  },
  getCareerLink: async (): Promise<CareerLinkState> => {
    const res = await api.get("/api/me/career-link");
    const d = (res.data ?? {}) as Partial<CareerLinkState>;
    return {
      link: d.link ?? null,
      stats: d.stats ?? null,
      suggested_slug: d.suggested_slug ?? null,
      jobs: Array.isArray(d.jobs) ? d.jobs : [],
    };
  },
  saveCareerLink: async (slug: string): Promise<void> => {
    await api.put("/api/me/career-link", { slug });
  },
  disableCareerLink: async (): Promise<void> => {
    await api.delete("/api/me/career-link");
  },
  checkSlug: async (slug: string): Promise<SlugAvailability> => {
    const res = await api.get("/api/me/career-link/slug-available", {
      params: { slug },
    });
    const d = (res.data ?? {}) as Partial<SlugAvailability>;
    return { available: d.available === true, reason: d.reason ?? null };
  },
  setVisibility: async (jobId: number, show: boolean): Promise<void> => {
    await api.put(`/api/jobs/${jobId}/public-profile/visibility`, {
      show_on_recruiter_page: show,
    });
  },
  getPublicProfile: async (jobId: number): Promise<JobPublicProfile> => {
    const res = await api.get(`/api/jobs/${jobId}/public-profile`);
    return normalizePublicProfile(jobId, res.data);
  },
  savePublicProfile: async (
    jobId: number,
    input: JobPublicProfileInput,
  ): Promise<JobPublicProfile> => {
    const res = await api.put(`/api/jobs/${jobId}/public-profile`, input);
    return normalizePublicProfile(jobId, res.data);
  },
  draftPublicProfile: async (jobId: number): Promise<PublicProfileDraft> => {
    const res = await api.post(`/api/jobs/${jobId}/public-profile/draft`);
    const d = (res.data ?? {}) as Partial<PublicProfileDraft>;
    return { subtitle: d.subtitle ?? "", about: d.about ?? "" };
  },
  approvePublicProfile: async (jobId: number): Promise<JobPublicProfile> => {
    const res = await api.post(`/api/jobs/${jobId}/public-profile/approve`);
    return normalizePublicProfile(jobId, res.data);
  },
};

/**
 * Znaleziska z odmowy zatwierdzenia (422 `PUBLIC_PROFILE_FINDINGS`) albo
 * `null`, gdy błąd jest innego rodzaju.
 */
export function findingsFromApproveError(
  error: unknown,
): PublicProfileFinding[] | null {
  const response = (error as { response?: { status?: unknown; data?: unknown } })
    ?.response;
  if (response?.status !== 422) return null;
  const detail = (response.data as { detail?: unknown } | null)?.detail;
  if (!detail || typeof detail !== "object" || Array.isArray(detail)) return null;
  const { code, findings } = detail as { code?: unknown; findings?: unknown };
  if (code !== "PUBLIC_PROFILE_FINDINGS" || !Array.isArray(findings)) return null;
  return findings as PublicProfileFinding[];
}

// ── Hooki ────────────────────────────────────────────────────────────────

export function useShareablePublishedJobs(enabled: boolean) {
  return useQuery({
    queryKey: shareablePublishedJobsQueryKey(),
    queryFn: careerLinksApi.listPublishedJobs,
    enabled,
    staleTime: 30_000,
  });
}

export function useInviteLinks(enabled: boolean) {
  return useQuery({
    queryKey: inviteLinksQueryKey(),
    queryFn: careerLinksApi.listInviteLinks,
    enabled,
  });
}

export function useCareerLink(enabled: boolean) {
  return useQuery({
    queryKey: careerLinkQueryKey(),
    queryFn: careerLinksApi.getCareerLink,
    enabled,
  });
}

export function useJobPublicProfile(jobId: number | null) {
  return useQuery({
    queryKey: jobPublicProfileQueryKey(jobId ?? 0),
    queryFn: () => careerLinksApi.getPublicProfile(jobId as number),
    enabled: jobId != null && jobId > 0,
  });
}

export function useSlugAvailability(slug: string | null) {
  return useQuery({
    queryKey: slugAvailabilityQueryKey(slug ?? ""),
    queryFn: () => careerLinksApi.checkSlug(slug as string),
    enabled: !!slug,
    staleTime: 30_000,
  });
}
