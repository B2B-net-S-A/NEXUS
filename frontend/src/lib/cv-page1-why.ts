/**
 * Zdania 1–3 „Dlaczego nasz kandydat” na stronie 1 nowego CV (25.11.2026).
 *
 * Lustro `services/cv_layout.compose_page1_why` i `cv_page1_why_checks`:
 * `page1_extras.why` to trzy sloty — sprawdzone zdanie generatora strony 1
 * (`why_generated`, model + kontrola kodem) albo zdanie poprawione przez
 * rekrutera. Pusty slot bierze to, co strona 1 brała dotąd: punkt 1 i 2 z CV,
 * w slocie 3 najmocniejszy wynik, a bez niego punkt 3 z CV.
 */

import type { CvPage1Extras, CvPage1WhyGenerated } from "@/lib/api";

export const WHY_SLOTS = 3;

/** Wynik z modelu niesie pogrubienia jako `**…**`; pole pokazuje czysty tekst. */
export function plainText(text: string | null | undefined): string {
  return (text ?? "").replace(/\*\*(.+?)\*\*/g, "$1");
}

function oneLine(text: unknown): string {
  return typeof text === "string" ? text.split(/\s+/).filter(Boolean).join(" ") : "";
}

/** `why` jako trzy sloty; `""` = slot bierze punkt z CV. */
export function whySlots(extras: CvPage1Extras | null | undefined): string[] {
  const why = Array.isArray(extras?.why) ? extras.why : [];
  return Array.from({ length: WHY_SLOTS }, (_, index) => oneLine(why[index]));
}

/** Wpis generatora dla slotu (także niesprawdzony — edytor mówi, czemu odpadł). */
export function generatedFor(
  extras: CvPage1Extras | null | undefined,
  index: number,
): CvPage1WhyGenerated | null {
  const generated = extras?.why_generated;
  return Array.isArray(generated) ? (generated[index] ?? null) : null;
}

/** Sprawdzone zdania generatora per slot; `""` = brak. */
export function autoTexts(extras: CvPage1Extras | null | undefined): string[] {
  return Array.from({ length: WHY_SLOTS }, (_, index) => {
    const item = generatedFor(extras, index);
    return item?.verified === true ? (item.text ?? "").trim() : "";
  });
}

/** Najmocniejszy wynik dla slotu 3 — lustro `cv_layout.chosen_result`. */
export function chosenResultText(extras: CvPage1Extras | null | undefined): string {
  const typed = extras?.result_text?.trim();
  if (typed) return typed;
  const results = extras?.results ?? [];
  if (!results.length) return "";
  const raw = extras?.result_index;
  const index = typeof raw === "number" && raw >= 0 && raw < results.length ? raw : 0;
  const result = results[index];
  return result?.verified === true ? (result.text ?? "").trim() : "";
}

/** Co stoi w slocie bez zdania: punkt 1 / 2 z CV, w slocie 3 wynik albo punkt 3. */
export function fallbackTexts(points: string[], extras: CvPage1Extras | null | undefined): string[] {
  const clean = points.map((point) => point.trim()).filter(Boolean);
  return [clean[0] ?? "", clean[1] ?? "", chosenResultText(extras) || clean[2] || ""];
}

/** Trzy zdania strony 1 tak, jak je złoży render (bez pustych). */
export function page1Sentences(points: string[], extras: CvPage1Extras | null | undefined): string[] {
  const slots = whySlots(extras);
  const fallback = fallbackTexts(points, extras);
  return slots.map((slot, index) => slot || fallback[index]).filter(Boolean);
}

/** Slot poprawiony przez rekrutera: ma zdanie i nie jest to sprawdzone zdanie generatora. */
export function isEdited(extras: CvPage1Extras | null | undefined, index: number): boolean {
  const slot = whySlots(extras)[index];
  return Boolean(slot) && slot !== autoTexts(extras)[index];
}

/** `why` do `PATCH …/cv/page1`: zmienia jeden slot, pozostałe `null` (bez zmiany). */
export function whyPatch(index: number, text: string): (string | null)[] {
  return Array.from({ length: WHY_SLOTS }, (_, slot) => (slot === index ? text : null));
}
