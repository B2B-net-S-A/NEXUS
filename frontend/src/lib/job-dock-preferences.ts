/**
 * Preferencja „zwinięty dok gotowości" na kroku 02 (`variant="champion"`
 * `JobReadinessDock`, zakładka Championa w `app/jobs/[id]/page.tsx`).
 *
 * Wyniesione do osobnego modułu z tego samego powodu co
 * `job-header-preferences.ts` — test i strona muszą wiązać się z TĄ SAMĄ
 * wartością klucza, nie z dwiema osobnymi kopiami literału.
 *
 * Domyślnie ROZWINIĘTY (`false`): dok niesie na kroku 02 główną akcję
 * („Przekaż do searchu") i checklistę gotowości — schowanie go od pierwszego
 * wejścia ukrywałoby cel tej zakładki. Kto go raz zwinie (żeby dać miejsce
 * edytorowi Championa), ma to zapamiętane.
 */
export const JOB_CHAMPION_DOCK_COLLAPSED_STORAGE_KEY =
  "nexus:jobChampionDockCollapsed:v1";

export const JOB_CHAMPION_DOCK_COLLAPSED_DEFAULT = false;
