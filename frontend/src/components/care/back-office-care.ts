// Opieka przy włączonym module back office (decyzja Artura 20.11.2026): Delivery
// Lead nie jest opiekunem z automatu, a rytmu rozmów nie ma — konsultantów bez
// opiekuna prowadzi kolejka back office'u („Kontakt 7. dnia”, „Co dalej po
// projekcie”). DL-owi zostają sprawy klienta. Bez Reacta, z testem.

import type { ConsultantRow } from "@/lib/api/care";
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
