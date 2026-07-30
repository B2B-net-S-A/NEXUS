export const PROFILE_SECTIONS = [
  "summary",
  "recruitments",
  "activity",
  "matching",
  "documents",
] as const;

export const ACTIVITY_VIEWS = ["timeline", "notes", "calls", "chat"] as const;
export const DOCUMENT_VIEWS = ["files", "contracts"] as const;

export type CandidateProfileSection = (typeof PROFILE_SECTIONS)[number];
export type CandidateActivityView = (typeof ACTIVITY_VIEWS)[number];
export type CandidateDocumentView = (typeof DOCUMENT_VIEWS)[number];

export interface CandidateProfileView {
  section: CandidateProfileSection;
  activity: CandidateActivityView;
  documents: CandidateDocumentView;
  /** True when an old top-level tab needs replacing with the canonical URL. */
  isLegacy: boolean;
  /** True when the incoming URL explicitly selected any tab. */
  hasExplicitTab: boolean;
}

type VisibleRecruitment = {
  job_id?: unknown;
  id?: unknown;
};

const isOneOf = <T extends readonly string[]>(
  value: string | null,
  values: T,
): value is T[number] => Boolean(value && values.includes(value as T[number]));

const isPositiveSafeInteger = (value: unknown): value is number =>
  typeof value === "number" &&
  Number.isSafeInteger(value) &&
  value > 0;

/**
 * Parse a recruitment focus request without accepting coercible or ambiguous
 * values such as decimals, exponents, whitespace or signed numbers.
 */
export function parseCandidateRecruitmentFocus(
  params: URLSearchParams,
): number | null {
  const rawFocusJobId = params.get("focusJobId");
  if (!rawFocusJobId || !/^[1-9]\d*$/.test(rawFocusJobId)) return null;

  const focusJobId = Number(rawFocusJobId);
  return isPositiveSafeInteger(focusJobId) ? focusJobId : null;
}

/**
 * Build the only supported link from the recent-recruitments rail. Invalid
 * identifiers intentionally render as plain text rather than as a link.
 */
export function candidateRecruitmentFocusHref(
  candidateId: number,
  jobId: number,
): string | null {
  if (
    !isPositiveSafeInteger(candidateId) ||
    !isPositiveSafeInteger(jobId)
  ) {
    return null;
  }

  return `/candidates/${candidateId}?tab=recruitments&focusJobId=${jobId}`;
}

/**
 * Resolve a requested focus only against the already authorised history
 * response. The URL value must never be used to fetch or construct a process.
 */
export function resolveVisibleRecruitmentFocus(
  requestedJobId: number | null,
  history: VisibleRecruitment[],
): number | null {
  if (!isPositiveSafeInteger(requestedJobId) || !Array.isArray(history)) {
    return null;
  }

  const isVisible = history.some((recruitment) => {
    const jobId = recruitment.job_id ?? recruitment.id;
    return isPositiveSafeInteger(jobId) && jobId === requestedJobId;
  });

  return isVisible ? requestedJobId : null;
}

/**
 * Focus an existing recruitment card. This helper only touches an element
 * already rendered from the authorised history response and never loads data.
 */
export function focusCandidateRecruitmentCard(
  jobId: number | null,
): boolean {
  if (!isPositiveSafeInteger(jobId) || typeof document === "undefined") {
    return false;
  }

  const recruitmentCard = document.getElementById(
    `candidate-recruitment-${jobId}`,
  );
  if (!(recruitmentCard instanceof HTMLElement)) return false;

  const prefersReducedMotion =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  recruitmentCard.focus({ preventScroll: true });
  recruitmentCard.scrollIntoView?.({
    behavior: prefersReducedMotion ? "auto" : "smooth",
    block: "center",
  });
  return true;
}

/**
 * Translate the pre-PR2, nine-tab URLs to the five-section information
 * architecture. Unknown values fail safely to the summary.
 */
export function parseCandidateProfileView(
  params: URLSearchParams,
  options: { fromJob?: boolean } = {},
): CandidateProfileView {
  const rawTab = params.get("tab");
  const rawActivity = params.get("activity");
  const rawDocuments = params.get("documents");

  if (isOneOf(rawTab, PROFILE_SECTIONS)) {
    return {
      section: rawTab,
      activity: isOneOf(rawActivity, ACTIVITY_VIEWS) ? rawActivity : "timeline",
      documents: isOneOf(rawDocuments, DOCUMENT_VIEWS)
        ? rawDocuments
        : "files",
      isLegacy: false,
      hasExplicitTab: true,
    };
  }

  const legacy: Record<
    string,
    Pick<CandidateProfileView, "section" | "activity" | "documents">
  > = {
    profil: { section: "summary", activity: "timeline", documents: "files" },
    podglad: {
      section: "activity",
      activity: "timeline",
      documents: "files",
    },
    timeline: {
      section: "activity",
      activity: "timeline",
      documents: "files",
    },
    rekrutacje: {
      section: "recruitments",
      activity: "timeline",
      documents: "files",
    },
    dopasowanie: {
      section: "matching",
      activity: "timeline",
      documents: "files",
    },
    notatki: { section: "activity", activity: "notes", documents: "files" },
    calls: { section: "activity", activity: "calls", documents: "files" },
    chat: { section: "activity", activity: "chat", documents: "files" },
    pliki: { section: "documents", activity: "timeline", documents: "files" },
    umowa: {
      section: "documents",
      activity: "timeline",
      documents: "contracts",
    },
  };

  if (rawTab && legacy[rawTab]) {
    return {
      ...legacy[rawTab],
      isLegacy: true,
      hasExplicitTab: true,
    };
  }

  if (options.fromJob) {
    return {
      section: "activity",
      activity: "timeline",
      documents: "files",
      isLegacy: false,
      hasExplicitTab: false,
    };
  }

  return {
    section: "summary",
    activity: "timeline",
    documents: "files",
    isLegacy: Boolean(rawTab),
    hasExplicitTab: Boolean(rawTab),
  };
}

/** Preserve unrelated context (`nav`, filters, `from`, `jobId`, `msg`). */
export function withCandidateProfileView(
  current: URLSearchParams,
  view: Pick<CandidateProfileView, "section" | "activity" | "documents">,
): URLSearchParams {
  const next = new URLSearchParams(current.toString());
  next.set("tab", view.section);

  if (view.section === "activity") next.set("activity", view.activity);
  else next.delete("activity");

  if (view.section === "documents") next.set("documents", view.documents);
  else next.delete("documents");

  return next;
}
