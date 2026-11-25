import type { UserRole } from "@/store/auth";

/** Kto widzi „Rytm dnia” — lustro `VIEWER_ROLES` z `services/work_rhythm.py`. */
export const RHYTHM_ROLES: UserRole[] = ["head_of_recruitment", "admin"];

/** Kto widzi „Zasady” — lustro `HeadOfRecruitmentPlus` w `api/insights_rules.py`. */
export const RULES_ROLES: UserRole[] = ["head_of_recruitment", "admin"];

/**
 * Kto widzi zakładkę „Przegrane” i zapisuje wnioski ze spotkania — lustro
 * `VIEWER_ROLES` w `backend/app/services/lost_review.py` (25.11.2026).
 */
export const LOST_REVIEW_ROLES: UserRole[] = ["admin", "head_of_recruitment", "delivery_lead"];
