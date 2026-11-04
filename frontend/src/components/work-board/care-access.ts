import { CARE_ROLES, type HrConfig } from "@/lib/api/hr";
import { hasRole, type User } from "@/store/auth";

/**
 * Kto widzi karty opieki na tablicy — to samo co pozycja „Opieka nad
 * konsultantami” w menu (moduł `care` otwarty + rola DL, TCM, Head of
 * Recruitment albo admin; osoba z samymi sprawami widzi w menu „Opiekę”, ale
 * kart opieki nie). Rola „Automatyzacje” opieki nie widzi
 * (serwer: `care_gates.refuse_automation`). Serwer i tak odmawia (403) —
 * to tylko, żeby nie pytać o tablicę opieki kogoś, kto jej nie dostanie.
 */
export function canSeeCareBoard(
  user: User | null | undefined,
  config: Pick<HrConfig, "program" | "open_modules"> | null | undefined,
): boolean {
  if (!config?.program || !config.open_modules.care) return false;
  return hasRole(user, ...CARE_ROLES);
}
