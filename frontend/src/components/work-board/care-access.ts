import type { HrConfig } from "@/lib/api/hr";
import { hasRole, type User } from "@/store/auth";

/**
 * Kto widzi karty opieki na tablicy — to samo co pozycja „Opieka nad
 * konsultantami” w menu (`nav-registry`: moduł `care` otwarty + rola DL, TCM,
 * Head of Recruitment albo admin). Rola „Automatyzacje” opieki nie widzi
 * (serwer: `care_gates.refuse_automation`). Serwer i tak odmawia (403) —
 * to tylko, żeby nie pytać o tablicę opieki kogoś, kto jej nie dostanie.
 */
export function canSeeCareBoard(
  user: User | null | undefined,
  config: Pick<HrConfig, "program" | "open_modules"> | null | undefined,
): boolean {
  if (!config?.program || !config.open_modules.care) return false;
  return hasRole(user, "admin", "delivery_lead", "talent_community_manager", "head_of_recruitment");
}
