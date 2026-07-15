import { formatDate } from "@/lib/utils";
import {
  formatCandidateLocation,
  getCandidateInitials,
  getCurrentTitle,
  getSkillList,
} from "@/components/v2/pages/candidate-list-helpers";
import type {
  CandidateDetailData,
  CandidateDetailPair,
} from "@/components/v2/candidates/CandidateDetailPanel";

interface RecruitmentLite {
  job_id: number;
  job_title: string;
  client_name?: string | null;
  stage: string;
  moved_at?: string | null;
  moved_by_name?: string | null;
}

/** Structural subset of the list-row Candidate that the detail VM needs.
 *  Declared here (rather than importing the page-local `Candidate`) so this
 *  mapper stays decoupled from CandidatesListV2. */
export interface CandidateForDetail {
  id: number;
  name?: string | null;
  lastname?: string | null;
  email?: string | null;
  phone?: string | null;
  city?: string | null;
  location?: string | null;
  country?: string | null;
  skills?: unknown;
  experience?: unknown;
  position?: string | null;
  current_role?: string | null;
  linkedin_current_title?: string | null;
  linkedin_current_company?: string | null;
  created_at?: string | null;
  created_by_user?: { id: number; name: string } | null;
  last_rate?: string | null;
  last_note_preview?: string | null;
  last_rejection_reason?: string | null;
  active_recruitments?: RecruitmentLite[] | null;
  years_it_experience?: number | null;
  source?: string | null;
}

const TERMINAL_STAGES = new Set(["rejected", "withdrawn", "hired"]);

/** Pick the recruitment that best represents the candidate's current state:
 *  active stages before terminal ones, newest stage-move first. */
function primaryRecruitment(
  recs: RecruitmentLite[] | null | undefined,
): RecruitmentLite | null {
  if (!recs || recs.length === 0) return null;
  const sorted = [...recs].sort((a, b) => {
    const ta = TERMINAL_STAGES.has(a.stage) ? 1 : 0;
    const tb = TERMINAL_STAGES.has(b.stage) ? 1 : 0;
    if (ta !== tb) return ta - tb;
    const ma = a.moved_at ? Date.parse(a.moved_at) : 0;
    const mb = b.moved_at ? Date.parse(b.moved_at) : 0;
    return mb - ma;
  });
  return sorted[0] ?? null;
}

/** Map a list-row candidate to the shared presentational view-model consumed by
 *  {@link CandidateDetailPanel} and {@link CandidateRowDetail}. Only fields that
 *  the list payload actually carries are surfaced — the AI summary and full
 *  timeline stay behind "Otwórz pełny profil". */
export function toCandidateDetail(c: CandidateForDetail): CandidateDetailData {
  const fullName = `${c.name ?? ""} ${c.lastname ?? ""}`.trim() || "Bez nazwiska";
  const role = getCurrentTitle(c);
  const location =
    formatCandidateLocation(c.city ?? c.location) ?? (c.country ?? null);
  const skills = getSkillList(c, 24);
  const primary = primaryRecruitment(c.active_recruitments);
  const recCount = c.active_recruitments?.length ?? 0;

  const detailPairs: CandidateDetailPair[] = [];
  if (c.last_rate) detailPairs.push({ label: "Stawka", value: c.last_rate });
  if (typeof c.years_it_experience === "number") {
    detailPairs.push({
      label: "Doświadczenie",
      value: `${c.years_it_experience} lat`,
    });
  }
  if (location) detailPairs.push({ label: "Lokalizacja", value: location });
  if (c.source) detailPairs.push({ label: "Źródło", value: c.source });
  if (c.created_by_user?.name) {
    detailPairs.push({ label: "Dodał", value: c.created_by_user.name });
  }
  if (c.created_at) {
    detailPairs.push({ label: "Dodano", value: formatDate(c.created_at) });
  }

  return {
    id: c.id,
    name: fullName,
    initials: getCandidateInitials(c) || fullName.slice(0, 2).toUpperCase(),
    role,
    location,
    phone: c.phone ?? null,
    email: c.email ?? null,
    stage: primary?.stage ?? "",
    stageDate: primary?.moved_at ? formatDate(primary.moved_at) : null,
    rateLabel: c.last_rate ?? null,
    owner: primary?.moved_by_name ?? c.created_by_user?.name ?? null,
    recruitments: recCount > 0 ? recCount : undefined,
    headline: null,
    skills,
    lastNote: c.last_note_preview ?? null,
    rejectionReason: c.last_rejection_reason ?? null,
    detailPairs,
  };
}
