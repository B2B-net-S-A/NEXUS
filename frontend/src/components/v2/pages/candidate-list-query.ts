import type { CandidatesView } from "@/lib/url-filters";

export interface CandidateListIncludeFlags {
  includeMatchStats: boolean;
  includeActiveRecruitments: boolean;
  includeLastActivity: boolean;
}

/** Heavy list enrichments are requested only when the active view renders them. */
export function getCandidateListIncludeFlags(
  view: CandidatesView,
  visibleColumns: ReadonlySet<string>,
): CandidateListIncludeFlags {
  const tiles = view === "tiles";
  return {
    includeMatchStats: tiles || visibleColumns.has("match"),
    includeActiveRecruitments:
      tiles ||
      visibleColumns.has("process") ||
      visibleColumns.has("recruitments") ||
      visibleColumns.has("stage_moved"),
    includeLastActivity:
      tiles ||
      visibleColumns.has("activity") ||
      visibleColumns.has("last_note") ||
      visibleColumns.has("rejection_reason") ||
      visibleColumns.has("rate"),
  };
}
