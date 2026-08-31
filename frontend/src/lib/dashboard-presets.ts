import {
  getUserRoles,
  type DashboardPreset,
  type User,
} from "@/store/auth"

export type { DashboardPreset } from "@/store/auth"

export type DashboardPeriod = "day" | "week" | "month" | "quarter" | "year"

export interface DashboardPresetDefinition {
  label: string
  shortLabel: string
  title: string
  description: string
  defaultPeriod: DashboardPeriod
}

export const DASHBOARD_PRESETS: Record<
  DashboardPreset,
  DashboardPresetDefinition
> = {
  "admin-ops": {
    label: "Admin Ops",
    shortLabel: "Admin",
    title: "Centrum operacyjne",
    description: "Otwarte procesy, odpowiedzialność i braki decyzyjne w jednym miejscu.",
    defaultPeriod: "month",
  },
  "delivery-lead": {
    label: "Delivery Lead",
    shortLabel: "Delivery",
    title: "Delivery Lead",
    description: "Procesy przypisanych klientów, kandydaci na etapach i podobne zapytania.",
    defaultPeriod: "month",
  },
  "head-of-recruitment": {
    label: "Head of Recruitment",
    shortLabel: "HoR",
    title: "Head of Recruitment",
    description: "Procesy zespołu według kategorii, etapów, właścicieli i faworytów.",
    defaultPeriod: "week",
  },
  "my-work": {
    label: "My Work",
    shortLabel: "My Work",
    title: "Moja praca",
    description: "Dzienny cel, własne KPI i bieżące procesy rekrutacyjne.",
    defaultPeriod: "day",
  },
  finance: {
    label: "Finanse",
    shortLabel: "Finanse",
    title: "Finanse",
    description: "Pełny widok procesów rekrutacyjnych, etapów, właścicieli i faworytów.",
    defaultPeriod: "quarter",
  },
}

const PRESET_VALUES = Object.keys(DASHBOARD_PRESETS) as DashboardPreset[]
const PERIOD_VALUES: DashboardPeriod[] = [
  "day",
  "week",
  "month",
  "quarter",
  "year",
]

export function isDashboardPreset(value: string | null): value is DashboardPreset {
  return value !== null && PRESET_VALUES.includes(value as DashboardPreset)
}

export function isDashboardPeriod(value: string | null): value is DashboardPeriod {
  return value !== null && PERIOD_VALUES.includes(value as DashboardPeriod)
}

/**
 * Backendowe available_dashboard_presets są źródłem prawdy. Fallback dotyczy
 * wyłącznie sesji zapisanych przed wdrożeniem nowego kontraktu /api/auth/me.
 */
export function getAvailableDashboardPresets(
  user:
    | Pick<
        User,
        "role" | "roles" | "available_dashboard_presets"
      >
    | null
    | undefined,
): DashboardPreset[] {
  if (!user) return []
  if (Array.isArray(user.available_dashboard_presets)) {
    return Array.from(
      new Set(
        user.available_dashboard_presets.filter((preset) =>
          PRESET_VALUES.includes(preset),
        ),
      ),
    )
  }
  const roles = new Set(getUserRoles(user))
  if (roles.has("admin")) return [...PRESET_VALUES]
  // Finance pozostaje ekskluzywne także dla starej sesji bez listy presetów.
  if (roles.has("finance")) return ["finance"]

  const fallback: DashboardPreset[] = []
  if (roles.has("head_of_recruitment")) fallback.push("head-of-recruitment")
  if (roles.has("delivery_lead")) fallback.push("delivery-lead")
  if (
    roles.has("tac") ||
    roles.has("recruiter") ||
    roles.has("sourcer")
  ) {
    fallback.push("my-work")
  }
  return fallback
}

export function getDefaultDashboardPreset(
  user:
    | Pick<
        User,
        | "role"
        | "roles"
        | "available_dashboard_presets"
        | "default_dashboard_preset"
      >
    | null
    | undefined,
): DashboardPreset | null {
  const available = getAvailableDashboardPresets(user)
  if (available.length === 0) return null
  const requested = user?.default_dashboard_preset
  return requested && available.includes(requested) ? requested : available[0]
}

export function dashboardHref(
  user:
    | Pick<
        User,
        | "role"
        | "roles"
        | "available_dashboard_presets"
        | "default_dashboard_preset"
      >
    | null
    | undefined,
): string {
  const preset = getDefaultDashboardPreset(user)
  if (!preset) return "/dashboard"
  const period = DASHBOARD_PRESETS[preset].defaultPeriod
  return `/dashboard?preset=${preset}&period=${period}`
}
