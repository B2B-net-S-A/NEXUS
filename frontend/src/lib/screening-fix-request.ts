/**
 * Prośba Delivery Leada o poprawki w formularzu screeningu (D6, 08.10.2026).
 *
 * Serwer mówi, które pola DL wskazał i które są już „poprawione” (różnią się
 * od stanu z chwili prośby — `fix_request.fields[].changed`). Tu tylko reguła
 * stanu pola na ekranie: zapisana poprawka wygrywa, potem niezapisana zmiana
 * w formularzu („zmienione — zapisz”), na końcu „do poprawy”.
 */

import type { ScreeningFixRequest } from "@/lib/api/screeningForm";

export type FixFieldState = "todo" | "edited" | "done";

export const FIX_STATE_LABEL: Record<FixFieldState, string> = {
  todo: "Do poprawy",
  edited: "Zmienione — zapisz",
  done: "Poprawione",
};

type DirtyTree = Record<string, unknown> | undefined;

function hasDirty(node: unknown): boolean {
  if (node === true) return true;
  if (node && typeof node === "object") return Object.values(node).some(hasDirty);
  return false;
}

/** Czy pole o kluczu prośby ma niezapisaną zmianę (`dirtyFields` react-hook-form). */
export function fixFieldDirty(key: string, dirty: DirtyTree): boolean {
  if (!dirty) return false;
  if (key.startsWith("question:")) {
    const id = key.slice("question:".length);
    return hasDirty((dirty.answers as DirtyTree)?.[id]);
  }
  if (key === "field:overall_fit") return hasDirty(dirty.overall_fit);
  if (key.startsWith("field:")) return hasDirty((dirty.card as DirtyTree)?.[key.slice("field:".length)]);
  if (key === "candidate_rate") return hasDirty(dirty.rate_amount) || hasDirty(dirty.rate_unit);
  return false;
}

export function fixFieldState(
  request: ScreeningFixRequest | null | undefined,
  key: string,
  dirty: DirtyTree,
): FixFieldState | null {
  const field = request?.fields.find((f) => f.key === key);
  if (!field) return null;
  if (field.changed) return "done";
  return fixFieldDirty(key, dirty) ? "edited" : "todo";
}
