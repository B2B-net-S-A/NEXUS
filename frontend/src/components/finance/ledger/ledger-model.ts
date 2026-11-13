// Logika ekranów „Koszty” i „Kontrahenci” bez Reacta (testy w __tests__).
//
// Etapy i przejścia liczy serwer (`services/finance_ledger/costs.py`); tu
// tylko to, które przyciski pokazać w zakładce i jak opisać wynik akcji
// zbiorczej, w której część faktur została odmówiona.

import type {
  ActionResult,
  CostAction,
  CostCategory,
  CostFlag,
  CostStage,
  CounterpartyRole,
} from "@/lib/api/finance-ledger";
import { countPl } from "@/lib/plural-pl";

/** Kolejność zakładek jak w makiecie M1 (eBI24: poczekalnia, zadania, statusy). */
export const STAGE_TABS: readonly { stage: CostStage; label: string }[] = [
  { stage: "received", label: "Z KSeF do przyjęcia" },
  { stage: "new", label: "Do opisu" },
  { stage: "verified", label: "Zweryfikowane" },
  { stage: "ready", label: "Gotowe do księgowania" },
  { stage: "booked", label: "Zaksięgowane" },
  { stage: "rejected", label: "Odrzucone" },
];

export const FLAG_LABELS: Record<CostFlag, string> = {
  mpp: "MPP",
  no_mpp: "NIE MPP",
  hold_payment: "Wstrzymać płatność",
  tax_office_account: "Zapłata na konto US",
  duplicate: "Duplikat",
};

export const FLAG_ORDER: readonly CostFlag[] = [
  "mpp",
  "no_mpp",
  "hold_payment",
  "tax_office_account",
  "duplicate",
];

export const CATEGORY_LABELS: Record<CostCategory, string> = {
  contractor: "Kontraktorzy",
  team: "Zespół",
  office: "Biuro",
  benefit: "Benefity",
  proforma: "Proforma",
  other: "Inne",
};

export const CATEGORY_ORDER: readonly CostCategory[] = [
  "contractor",
  "team",
  "office",
  "benefit",
  "proforma",
  "other",
];

export const ROLE_LABELS: Record<CounterpartyRole, string> = {
  client: "klient",
  team: "osoba zespołu",
  contractor: "kontraktor",
  supplier: "dostawca",
};

export interface StageButton {
  action: Exclude<CostAction, "flag_add" | "flag_remove">;
  label: string;
  primary?: boolean;
  /** Akcja pyta o powód (odrzucenie). */
  needsReason?: boolean;
}

/**
 * Przyciski etapu dla faktury (karta) albo zaznaczonych (zakładka).
 * `fromKsef = false` — dokument spoza KSeF nie wraca do poczekalni.
 */
export function stageButtons(stage: CostStage, fromKsef = true): StageButton[] {
  switch (stage) {
    case "received":
      return [
        { action: "reject", label: "Odrzuć", needsReason: true },
        { action: "accept", label: "Przyjmij", primary: true },
      ];
    case "new":
      return [
        ...(fromKsef ? [{ action: "back" as const, label: "Cofnij do poczekalni" }] : []),
        { action: "reject", label: "Odrzuć", needsReason: true },
        { action: "verify", label: "Zweryfikuj", primary: true },
      ];
    case "verified":
      return [
        { action: "back", label: "Cofnij o krok" },
        { action: "ready", label: "Gotowa do księgowania", primary: true },
      ];
    case "ready":
      return [{ action: "back", label: "Cofnij o krok" }];
    case "rejected":
      return [{ action: "back", label: "Przywróć" }];
    case "booked":
      return [];
  }
}

/** Etykieta przycisku zbiorczego: „Przyjmij zaznaczone (3)”. */
export function bulkLabel(button: StageButton, count: number): string {
  return `${button.label} zaznaczone (${count})`;
}

/** Toast po akcji: ile zmieniono i dlaczego reszta nie przeszła. */
export function describeResult(result: ActionResult): { text: string; tone: "success" | "info" } {
  const changed = countPl(result.changed, "faktura", "faktury", "faktur");
  if (result.refused.length === 0) {
    return { text: `Zmieniono: ${changed}.`, tone: "success" };
  }
  const reasons = Array.from(new Set(result.refused.map((item) => item.detail)));
  const refused = countPl(result.refused.length, "faktura", "faktury", "faktur");
  return {
    text: `Zmieniono: ${changed}. Bez zmiany: ${refused} — ${reasons.join(" ")}`,
    tone: "info",
  };
}

/** Zaznaczenie po kliknięciu „wszystkie”: zaznacza widoczne albo czyści. */
export function toggleAll(selected: ReadonlySet<number>, visible: readonly number[]): Set<number> {
  const allOn = visible.length > 0 && visible.every((id) => selected.has(id));
  return allOn ? new Set() : new Set(visible);
}

/** Zaznaczone, które są nadal na liście (po odświeżeniu po akcji). */
export function keepVisible(selected: ReadonlySet<number>, visible: readonly number[]): Set<number> {
  const ids = new Set(visible);
  return new Set(Array.from(selected).filter((id) => ids.has(id)));
}

/** Ostatnie 12 miesięcy (`YYYY-MM`) do filtra wpływu, od bieżącego. */
export function recentMonths(today: string, count = 12): string[] {
  const [year, month] = today.split("-").map(Number);
  const months: string[] = [];
  for (let back = 0; back < count; back += 1) {
    const index = year * 12 + (month - 1) - back;
    const y = Math.floor(index / 12);
    const m = (index % 12) + 1;
    months.push(`${y}-${String(m).padStart(2, "0")}`);
  }
  return months;
}
