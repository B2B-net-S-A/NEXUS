// Insights → Zasady (05.11.2026): lista zasad i kto którą widzi. Widoczność idzie
// z rejestru Ustawień, bo to te same ekrany z tymi samymi bramkami.
import { RHYTHM_ROLES } from "@/lib/insights-roles";
import {
  canSeeSettingsItem,
  findSettingsItem,
  type SettingsItemId,
} from "@/lib/settings-registry";
import { formatDate } from "@/lib/utils";
import { hasRole, type useAuthStore } from "@/store/auth";

export type RuleId =
  | "przydzial"
  | "blizniaki"
  | "ranking"
  | "prepy"
  | "qc"
  | "cele"
  | "liga"
  | "aktywnosc"
  | "placementy";

export interface RuleRow {
  id: RuleId;
  group: string;
  title: string;
  question: string;
  /** Pozycja Ustawień z tym samym ekranem: jej bramka decyduje o widoczności. */
  settingsItem?: SettingsItemId;
  /** Ekran mieszka w innej zakładce Insights i wiersz tam prowadzi. */
  href?: string;
}

export interface RuleChange {
  at: string;
  /** `null` = zapis automatu. */
  by: string | null;
}

const ALLOCATION = "Przydział i rekrutacje";
const MATCHING = "Dopasowanie i AI";
const RESULTS = "Wyniki i nagrody";

export const RULE_ROWS: readonly RuleRow[] = [
  { id: "przydzial", group: ALLOCATION, title: "Automat przydziału", question: "Kto dostaje nowy request", settingsItem: "assign" },
  { id: "blizniaki", group: ALLOCATION, title: "Zasady bliźniaków", question: "Kiedy dwie rekrutacje to bliźniaki", settingsItem: "twin-rules" },
  { id: "ranking", group: MATCHING, title: "Ranking kandydatów", question: "Co liczy się przy dopasowaniu", settingsItem: "ranking" },
  { id: "prepy", group: MATCHING, title: "Ocena prepów", question: "Jak oceniamy Prep 1 i Prep 2", settingsItem: "prep-review" },
  { id: "qc", group: MATCHING, title: "Jakość QC", question: "Które uwagi QC CV blokują", settingsItem: "qc-quality" },
  { id: "cele", group: RESULTS, title: "Cele KPI", question: "Jakie cele mają role i osoby", settingsItem: "kpi-targets" },
  { id: "liga", group: RESULTS, title: "Liga, Wyścig i Ścieżka rozwoju", question: "Ile warte są punkty i progi awansu" },
  { id: "aktywnosc", group: RESULTS, title: "Punkty aktywności", question: "Ile warta jest akcja w „Aktywności”", href: "/insights?tab=rytm" },
  { id: "placementy", group: RESULTS, title: "Wykluczone placementy", question: "Co nie liczy się w statystykach", settingsItem: "placements" },
];

export const isRuleId = (value: string | null): value is RuleId =>
  RULE_ROWS.some((row) => row.id === value);

type AuthUser = ReturnType<typeof useAuthStore.getState>["user"];

export function visibleRuleRows(user: AuthUser): RuleRow[] {
  return RULE_ROWS.filter((row) => {
    if (row.id === "liga") return hasRole(user, "admin");
    if (row.id === "aktywnosc") return hasRole(user, ...RHYTHM_ROLES);
    const item = findSettingsItem(row.settingsItem);
    return item ? canSeeSettingsItem(user, item) : false;
  });
}

export function lastChangeText(change: RuleChange | null): string {
  if (!change) return "Nigdy";
  return `${formatDate(change.at)} · ${change.by ?? "automat"}`;
}

/** Komponent ekranu ma własny tytuł, więc zakładka go nie powtarza. */
export function ruleHasOwnHeader(row: RuleRow): boolean {
  return Boolean(findSettingsItem(row.settingsItem)?.ownHeader);
}
