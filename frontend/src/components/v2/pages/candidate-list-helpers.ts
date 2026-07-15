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
  name?: string | null;
  lastname?: string | null;
  position?: string | null;
  current_role?: string | null;
  linkedin_current_title?: string | null;
  linkedin_current_company?: string | null;
  experience?: unknown;
  skills?: unknown;
  years_it_experience?: number | null;
}

/** Initials are the first letters of the first-name and last-name fields. */
export function getCandidateInitials(
  candidate: Pick<CandidateLite, "name" | "lastname">,
): string {
  const first = candidate.name?.trim().charAt(0) ?? "";
  const last = candidate.lastname?.trim().charAt(0) ?? "";
  return `${first}${last}`.toUpperCase();
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

/** Normalize a candidate location field to a human-readable string.
 *
 *  Most candidates have a plain-text location ("Warszawa", "Kraków/remote").
 *  External imports (Traffit, TalentRadar) may store a structured JSON blob:
 *    {"latitude":"...","longitude":"...","locality":"Warszawa",
 *     "region1":"Mazowieckie","region2":"Warszawa","country":"Polska",...}
 *  Rendering that JSON verbatim leaks raw data into the UI, so we parse it
 *  here and join `locality, region1, country` (deduped) into a readable label.
 *  Returns null for empty/unparseable input. */
export function formatCandidateLocation(loc?: string | null): string | null {
  if (loc == null) return null;
  const trimmed = String(loc).trim();
  if (!trimmed) return null;
  if (!trimmed.startsWith("{")) return trimmed;
  try {
    const parsed = JSON.parse(trimmed) as Record<string, unknown>;
    const pick = (k: string): string | null => {
      const v = parsed[k];
      return typeof v === "string" && v.trim() ? v.trim() : null;
    };
    const locality = pick("locality") ?? pick("city");
    const region = pick("region1");
    const country = pick("country");
    const parts: string[] = [];
    if (locality) parts.push(locality);
    if (region && region !== locality) parts.push(region);
    if (country && country !== region && country !== locality) parts.push(country);
    return parts.length > 0 ? parts.join(", ") : null;
  } catch {
    return null;
  }
}

/** Normalize a single tag entry to its display name.
 *
 *  Backend emits tags in several shapes:
 *    - bare strings: "python"
 *    - manual tags: {name: "..."} or {label: "..."}
 *    - Traffit source tags: {type:"traffit_source", domain:"Rekomendacja", value:null}
 *  External imports also produce rows with empty/whitespace names that would
 *  render as a bare "#" chip. Returns null for anything that wouldn't produce
 *  a readable label so callers can filter the list before mapping. */
export function getTagName(t: unknown): string | null {
  if (typeof t === "string") {
    const v = t.trim();
    return v ? v : null;
  }
  if (t && typeof t === "object") {
    const obj = t as Record<string, unknown>;
    const raw = obj.name ?? obj.label ?? obj.value ?? obj.domain;
    if (typeof raw === "string") {
      const v = raw.trim();
      return v ? v : null;
    }
  }
  return null;
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

/** Polskie etykiety etapów pipeline'u (kanoniczny słownik dla listy + panelu). */
export const STAGE_LABELS: Record<string, string> = {
  new: "Nowy",
  prep_call: "Prep call",
  screening: "Screening",
  verified: "Zweryfikowany",
  interview: "Interview",
  cv_sent: "CV wysłane",
  client_interview: "Rozmowa u klienta",
  acceptance: "Akceptacja",
  negotiation: "Negocjacje",
  onboarding: "Onboarding",
  hired: "Zatrudniony",
  rejected: "Odrzucony",
  withdrawn: "Wycofany",
};

/** Tłumaczy klucz etapu na polską etykietę (fallback: surowy klucz). */
export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

/** Badge variants used for stage pills — a subset of the DS Badge tones.
 *  Kept as a local union so this pure helper stays decoupled from the Badge
 *  component's prop types. */
export type StageBadgeVariant =
  | "neutral"
  | "soft"
  | "info"
  | "success"
  | "warning"
  | "danger";

export interface StageTone {
  /** DS Badge variant driving the pill's background/text/border. */
  variant: StageBadgeVariant;
  /** Solid Tailwind bg-* class for the leading status dot. */
  dot: string;
}

/** Token-first colour map for the whole 13-stage pipeline.
 *
 *  Design intent (mockup → semantic token):
 *    Nowy/Wycofany → neutral (grey)      · CV wysłane/Screening→ blue/amber
 *    Rozmowa (interview) → primary (soft indigo)  · Oferta/Zatrudniony → success
 *    Odrzucony → destructive.
 *  Every value resolves to a semantic token, so dark-mode + theme swaps just work. */
const STAGE_TONES: Record<string, StageTone> = {
  new: { variant: "neutral", dot: "bg-muted-foreground/60" },
  prep_call: { variant: "info", dot: "bg-info" },
  screening: { variant: "warning", dot: "bg-warning" },
  verified: { variant: "info", dot: "bg-info" },
  interview: { variant: "soft", dot: "bg-primary" },
  cv_sent: { variant: "info", dot: "bg-info" },
  client_interview: { variant: "soft", dot: "bg-primary" },
  acceptance: { variant: "success", dot: "bg-success" },
  negotiation: { variant: "warning", dot: "bg-warning" },
  onboarding: { variant: "success", dot: "bg-success" },
  hired: { variant: "success", dot: "bg-success" },
  rejected: { variant: "danger", dot: "bg-destructive" },
  withdrawn: { variant: "neutral", dot: "bg-muted-foreground/50" },
};

const NEUTRAL_STAGE_TONE: StageTone = {
  variant: "neutral",
  dot: "bg-muted-foreground/60",
};

/** Resolve a stage key to its pill tone. Unknown stages fall back to neutral. */
export function stageTone(stage: string): StageTone {
  return STAGE_TONES[stage] ?? NEUTRAL_STAGE_TONE;
}

/** Token-based avatar tints — deterministic per seed so a candidate keeps the
 *  same colour across the list row, the expanded detail, and the panel. */
const AVATAR_TONES = [
  "bg-primary/10 text-primary",
  "bg-info-muted text-info-muted-foreground",
  "bg-success-muted text-success-muted-foreground",
  "bg-warning-muted text-warning-muted-foreground",
  "bg-destructive-muted text-destructive-muted-foreground",
];

/** Pick a stable avatar tint from `seed` (candidate id or name). */
export function avatarTone(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i += 1) {
    h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  }
  return AVATAR_TONES[h % AVATAR_TONES.length];
}
