/**
 * Podpis pod nazwą kolumny Tablicy = „co tu robisz" (Rekrutacja v5,
 * 24.09.2026). Do tego dnia druga linia mówiła „SLA: —" albo „→ CV do
 * klienta" — także w „Zweryfikowany" i „QC CV", choć od v5 następną kolumną
 * po weryfikacji jest QC CV, nie klient.
 *
 * Czysty moduł bez renderu. Informację o SLA / najstarszej karcie
 * (`columnSlaHint`) kolumna pokazuje dalej — po prawej stronie tej linii.
 */

import type { BoardColumnKey } from "@/lib/board-stages";

export interface ColumnPurposeContext {
  /** Nordea: „CV wysłane" to „Wysłane do Cpro". */
  cproEnabled?: boolean;
  /** Zatrudnieni w kolumnie „Zatrudniony" (obsada N / M). */
  hired?: number | null;
  /** Obsada z rekrutacji; `null` = nie ustawiono. */
  headcount?: number | null;
}

const PURPOSE: Partial<Record<BoardColumnKey, string>> = {
  new: "Przejrzyj, zadzwoń, kliknij „Biorę”",
  screening: "Arkusz pytań z Championa",
  verified: "Stawka ✓ → przygotuj CV do QC",
  cv_qc: "Popraw CV, potem wyślij",
  cv_sent: "Czekamy na klienta",
  client_interview: "Prep → rozmowa → telefon",
  contract: "Podpis umowy",
};

/**
 * „Co tu robisz" dla kolumny Tablicy; `null` dla własnego etapu szablonu
 * (bez znanego znaczenia) i zamkniętych — wtedy zostaje dawna linia SLA.
 */
export function boardColumnPurpose(
  key: BoardColumnKey | null | undefined,
  ctx: ColumnPurposeContext = {},
): string | null {
  if (!key || key === "closed") return null;
  if (key === "hired") {
    return `Obsada ${ctx.hired ?? "—"} / ${ctx.headcount ?? "—"}`;
  }
  if (key === "cv_sent" && ctx.cproEnabled) {
    return "CV w Cpro — czekamy na klienta";
  }
  if (key === "cv_qc" && ctx.cproEnabled) {
    return "Popraw CV, potem przekaż do Cpro";
  }
  return PURPOSE[key] ?? null;
}
