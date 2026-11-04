/**
 * Zasady automatu przydziału w Ustawieniach (29.10.2026): wartości domyślne
 * (lustro `AllocationRules` w `services/request_allocation_rules.py`),
 * etykiety i opis zmian do listy „Zmieniasz” i historii.
 */
import type { AllocationRunMode, TeamRules } from "@/lib/api/requestAllocation"

export const DEFAULT_TEAM_RULES: TeamRules = {
  review_time: "08:30",
  include_p2: false,
  people_per_p1: 1,
  max_load: null,
  overflow: 1,
  outsiders: true,
  order: "sent_first",
  leave_policy: "wait",
}

export const MODE_LABEL: Record<AllocationRunMode, string> = {
  off: "Wyłączony",
  shadow: "Proponuje",
  auto: "Przydziela sam",
}

export const MAX_LOAD_OPTIONS = [4, 5, 6, 7, 8, 10] as const

type Field = keyof TeamRules | "mode"

/** Jak pokazać wartość pola w zdaniu „Limit P1 na osobę: 6”. */
export function ruleValueLabel(field: Field, value: unknown): string {
  switch (field) {
    case "mode":
      return MODE_LABEL[value as AllocationRunMode] ?? String(value)
    case "include_p2":
      return value ? "P0, P1 i P2" : "P0 i P1"
    case "people_per_p1":
      return `${value} os.`
    case "max_load":
      return value === null || value === undefined ? "bez limitu" : String(value)
    case "overflow":
      return Number(value) === 0 ? "przy każdej różnicy" : `różnica ponad ${value}`
    case "outsiders":
      return value ? "mogą dostać" : "czeka na Head of Recruitment"
    case "order":
      return value === "deadline_first" ? "najpierw najbliższy termin" : "najpierw bez wysłanych"
    case "leave_policy":
      return value === "ignore" ? "przydziela mimo to" : "czeka"
    case "review_time":
      return String(value)
  }
}

export const RULE_NAME: Record<Field, string> = {
  mode: "Tryb",
  include_p2: "Rekrutacje",
  people_per_p1: "Osób na rekrutację P1",
  max_load: "Limit P1 na osobę",
  overflow: "Inna kategoria",
  outsiders: "Osoby bez kategorii",
  order: "Kolejność",
  leave_policy: "Bez świeżych urlopów",
  review_time: "Przegląd o",
}

const FIELDS = Object.keys(DEFAULT_TEAM_RULES) as (keyof TeamRules)[]

/** „Tryb: Proponuje”, „Limit P1 na osobę: 6” — różnice szkicu od zapisanych. */
export function changedRuleLabels(
  saved: TeamRules,
  savedMode: AllocationRunMode,
  draft: TeamRules,
  draftMode: AllocationRunMode,
): string[] {
  const out: string[] = []
  if (savedMode !== draftMode) out.push(`${RULE_NAME.mode}: ${ruleValueLabel("mode", draftMode)}`)
  for (const field of FIELDS) {
    if (saved[field] !== draft[field]) {
      out.push(`${RULE_NAME[field]}: ${ruleValueLabel(field, draft[field])}`)
    }
  }
  return out
}

/** Wpis historii: „Limit P1 na osobę: bez limitu → 6”. */
export function historyLines(changed: Record<string, [unknown, unknown]>): string[] {
  return Object.entries(changed).map(([field, [before, after]]) => {
    const key = (field in RULE_NAME ? field : null) as Field | null
    if (!key) return field
    return `${RULE_NAME[key]}: ${ruleValueLabel(key, before)} → ${ruleValueLabel(key, after)}`
  })
}
