/**
 * Adres URL profilu kandydata: cztery zakładki (Profil, Rekrutacje, Historia,
 * Pliki i umowy) i ich filtry.
 *
 * Stare klucze MUSZĄ działać dalej — linki z powiadomień są zapisane w bazie
 * (`?tab=chat&msg=`, `?tab=activity&activity=notes&note=`), a stare zakładki
 * („Dopasowanie”, „Maile”, „Aktywność”) przez lata trafiały do zakładek
 * przeglądarki i maili. Każdy stary klucz ma tu alias na nową zakładkę
 * z właściwym filtrem albo sekcją.
 */
export const PROFILE_SECTIONS = [
  "summary",
  "recruitments",
  "activity",
  "documents",
] as const;

/** Filtry zakładki „Historia”. `timeline` = „Wszystko”. */
export const ACTIVITY_VIEWS = [
  "timeline",
  "notes",
  "emails",
  "calls",
  "chat",
] as const;
/** Sekcja zakładki „Pliki i umowy”, do której przewijamy. */
export const DOCUMENT_VIEWS = ["files", "contracts"] as const;
/** Sekcja zakładki „Rekrutacje” — `matching` rozwija „Dopasowanie do rekrutacji”. */
export const RECRUITMENT_VIEWS = ["list", "matching"] as const;

export type CandidateProfileSection = (typeof PROFILE_SECTIONS)[number];
export type CandidateActivityView = (typeof ACTIVITY_VIEWS)[number];
export type CandidateDocumentView = (typeof DOCUMENT_VIEWS)[number];
export type CandidateRecruitmentView = (typeof RECRUITMENT_VIEWS)[number];

/**
 * Stare zakładki najwyższego poziomu, które wciąż przyjmujemy na wejściu
 * zapisu (np. szybki podgląd z listy otwiera „matching”).
 */
export type LegacyProfileSection = "matching" | "emails";

export interface CandidateProfileView {
  section: CandidateProfileSection;
  activity: CandidateActivityView;
  documents: CandidateDocumentView;
  recruitments: CandidateRecruitmentView;
  /** True when an old top-level tab needs replacing with the canonical URL. */
  isLegacy: boolean;
  /** True when the incoming URL explicitly selected any tab. */
  hasExplicitTab: boolean;
}

export type CandidateProfileViewInput = {
  section: CandidateProfileSection | LegacyProfileSection;
  activity: CandidateActivityView;
  documents: CandidateDocumentView;
  recruitments?: CandidateRecruitmentView;
};

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

type ViewTarget = Pick<
  CandidateProfileView,
  "section" | "activity" | "documents" | "recruitments"
>;

const DEFAULT_TARGET: Omit<ViewTarget, "section"> = {
  activity: "timeline",
  documents: "files",
  recruitments: "list",
};

const target = (
  section: CandidateProfileSection,
  sub: Partial<Omit<ViewTarget, "section">> = {},
): ViewTarget => ({ section, ...DEFAULT_TARGET, ...sub });

/**
 * Stare klucze `?tab=` → nowa zakładka z filtrem. Każdy wpis tutaj to link,
 * który gdzieś żyje (powiadomienia w bazie, zakładki przeglądarki, maile).
 */
const LEGACY_TABS: Record<string, ViewTarget> = {
  // Zakładki sprzed 09.2026 (sześć sekcji).
  matching: target("recruitments", { recruitments: "matching" }),
  emails: target("activity", { activity: "emails" }),
  // Zakładki sprzed PR2 (dziewięć zakładek).
  profil: target("summary"),
  podglad: target("activity"),
  timeline: target("activity"),
  rekrutacje: target("recruitments"),
  dopasowanie: target("recruitments", { recruitments: "matching" }),
  notatki: target("activity", { activity: "notes" }),
  // Angielski alias — starsze linki z powiadomień o wzmiankach (`?tab=notes`).
  notes: target("activity", { activity: "notes" }),
  calls: target("activity", { activity: "calls" }),
  // `?tab=chat&msg=` — link z powiadomienia czatu (candidate_chat.py).
  chat: target("activity", { activity: "chat" }),
  maile: target("activity", { activity: "emails" }),
  pliki: target("documents", { documents: "files" }),
  umowa: target("documents", { documents: "contracts" }),
};

/**
 * Translate the incoming URL to the four-tab information architecture.
 * Unknown values fail safely to the summary.
 */
export function parseCandidateProfileView(
  params: URLSearchParams,
  options: { fromJob?: boolean } = {},
): CandidateProfileView {
  const rawTab = params.get("tab");
  const rawActivity = params.get("activity");
  const rawDocuments = params.get("documents");
  const rawRecruitments = params.get("recruitments");

  if (isOneOf(rawTab, PROFILE_SECTIONS)) {
    return {
      section: rawTab,
      activity: isOneOf(rawActivity, ACTIVITY_VIEWS) ? rawActivity : "timeline",
      documents: isOneOf(rawDocuments, DOCUMENT_VIEWS)
        ? rawDocuments
        : "files",
      recruitments: isOneOf(rawRecruitments, RECRUITMENT_VIEWS)
        ? rawRecruitments
        : "list",
      isLegacy: false,
      hasExplicitTab: true,
    };
  }

  if (rawTab && Object.prototype.hasOwnProperty.call(LEGACY_TABS, rawTab)) {
    return {
      ...LEGACY_TABS[rawTab],
      isLegacy: true,
      hasExplicitTab: true,
    };
  }

  // Wejście z rekrutacji: zakładka Rekrutacje z tą rekrutacją rozwiniętą
  // (fokus liczony w profilu z `jobId`, gdy brak `focusJobId`).
  if (options.fromJob) {
    return {
      ...target("recruitments"),
      isLegacy: false,
      hasExplicitTab: false,
    };
  }

  return {
    ...target("summary"),
    isLegacy: Boolean(rawTab),
    hasExplicitTab: Boolean(rawTab),
  };
}

/** Sprowadza stary klucz sekcji (`matching`, `emails`) do nowej zakładki. */
export function normalizeProfileViewInput(
  view: CandidateProfileViewInput,
): ViewTarget {
  if (view.section === "matching") {
    return {
      section: "recruitments",
      activity: view.activity,
      documents: view.documents,
      recruitments: "matching",
    };
  }
  if (view.section === "emails") {
    return {
      section: "activity",
      activity: "emails",
      documents: view.documents,
      recruitments: view.recruitments ?? "list",
    };
  }
  return {
    section: view.section,
    activity: view.activity,
    documents: view.documents,
    recruitments: view.recruitments ?? "list",
  };
}

/** Preserve unrelated context (`nav`, filters, `from`, `jobId`, `msg`). */
export function withCandidateProfileView(
  current: URLSearchParams,
  input: CandidateProfileViewInput,
): URLSearchParams {
  const view = normalizeProfileViewInput(input);
  const next = new URLSearchParams(current.toString());
  next.set("tab", view.section);

  if (view.section === "activity") next.set("activity", view.activity);
  else next.delete("activity");

  if (view.section === "documents") next.set("documents", view.documents);
  else next.delete("documents");

  if (view.section === "recruitments" && view.recruitments === "matching") {
    next.set("recruitments", "matching");
  } else next.delete("recruitments");

  return next;
}

/**
 * Notatka wskazana w adresie (`?note=<id>`, link z powiadomienia o wzmiance).
 * Tylko dodatnia liczba całkowita; wszystko inne jest ignorowane.
 */
export function parseCandidateNoteFocus(params: URLSearchParams): number | null {
  const raw = params.get("note");
  if (!raw || !/^[1-9]\d*$/.test(raw)) return null;
  const noteId = Number(raw);
  return isPositiveSafeInteger(noteId) ? noteId : null;
}
