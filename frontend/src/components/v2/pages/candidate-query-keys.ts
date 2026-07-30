/**
 * Canonical React Query keys for every candidate-profile surface.
 *
 * Candidate ids are normalised to numbers at the boundary so the list drawer,
 * full profile and mutations share one cache entry instead of alternating
 * between `"123"` and `123` keys.
 */
const candidateId = (id: number | string) => Number(id);

type ViewerScopeUser = {
  id?: number | null;
  role?: string | null;
  roles?: readonly string[] | null;
};

/**
 * Cache partition for candidate data whose response is filtered by the
 * effective viewer scope. Roles are sorted so equivalent multi-role sessions
 * share an identity, while a user or role switch can never reuse the previous
 * viewer's scoped payload.
 */
export function candidateViewerScopeKey(
  user: ViewerScopeUser | null | undefined,
): string | null {
  const viewerId = Number(user?.id);
  if (!Number.isSafeInteger(viewerId) || viewerId <= 0) return null;

  const roles = Array.from(
    new Set(
      [user?.role, ...(user?.roles ?? [])].filter(
        (role): role is string => typeof role === "string" && role.length > 0,
      ),
    ),
  ).sort();
  return `viewer:${viewerId}:roles:${roles.join(",") || "none"}`;
}

export const candidateQueryKeys = {
  all: ["candidate"] as const,
  detail: (id: number | string) => ["candidate", candidateId(id)] as const,
  quickView: (id: number | string) =>
    ["candidate-quick-view", candidateId(id)] as const,
  risk: (id: number | string) => ["candidate-risk", candidateId(id)] as const,
  history: (id: number | string, viewerScope: string) =>
    ["candidate-history", candidateId(id), { viewerScope }] as const,
  historyRoot: (id: number | string) =>
    ["candidate-history", candidateId(id)] as const,
  timeline: (id: number | string, limit: number) =>
    ["candidate-timeline", candidateId(id), { limit }] as const,
  timelineRoot: (id: number | string) =>
    ["candidate-timeline", candidateId(id)] as const,
  notes: (id: number | string) =>
    ["candidate-notes", candidateId(id)] as const,
  calls: (id: number | string) =>
    ["candidate-calls", candidateId(id)] as const,
  aiProfile: (id: number | string) =>
    ["candidate-ai-profile", candidateId(id)] as const,
  activitySummary: (id: number | string, viewerScope: string) =>
    [
      "candidate-activity-summary",
      candidateId(id),
      { viewerScope },
    ] as const,
  languages: (id: number | string) =>
    ["candidate-languages", candidateId(id)] as const,
  profileRate: (id: number | string) =>
    ["candidate-profile-rate", candidateId(id)] as const,
  recentRecruitments: (
    id: number | string,
    limit: number,
    viewerScope: string,
  ) =>
    [
      "candidate-recent-recruitments",
      candidateId(id),
      { limit, viewerScope },
    ] as const,
  documents: (id: number | string) =>
    ["candidate-documents", candidateId(id)] as const,
  cvDocuments: (id: number | string) =>
    ["candidate-documents", candidateId(id), { kind: "cv" }] as const,
  contracts: (id: number | string) =>
    ["candidate-contracts", candidateId(id)] as const,
  recommendations: (id: number | string, topK: number) =>
    ["suggested-jobs", candidateId(id), { topK }] as const,
  recommendationsRoot: (id: number | string) =>
    ["suggested-jobs", candidateId(id)] as const,
} as const;
