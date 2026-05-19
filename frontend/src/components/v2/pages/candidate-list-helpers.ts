/** Pure helpers extracted from CandidatesListV2 for unit testing & reuse.
 *
 *  These derive display fields (current title, current company, skill chips,
 *  experience badges) from the loosely-typed candidate payload returned by
 *  GET /api/candidates. Keeping them pure (no React, no DOM) lets the drawer
 *  and tiles view consume the same logic without duplicating coercion rules.
 */

export interface CandidateExperienceLite {
  company?: string | null;
  role?: string | null;
  start?: string | null;
  end?: string | null;
}

export interface CandidateLite {
  position?: string | null;
  current_role?: string | null;
  linkedin_current_title?: string | null;
  linkedin_current_company?: string | null;
  experience?: unknown;
  skills?: unknown;
  years_it_experience?: number | null;
}

/** Best-effort extractor for the candidate's CURRENT job title.
 *
 *  Resolution order (highest signal first):
 *    1. linkedin_current_title — populated by Proxycurl sync, freshest source
 *    2. experience[0].role — top-of-CV current role
 *    3. position — legacy free-text field
 *    4. current_role — alternative legacy field
 *  Returns null when no source has a non-empty value. */
export function getCurrentTitle(c: CandidateLite): string | null {
  if (c.linkedin_current_title) return c.linkedin_current_title;
  const exp = Array.isArray(c.experience)
    ? (c.experience as CandidateExperienceLite[])
    : [];
  const first = exp[0];
  if (first?.role) return first.role;
  if (c.position) return c.position;
  if (c.current_role) return c.current_role;
  return null;
}

/** Best-effort extractor for the candidate's CURRENT employer name.
 *
 *  Resolution order:
 *    1. linkedin_current_company — Proxycurl-synced, freshest
 *    2. experience[0].company — top-of-CV current employer */
export function getCurrentCompany(c: CandidateLite): string | null {
  if (c.linkedin_current_company) return c.linkedin_current_company;
  const exp = Array.isArray(c.experience)
    ? (c.experience as CandidateExperienceLite[])
    : [];
  return exp[0]?.company ?? null;
}

/** Coerce the loosely-typed skills payload to a clean string array.
 *
 *  The backend stores skills as JSONB and emits various shapes — accept:
 *    - array of strings → ["Python","AWS"]
 *    - array of {name|skill|label|value: string} objects (legacy parsers)
 *  Trims whitespace, drops empties, caps at `limit` entries. */
export function getSkillList(c: CandidateLite, limit = 8): string[] {
  const raw = c.skills;
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const item of raw) {
    if (typeof item === "string") {
      const v = item.trim();
      if (v) out.push(v);
    } else if (item && typeof item === "object") {
      const obj = item as Record<string, unknown>;
      const v = (obj.name ?? obj.skill ?? obj.label ?? obj.value) as unknown;
      if (typeof v === "string" && v.trim()) out.push(v.trim());
    }
    if (out.length >= limit) break;
  }
  return out;
}

export type ExperienceVariant = "outline" | "soft" | "success" | "neutral";

/** Bucket years_it_experience into Junior/Mid/Senior badge labels.
 *
 *  Buckets (Polish recruiter convention):
 *    0–1 years → outline ("Junior")
 *    2–4 years → soft ("Mid")
 *    5+ years  → success ("Senior") — uses `5+` notation regardless of exact value */
export function getExperienceLabel(
  years: number | null | undefined,
): { label: string; variant: ExperienceVariant } | null {
  if (years == null || years < 0) return null;
  if (years < 2) return { label: `${years} lat`, variant: "outline" };
  if (years < 5) return { label: `${years} lat`, variant: "soft" };
  return { label: `${years}+ lat`, variant: "success" };
}
