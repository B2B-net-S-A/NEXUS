import type { JobDetailTab } from "@/components/v2/jobs/JobDetailCompactHeader";

/**
 * Aliasy dla starych deep-linków, które nie są literałami `JobDetailTab`.
 *
 * `champion-profile` — `AddJobModal` (przed przejściem na `CreateJobModal`,
 * PR 2) przekierowywał na `?tab=champion-profile`, a strona rozumiała tylko
 * `?tab=champion` — DL zapisujący rekrutację lądował na pustym Pipeline
 * zamiast na Championie (przegląd 17.09.2026). `CreateJobModal` już generuje
 * poprawny link (`createdJobUrl`), ale stare zakładki przeglądarki i
 * powiadomienia sprzed tej zmiany nadal noszą `champion-profile`.
 *
 * `similar` — link z powiadomienia „Podobny request — gotowi kandydaci"
 * prowadzi na zakładkę AI Matching, nie na zakładkę o nazwie „similar".
 */
const TAB_PARAM_ALIASES: Readonly<Record<string, JobDetailTab>> = {
  "champion-profile": "champion",
  similar: "ai-matching",
};

/** Literały `JobDetailTab`, na które wolno wejść bezpośrednio przez `?tab=`. */
const DEEP_LINKABLE_TABS: ReadonlySet<JobDetailTab> = new Set<JobDetailTab>([
  "chat",
  "champion",
  "screening",
  "cv",
  "interviews",
  "contract",
]);

/**
 * Tłumaczy `?tab=` z URL-a na `JobDetailTab`, albo zwraca `null`, gdy
 * parametr jest pusty lub nieznany (strona zostaje na domyślnej zakładce).
 */
export function resolveJobDetailTab(
  tabParam: string | null | undefined,
): JobDetailTab | null {
  if (!tabParam) return null;
  const aliased = TAB_PARAM_ALIASES[tabParam];
  if (aliased) return aliased;
  if (DEEP_LINKABLE_TABS.has(tabParam as JobDetailTab)) {
    return tabParam as JobDetailTab;
  }
  return null;
}
