// Podgląd na telefonie (05.11.2026): kto widzi którą zakładkę. Bramki to lustra
// tych, których pilnuje serwer (`BoardReader`, `view_team_kpi`, sekcja pipeline),
// żeby ekran nie obiecywał danych, których API i tak odmówi.

import { hasPermission } from "@/lib/permissions";
import { hasSectionAccess } from "@/lib/section-access";
import { hasAnalyticsCapability, hasRole, type User } from "@/store/auth";

export const PREVIEW_PATH = "/podglad";

/** Do takiej szerokości wejście na pulpit otwiera podgląd zamiast pełnej wersji. */
export const PHONE_MAX_WIDTH = 500;

export type ResultsKind = "company" | "portfolio" | "month";

/** Co pokazuje „Wyniki”; `null` = zakładki nie ma, start na „Zespole”. */
export function resultsKind(user: User | null | undefined): ResultsKind | null {
  if (!user) return null;
  if (hasRole(user, "board") || hasPermission(user, "company_results")) return "company";
  if (hasRole(user, "delivery_lead")) return "portfolio";
  if (hasRole(user, "recruiter")) return "month";
  return null;
}

export function canUsePreview(user: User | null | undefined): boolean {
  return Boolean(user) && hasSectionAccess(user, "insights");
}

/** Rekrutacje i plan dnia: Rada nie ma sekcji rekrutacji. */
export function seesRecruitment(user: User | null | undefined): boolean {
  return Boolean(user) && hasSectionAccess(user, "pipeline");
}

/** Lustro `_OVERSIGHT_ROLES` w `api/interview_cycle.py`. */
export function seesWholeTeam(user: User | null | undefined): boolean {
  return hasRole(user, "admin") || hasRole(user, "head_of_recruitment");
}

function hasOwnCandidates(user: User | null | undefined): boolean {
  return hasRole(user, "recruiter") || hasRole(user, "delivery_lead") || hasRole(user, "talent_community_manager");
}

/** Plan dnia ma sens, gdy ktoś prowadzi rozmowy; Finanse miałyby tu zawsze pusto. */
export function seesToday(user: User | null | undefined): boolean {
  return seesRecruitment(user) && (hasOwnCandidates(user) || seesWholeTeam(user));
}

/** Wszystkie otwarte dla tych, którzy nie mają własnych rekrutacji (admin, HoR, Finanse). */
export function seesAllRecruitments(user: User | null | undefined): boolean {
  return seesWholeTeam(user) || !hasOwnCandidates(user);
}

/** Lustro `seesTeam` z `ZespolView`. */
export function seesAttention(user: User | null | undefined): boolean {
  return hasRole(user, "admin") || hasAnalyticsCapability(user, "view_team_kpi");
}

/** „Piotr Kowalski” → „Piotr K.”: na telefonie plan dnia bez pełnych nazwisk. */
export function shortName(name: string | null | undefined): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length < 2) return parts[0] ?? "";
  return `${parts[0]} ${parts[parts.length - 1][0]}.`;
}
