import type { UserRole } from "@/store/auth";

/** Kto widzi „Rytm dnia” — lustro `VIEWER_ROLES` z `services/work_rhythm.py`. */
export const RHYTHM_ROLES: UserRole[] = ["head_of_recruitment", "admin"];

/** Kto widzi „Zasady” — lustro `HeadOfRecruitmentPlus` w `api/insights_rules.py`. */
export const RULES_ROLES: UserRole[] = ["head_of_recruitment", "admin"];
