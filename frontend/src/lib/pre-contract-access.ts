import type { UserRole } from "@/store/auth";

/**
 * Kto pracuje na umowach przedwstępnych — lustro `PRE_CONTRACT_ROLES`
 * (backend/app/api/pre_contracts.py): osoby z rekrutacji oraz Finanse, Rada
 * nadzorcza i Automatyzacje, jak rekruter — odczyt, pliki i akcje (decyzja
 * Artura 22.10.2026, audyt F54). Viewer nie: jego wejścia kończyły się 403.
 * Osobny moduł bez zależności od store'a, bo czyta go też middleware (Edge).
 */
export const PRE_CONTRACT_ROLES: readonly UserRole[] = [
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "recruiter",
  "finance",
  "automation",
  "board",
];

/** Lista „Umowy przedwstępne” — jedyny ekran rekrutacji otwarty Radzie
 *  nadzorczej (decyzja Artura 23.10.2026). */
export const PRE_CONTRACTS_PATH = "/jobs/umowy-przedwstepne";
