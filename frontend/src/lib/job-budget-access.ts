import { hasRole, type User } from "@/store/auth";

/**
 * Czy użytkownik może ustawić widełki wynagrodzenia (`salary_min`/`salary_max`)
 * na rekrutacji.
 *
 * Lustro backendowej bramki `_assert_delivery_lead_finance_write`
 * (`backend/app/api/jobs.py`): Delivery Lead i Talent Community Manager BEZ
 * roli admina nie mogą tworzyć ani zmieniać pól budżetu rekrutacyjnego — to
 * pole widzi Delivery, ale wypełnia je TAC/HR/klient. `CreateJobModal` chowa
 * wtedy pole widełek zamiast pokazywać je i dostawać 403 po zapisie (odbiór
 * 17.09.2026 — DL widział placeholdery „90"/„150" i backend odrzucał je po
 * angielsku).
 *
 * Frontend chowa pole — backend i tak odrzuca zapis; ukrycie w UI nie jest
 * zabezpieczeniem, tylko uprzejmością wobec DL-a, który i tak dostałby 403.
 */
export function canManageRecruitmentBudget(
  user: Pick<User, "role" | "roles"> | null | undefined,
): boolean {
  if (!user) return false;
  if (hasRole(user, "admin")) return true;
  if (hasRole(user, "delivery_lead", "talent_community_manager")) return false;
  return true;
}
