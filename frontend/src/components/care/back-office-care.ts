// Opieka przy włączonym module back office (decyzja Artura 20.11.2026): Delivery
// Lead nie jest opiekunem z automatu, a rytmu rozmów nie ma — konsultantów bez
// opiekuna prowadzi kolejka back office'u („Kontakt 7. dnia”, „Co dalej po
// projekcie”). DL-owi zostają sprawy klienta. Bez Reacta, z testem.

import type { CardPlanItem, ConsultantRow } from "@/lib/api/care";
import type { HrConfig } from "@/lib/api/hr";

export const BACK_OFFICE_CARE_DESCRIPTION =
  "Opinie menedżerów, popyt i dane Twoich klientów. Konsultantów bez opiekuna prowadzi kolejka back office'u.";

export const BACK_OFFICE_CARE_NOTE =
  "Rozmowy z konsultantami bez opiekuna, kontakt 7. dnia i „co dalej po projekcie” prowadzi kolejka back office'u. Tu zostają sprawy klienta: opinie menedżerów, popyt i dane klienta.";

/** Moduł back office włączony: ekrany Opieki bez rytmu rozmów. */
export function careWithoutRhythm(config: Pick<HrConfig, "open_modules">): boolean {
  return config.open_modules.back_office === true;
}

/**
 * Bez podopiecznych przy module back office — zakres „Moi” byłby pusty, więc
 * listy pokazują cały zakres czytającego. `null` = lista jeszcze się nie wczytała.
 */
export function withoutWards(
  withoutRhythm: boolean,
  items: readonly Pick<ConsultantRow, "is_mine">[] | null,
): boolean {
  return withoutRhythm && items !== null && !items.some((row) => row.is_mine);
}

/**
 * Chip „Moi podopieczni”: przy module back office tylko, gdy czytający ma
 * podopiecznych albo chip jest włączony (da się go wyłączyć). `null` = liczba
 * jeszcze nieznana.
 */
export function showMineCareChip(withoutRhythm: boolean, count: number | null, active: boolean): boolean {
  if (!withoutRhythm) return true;
  return active || (count ?? 0) > 0;
}

/**
 * Karta liczy się do „Moich podopiecznych”. Przy module back office tylko karty
 * konsultanta (rozmowa, decyzja) — opinię, popyt i dane klienta prowadzi DL
 * klienta jako sprawę klienta, nie podopiecznego.
 */
export function countsAsWard(kind: string, withoutRhythm: boolean): boolean {
  return !withoutRhythm || kind === "contact" || kind === "decision";
}

type PlanPoint = Pick<CardPlanItem, "kind" | "status" | "due_on">;

/**
 * Punkt planu kontaktów „po terminie”. Przy module back office rozmowa z rytmu
 * (`cadence`, punkty sprzed modułu — plan już ich nie tworzy) nie jest zaległa:
 * rytmu nie ma, a takie punkty zamyka krok 5 runbooka back office'u.
 */
export function planItemOverdue(item: PlanPoint, today: string, withoutRhythm: boolean): boolean {
  if (item.status !== "open" || item.due_on >= today) return false;
  return !(withoutRhythm && item.kind === "cadence");
}

/**
 * „Najbliższy” punkt w nagłówku planu kontaktów (`open` posortowane od
 * najwcześniejszego). Przy module back office pomija rozmowy z rytmu sprzed
 * dziś — inaczej „najbliższy” wskazywałby datę sprzed tygodni.
 */
export function nearestPlanItem<T extends PlanPoint>(open: readonly T[], today: string, withoutRhythm: boolean): T | null {
  if (!withoutRhythm) return open[0] ?? null;
  return open.find((item) => !(item.kind === "cadence" && item.due_on < today)) ?? null;
}
