// Kartoteka → „Nieobecności i godziny” — czyste funkcje (bez Reacta).

import type { EmploymentType, LeaveEntitlementRow } from "@/lib/api/hr";
import type { AbsenceState, PersonTimesheetMonth } from "@/lib/api/hr-person-history";
import type { QueueStatus } from "@/lib/api/hr-time";

import type { TodayTone } from "./directory-view";
import { formatDays } from "./hr-format";
import type { RingParts } from "./person-view";

export const ABSENCE_STATE_LABEL: Record<AbsenceState, string> = {
  planned: "zaplanowana",
  waiting: "czeka",
  used: "wykorzystana",
  rejected: "odrzucona",
};

export const ABSENCE_STATE_TONE: Record<AbsenceState, TodayTone> = {
  planned: "info",
  waiting: "warning",
  used: "neutral",
  rejected: "neutral",
};

/** Status raportu w wierszu kartoteki — brak raportu to „nie założony”. */
export function timesheetStatus(item: PersonTimesheetMonth): QueueStatus {
  return item.status ?? "missing";
}

/**
 * Linia puli nad listą nieobecności — z danych kartoteki (saldo serwera,
 * wiersz puli Kadr). Bez słowa „urlop”: forma bywa ukryta (Kadry bez Płac).
 */
export function poolSummary({
  form,
  ring,
  entitlement,
  year,
}: {
  form: EmploymentType | null | undefined;
  ring: RingParts | null;
  entitlement: LeaveEntitlementRow | undefined;
  year: number;
}): string {
  if (form === "zlecenie") {
    return "Na umowie zlecenie nie ma puli płatnych dni — nieobecność jest bez wynagrodzenia.";
  }
  if (ring) {
    return [
      `Pula ${formatDays(ring.pool)} dni`,
      `wykorzystane ${formatDays(ring.used)}`,
      ...(ring.planned > 0 ? [`zaplanowane ${formatDays(ring.planned)}`] : []),
      `zostało ${formatDays(ring.remaining)}`,
    ].join(" · ");
  }
  if (entitlement) {
    return [
      entitlement.entitlement_days == null
        ? "Bez puli płatnych dni"
        : `Pula na rok ${formatDays(entitlement.entitlement_days)} dni`,
      `zaległe ${formatDays(entitlement.carried_over_days)}`,
      `przed NEXUSEM ${formatDays(entitlement.used_initial_days)}`,
    ].join(" · ");
  }
  return `Pula na ${year} nie jest ustawiona.`;
}

/** „7,5 / 168 h” — godziny wobec normy miesiąca. */
export function hoursOfNorm(item: PersonTimesheetMonth): string {
  const fmt = (value: number) => value.toLocaleString("pl-PL", { maximumFractionDigits: 2 });
  return `${fmt(item.hours)} / ${fmt(item.norm_hours)} h`;
}

/**
 * Powrót „← Ludzie”: poprzedni wpis historii karty, gdy był to katalog
 * (`/people` z filtrami w adresie). `null` = brak takiego wpisu — link
 * prowadzi na goły `/people`.
 */
export function previousPeopleList(
  previousUrl: string | null | undefined,
  origin: string,
): string | null {
  if (!previousUrl) return null;
  try {
    const url = new URL(previousUrl, origin);
    if (url.origin !== origin) return null;
    const path = url.pathname.replace(/\/+$/, "") || "/";
    return path === "/people" ? `${path}${url.search}` : null;
  } catch {
    return null;
  }
}
