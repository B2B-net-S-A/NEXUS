/**
 * „Szybkie poprawki” w panelu „Do poprawy” (E1, 07.11.2026) — czysta logika.
 *
 * Pomiar 266 CV z generatora (07.11.2026): rekruterzy ręcznie rozbijają języki
 * „English - B2 · Polish - native” na osobne linie. Tu tylko wykrycie i podgląd
 * zmiany na bieżącym dokumencie edytora; zmianę liczy serwer kodem, bez AI
 * (`qc/transform`, `cv_qc.languages_lines_html`) — ta sama droga co „Pogrub
 * wymagania”. Reguły są lustrem serwera; gdy podgląd i serwer się rozminą,
 * serwer odpowiada „nic do zrobienia” i panel to mówi.
 *
 * Działa na każdej treści w edytorze — także CV wgranym z Worda (21%
 * zatwierdzonych CV nie jest z generatora): sekcję rozpoznaje znacznik
 * nagłówka albo jego tytuł (`cvOutline`). Pogrubianie początku punktów
 * podsumowania Artur odłożył do pomiaru (07.11.2026). Moduł nie importuje
 * `@tiptap/react`.
 */

import type { Node as PMNode } from "@tiptap/pm/model";

import type { QcFixAction } from "@/lib/api/cvQc";
import { cvOutline, isRodoNode, type CvOutline } from "@/lib/cv-editor-blocks";
import type { IssueRange } from "@/lib/cv-editor-issues";

export type QuickFixAction = Extract<QcFixAction, { action: "languages_lines" }>;

export interface QuickFix {
  action: "languages_lines";
  /** Ile akapitów zostanie rozbitych. */
  count: number;
  /** Pierwszy taki akapit: tekst dziś i linie po poprawce. */
  before: string;
  after: string[];
  where: IssueRange;
}

/** Akapity szablonu, których poprawki nie dotykają (lustro `cv_qc._NON_CONTENT_SECTIONS`). */
const NON_CONTENT = new Set(["role", "employer", "duties_label", "considered", "rodo"]);

// Lustro `cv_qc._LANG_*` (pozycja ≤ 80 znaków, separator łącznikiem lub pauzą).
const LANG_PART_MAX = 80;
const LANG_DASH = /(?<!\s)[^\S\n]+[-—][^\S\n]+(?=\S)/g;
const LANG_PARENS = /^([^():–—]{1,60}?)[^\S\n]*\(([^()]{1,40})\)$/;
const LANG_COLON = /^([^\s:][^:–—]{0,39}):[^\S\n]*(\S.{0,59})$/;

/** „English - B2”, „English (B2)”, „English: B2” → „English – B2”; bez dopisywania. */
export function languagePart(part: string, plain = true): string {
  if (!plain) return part.trim().replace(LANG_DASH, " – ");
  const text = part.split(/\s+/).filter(Boolean).join(" ");
  if (text.length > LANG_PART_MAX) return text;
  const dashed = text.replace(LANG_DASH, " – ");
  const match = LANG_PARENS.exec(dashed) ?? LANG_COLON.exec(dashed);
  return match ? `${match[1].trim()} – ${match[2].trim()}` : dashed;
}

/** Akapit z formatowaniem albo złamaniem linii — serwer dzieli go w węzłach i poprawia tylko łącznik. */
function hasMarks(node: PMNode): boolean {
  let marked = false;
  node.forEach((child) => {
    if (child.marks.length > 0 || !child.isText) marked = true;
  });
  return marked;
}

function languagesFix(outline: CvOutline): QuickFix | null {
  let first: QuickFix | null = null;
  let count = 0;
  for (const block of outline.blocks) {
    const { node } = block;
    if (block.section !== "languages" || node.type.name !== "paragraph" || isRodoNode(node)) continue;
    if (block.marker && NON_CONTENT.has(block.marker)) continue;
    const text = node.textContent;
    const parts = text.split("·").filter((part) => part.trim() !== "");
    if (parts.length < 2) continue;
    count += 1;
    first ??= {
      action: "languages_lines",
      count: 0,
      before: text.trim(),
      after: parts.map((part) => languagePart(part, !hasMarks(node))),
      where: { from: block.from, to: block.to, block: true },
    };
  }
  return first ? { ...first, count } : null;
}

/** Szybkie poprawki, które coś zmienią w tym dokumencie (w kolejności panelu). */
export function quickFixes(doc: PMNode, outline: CvOutline = cvOutline(doc)): QuickFix[] {
  const languages = languagesFix(outline);
  return languages ? [languages] : [];
}

export function quickFixAction(fix: QuickFix): QuickFixAction {
  return { action: fix.action };
}

/** Wiersz grupy „Poprawione”. */
export function quickFixLabel(action: QuickFixAction["action"]): string {
  switch (action) {
    case "languages_lines":
      return "Języki w osobnych liniach";
  }
}
