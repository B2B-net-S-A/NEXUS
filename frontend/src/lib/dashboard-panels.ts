// Listy panelu „Czeka na Ciebie”, które da się usunąć z pulpitu.
//
// „Twoje CV w drodze” usuwa każdy (02.10.2026). Pozostałe listy usuwa
// wyłącznie Head of Recruitment (decyzja Artura 06.10.2026): prowadzi zespół
// i nie każda lista jest dla niego pracą, a panel stał nad kafelkami bez
// możliwości zmiany. Osobom pracującym przy kandydatach listy zostają
// sztywne — zadanie ma do nich dotrzeć, nawet gdy pulpitu nie układały.
//
// Lustro `PANEL_KEYS` i `may_hide_panel` w
// `backend/app/services/dashboard_tiles.py`.

import type { BoardTasksResponse } from "@/lib/api/boardTasks"
import { hasRole, type UserRole } from "@/store/auth"

export const DASHBOARD_PANEL_KEYS = [
  "cv_in_transit",
  "allocation_proposals",
  "new_job_leads",
  "pending_jobs",
  "board_flow",
  "followups",
  "agreements",
  "rate_changes",
  "dl_review",
  "cpro",
  "prep_attention",
] as const

export type DashboardPanelKey = (typeof DASHBOARD_PANEL_KEYS)[number]

export const PANEL_LABELS: Record<DashboardPanelKey, string> = {
  cv_in_transit: "Twoje CV w drodze",
  allocation_proposals: "Propozycje automatu do akceptacji",
  new_job_leads: "Nowe rekrutacje — kto prowadzi",
  pending_jobs: "Rekrutacje do dokończenia albo zamknięcia",
  board_flow: "Praca na Tablicach i zamówienia",
  followups: "Follow-up z kandydatami",
  agreements: "Umowy do potwierdzenia",
  rate_changes: "Zmiany stawek kandydatów",
  dl_review: "Przegląd przed wysłaniem (DL)",
  cpro: "Cpro",
  prep_attention: "Prepy przed rozmową u klienta",
}

/** Role, które mogą usuwać z pulpitu każdą listę panelu. */
export const PANEL_EDIT_ROLES: readonly UserRole[] = ["head_of_recruitment"]

type RoleBearing = Parameters<typeof hasRole>[0]

/** Czy osoba może usunąć daną listę z pulpitu. */
export function canHidePanel(user: RoleBearing, key: DashboardPanelKey): boolean {
  if (key === "cv_in_transit") return true
  return hasRole(user, ...PANEL_EDIT_ROLES)
}

/** Czy osoba może dostosować cały panel (listy poza „CV w drodze”). */
export function canCustomizeBoardPanel(user: RoleBearing): boolean {
  return hasRole(user, ...PANEL_EDIT_ROLES)
}

/** Listy, które osoba naprawdę ukryła — klucz bez prawa do ukrycia się nie liczy. */
export function effectiveHiddenPanels(
  user: RoleBearing,
  stored: readonly string[] | null | undefined,
): Set<DashboardPanelKey> {
  const out = new Set<DashboardPanelKey>()
  for (const key of DASHBOARD_PANEL_KEYS) {
    if (stored?.includes(key) && canHidePanel(user, key)) out.add(key)
  }
  return out
}

/**
 * Kolejka „Czeka na Ciebie” bez list usuniętych z pulpitu. Ukryta lista
 * wygląda dla panelu jak pusta — znika też z liczników („Twój ruch”, „U innych”).
 * „Twoje CV w drodze” wycina serwer, ale tu też, na wypadek starej odpowiedzi.
 */
export function withoutHiddenPanels(
  data: BoardTasksResponse,
  hidden: ReadonlySet<DashboardPanelKey>,
): BoardTasksResponse {
  if (hidden.size === 0) return data
  const next: BoardTasksResponse = { ...data }
  if (hidden.has("cv_in_transit")) next.cv_in_transit = null
  if (hidden.has("allocation_proposals")) next.allocation_proposals = []
  if (hidden.has("new_job_leads")) next.new_job_leads = []
  if (hidden.has("pending_jobs")) {
    next.pending_jobs = null
    next.unfinished_forms = null
  }
  if (hidden.has("board_flow")) {
    next.flow = null
    next.finance = null
  }
  if (hidden.has("followups")) {
    next.followups = []
    next.followups_by_others = []
  }
  if (hidden.has("agreements")) next.agreements = null
  if (hidden.has("rate_changes")) {
    next.rate_changes = []
    next.rate_changes_by_others = []
  }
  if (hidden.has("dl_review")) next.dl_review = []
  if (hidden.has("cpro")) {
    next.cpro_to_send = []
    next.cpro_sent = []
    next.can_set_cpro_sender = false
  }
  if (hidden.has("prep_attention")) next.prep_attention = []
  return next
}
