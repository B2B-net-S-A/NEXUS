// Układ pulpitu dla roli (04.10.2026).
//
// Do 04.10 pierwszy pulpit był pusty, a polecane kafelki trzeba było dodać
// ręcznie — po dwóch tygodniach 29 z 35 kont miało pusty pulpit. Teraz konto
// bez zapisanego układu widzi układ swojej roli (serwer mówi to polem
// `uses_role_layout`), a „Dostosuj pulpit” zapisuje jego kopię.
//
// Konto z kilkoma rolami dostaje sumę układów w kolejności `ROLE_PRIORITY`,
// z jedną tablicą „Requesty i obłożenie” (pierwszy zakres wygrywa). Head of
// Recruitment i admin nie dostają kafelków pracy rekrutera — prowadzącym
// rekrutacji nie bywają.

import type { DashboardTile } from "@/lib/api/userDashboard"
import {
  TILE_DEFINITIONS,
  TILE_TEMPLATES,
  templateAvailability,
  type TileTemplate,
} from "@/lib/dashboard-tiles/catalog"
import { GRID_COLUMNS, firstFreeSpot } from "@/lib/dashboard-tiles/layout"
import type { TileType } from "@/lib/api/userDashboard"
import { getUserRoles, type User, type UserRole } from "@/store/auth"

type Entry = { key: string; w?: number; h?: number }

const ROLE_LAYOUTS: Partial<Record<UserRole, Entry[]>> = {
  admin: [
    { key: "system_status", w: 6, h: 4 },
    { key: "team_signals", w: 6, h: 4 },
    { key: "hired_month_all", w: 4, h: 2 },
    { key: "active_contracts", w: 4, h: 2 },
    { key: "margin_number", w: 4, h: 2 },
    { key: "request_board", w: 12, h: 8 },
  ],
  finance: [
    { key: "orders_ending", w: 6, h: 4 },
    { key: "active_contracts", w: 6, h: 2 },
    { key: "margin_monthly", w: 12, h: 3 },
  ],
  head_of_recruitment: [
    { key: "team_signals", w: 6, h: 4 },
    { key: "team_funnel_week", w: 6, h: 4 },
    { key: "request_board", w: 12, h: 8 },
    { key: "contact_oversight", w: 12, h: 5 },
  ],
  delivery_lead: [
    { key: "my_clients_alerts", w: 8, h: 5 },
    { key: "today_cycle", w: 4, h: 5 },
    { key: "active_contracts", w: 4, h: 2 },
    { key: "orders_ending_count", w: 4, h: 2 },
    { key: "margin_number", w: 4, h: 2 },
    { key: "my_recruitments", w: 12, h: 5 },
    { key: "request_board_my_lead", w: 12, h: 8 },
  ],
  talent_community_manager: [
    { key: "my_contact_queue", w: 8, h: 5 },
    { key: "today_cycle", w: 4, h: 5 },
    { key: "my_people", w: 7, h: 4 },
    { key: "my_week", w: 5, h: 2 },
    { key: "request_board_my_category", w: 12, h: 8 },
  ],
  recruiter: [
    { key: "my_recruitments", w: 8, h: 5 },
    { key: "today_cycle", w: 4, h: 5 },
    { key: "request_board_my_category", w: 12, h: 8 },
    { key: "my_people", w: 7, h: 3 },
    { key: "my_week", w: 5, h: 3 },
  ],
}

const FALLBACK: Entry[] = [
  { key: "calendar_today", w: 4, h: 3 },
  { key: "note", w: 4, h: 2 },
]

// Kolejność ról przy sumowaniu układów i w etykiecie.
const ROLE_PRIORITY: UserRole[] = [
  "admin",
  "finance",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "recruiter",
]

// Kafelki pracy osoby przy rekrutacjach (kolejka, „Dziś”, moje rekrutacje) —
// Head i admin ich nie dostają, choć czasem mają też rolę rekrutera.
const LEADERSHIP: UserRole[] = ["admin", "head_of_recruitment"]
const INDIVIDUAL_ROLES: UserRole[] = ["recruiter", "talent_community_manager"]

const MAX_ROLE_TILES = 10

export const ROLE_LABELS_PL: Partial<Record<UserRole, string>> = {
  admin: "Administrator",
  finance: "Finanse",
  head_of_recruitment: "Head of Recruitment",
  delivery_lead: "Delivery Lead",
  talent_community_manager: "Talent Community Manager",
  recruiter: "Rekruter",
}

function layoutRoles(user: User | null | undefined): UserRole[] {
  const held = getUserRoles(user)
  const leader = held.some((r) => LEADERSHIP.includes(r))
  return ROLE_PRIORITY.filter(
    (r) => held.includes(r) && !(leader && INDIVIDUAL_ROLES.includes(r)),
  )
}

/** Etykieta ról, dla których złożono układ („Delivery Lead + Rekruter”). */
export function roleLayoutLabel(user: User | null | undefined): string | null {
  const roles = layoutRoles(user)
  if (!roles.length) return null
  return roles.map((r) => ROLE_LABELS_PL[r] ?? r).join(" + ")
}

type PlacedTemplate = { template: TileTemplate; w: number; h: number }

export interface RoleLayoutOptions {
  /**
   * Typy pomijane w układzie roli — np. kafelki kontaktu z kandydatem, gdy
   * funkcja jest wyłączona (`CANDIDATE_CONTACT_ENABLED`). Widżet zwraca wtedy
   * `null`, a w układzie roli zostałaby pusta dziura.
   */
  skipTypes?: ReadonlySet<TileType>
}

/** Kafelki kontaktu z kandydatem — działają tylko przy włączonej funkcji. */
export const CONTACT_TILE_TYPES: ReadonlySet<TileType> = new Set<TileType>([
  "my_contact_queue",
  "contact_oversight",
])

function roleEntries(
  user: User | null | undefined,
  options: RoleLayoutOptions = {},
): PlacedTemplate[] {
  const roles = layoutRoles(user)
  const entries = roles.length
    ? roles.flatMap((r) => ROLE_LAYOUTS[r] ?? [])
    : FALLBACK
  const seenKeys = new Set<string>()
  const seenTypes = new Set<TileType>()
  const out: PlacedTemplate[] = []
  for (const entry of entries) {
    if (seenKeys.has(entry.key)) continue
    const template = TILE_TEMPLATES.find((t) => t.key === entry.key)
    if (!template) continue
    // Jedna tablica „Requesty i obłożenie” — zakres z pierwszej roli.
    if (template.type === "request_board" && seenTypes.has("request_board")) continue
    if (!templateAvailability(template, user).ok) continue
    if (options.skipTypes?.has(template.type)) continue
    seenKeys.add(entry.key)
    seenTypes.add(template.type)
    const def = TILE_DEFINITIONS[template.type]
    out.push({
      template,
      w: Math.min(entry.w ?? template.size?.w ?? def.defaultSize.w, GRID_COLUMNS),
      h: entry.h ?? template.size?.h ?? def.defaultSize.h,
    })
    if (out.length >= MAX_ROLE_TILES) break
  }
  return out
}

/** Szablony układu roli — polecenia na pustej karcie i „Przywróć układ roli”. */
export function roleDefaultTemplates(
  user: User | null | undefined,
  options: RoleLayoutOptions = {},
): TileTemplate[] {
  return roleEntries(user, options).map((e) => ({ ...e.template, size: { w: e.w, h: e.h } }))
}

/**
 * Stały identyfikator kafelka układu roli (UUID v4 z hasza klucza). Siatka
 * nie miga między odświeżeniami, a zapisany później układ nie dubluje id.
 */
export function stableTileId(key: string): string {
  let h1 = 0x811c9dc5
  let h2 = 0x01000193
  for (let i = 0; i < key.length; i += 1) {
    const c = key.charCodeAt(i)
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0
    h2 = Math.imul(h2 ^ c, 0x811c9dc5) >>> 0
  }
  const hex = (h1.toString(16).padStart(8, "0") + h2.toString(16).padStart(8, "0"))
    .repeat(2)
    .slice(0, 32)
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    `4${hex.slice(13, 16)}`,
    `8${hex.slice(17, 20)}`,
    hex.slice(20, 32),
  ].join("-")
}

/** Kafelki układu roli rozłożone na siatce (pierwsze wolne miejsce). */
export function roleDefaultTiles(
  user: User | null | undefined,
  options: RoleLayoutOptions = {},
): DashboardTile[] {
  const tiles: DashboardTile[] = []
  for (const entry of roleEntries(user, options)) {
    const { x, y } = firstFreeSpot(tiles, entry.w, entry.h)
    tiles.push({
      id: stableTileId(`role:${entry.template.key}`),
      type: entry.template.type,
      x,
      y,
      w: entry.w,
      h: entry.h,
      config: JSON.parse(JSON.stringify(entry.template.config)),
    })
  }
  return tiles
}

/** Polecenia na pustej karcie (osoba zapisała pusty pulpit). */
export function recommendedTemplates(
  user: User | null | undefined,
  options: RoleLayoutOptions = {},
): {
  roleLabel: string | null
  templates: TileTemplate[]
} {
  return { roleLabel: roleLayoutLabel(user), templates: roleDefaultTemplates(user, options) }
}

/**
 * Nowe kafelki, o których mówimy osobom z JUŻ ułożonym pulpitem — układ roli
 * widzi tylko konto bez zapisu, więc bez tego nowość nie dociera do nikogo
 * (24.09.2026: „Requesty i obłożenie” wdrożone, na 5 pulpitach 0 kafelków).
 */
export const ANNOUNCED_TILES: TileType[] = ["request_board", "today_cycle"]

/** Pierwszy ogłaszany kafelek układu tej roli, którego nie ma na pulpicie. */
export function announcedTile(
  user: User | null | undefined,
  tiles: Pick<DashboardTile, "type">[],
  dismissed: ReadonlySet<string>,
): TileTemplate | null {
  const recommended = roleDefaultTemplates(user)
  for (const type of ANNOUNCED_TILES) {
    if (dismissed.has(type)) continue
    if (tiles.some((t) => t.type === type)) continue
    const template = recommended.find((t) => t.type === type)
    if (template) return template
  }
  return null
}
