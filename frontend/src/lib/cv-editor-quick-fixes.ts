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
 * podsumowania Artur odłożył do pomiaru (07.11.2026).
 *
 * Tytuł z numerem zapytania (G3, #3134): gdy reguła CV klienta go chce, serwer
 * podaje nagłówek (`header_title` w uwagach edytora), a istniejąca poprawka
 * `title` go wpisuje — tylko w układzie generatora „Rola – Imię” (lustro
 * `cv_qc.set_title_html`). Moduł nie importuje `@tiptap/react`.
 */

import type { Node as PMNode } from "@tiptap/pm/model";

import type { QcFixAction } from "@/lib/api/cvQc";
import { cvOutline, isRodoNode, type CvOutline } from "@/lib/cv-editor-blocks";
import type { IssueRange } from "@/lib/cv-editor-issues";

export type QuickFixAction = Extract<QcFixAction, { action: "languages_lines" | "title" }>;

export interface QuickFix {
  action: QuickFixAction["action"];
  /** Ile akapitów zostanie zmienionych. */
  count: number;
  /** Pierwszy taki akapit: tekst dziś i linie po poprawce. */
  before: string;
  after: string[];
  where: IssueRange;
}

export interface QuickFixContext {
  /** Nagłówek z numerem zapytania z reguły klienta (`header_title`); brak = bez wiersza tytułu. */
  headerTitle?: string | null;
  /** Imię i nazwisko kandydata (z QC) — po nim poznajemy układ „Rola – Imię”. */
  candidateName?: string | null;
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

// Lustro `cv_qc._TITLE_SEPARATOR`, `_NAME_WORD` i `_norm`.
const TITLE_SEPARATOR = /(?<!\s)\s+[–—|-](?=\s)/g;
const NAME_WORD = /\p{L}{2,}/gu;

function nameWords(text: string): Set<string> {
  return new Set(text.toLocaleLowerCase("pl").match(NAME_WORD) ?? []);
}

function norm(text: string): string {
  return text.replaceAll("**", "").split(/\s+/).filter(Boolean).join(" ").toLocaleLowerCase("pl");
}

/** Nagłówek „Rola – Imię” z rolą bez numeru → tytuł z reguły klienta (lustro `cv_qc.set_title_html`). */
function titleFix(outline: CvOutline, context: QuickFixContext): QuickFix | null {
  const title = (context.headerTitle ?? "").split(/\s+/).filter(Boolean).join(" ").slice(0, 200);
  const name = nameWords(context.candidateName ?? "");
  if (!title || name.size === 0) return null;
  const head = outline.blocks.find((block) => block.node.type.name === "heading" && Number(block.node.attrs.level) === 1);
  if (!head) return null;
  const text = head.node.textContent;
  const seps = [...text.matchAll(TITLE_SEPARATOR)];
  const sep = seps.at(-1);
  if (!sep || sep.index === undefined) return null;
  const left = text.slice(0, sep.index);
  const right = text.slice(sep.index + sep[0].length);
  const overlaps = (words: Set<string>) => [...words].some((word) => name.has(word));
  if (!overlaps(nameWords(right)) || overlaps(nameWords(left))) return null;
  const role = left.trim();
  if (!role || norm(role) === norm(title)) return null;
  return {
    action: "title",
    count: 1,
    before: text.trim(),
    after: [`${title}${text.slice(sep.index)}`.trim()],
    where: { from: head.from, to: head.to, block: true },
  };
}

/** Szybkie poprawki, które coś zmienią w tym dokumencie (w kolejności panelu). */
export function quickFixes(
  doc: PMNode,
  context: QuickFixContext = {},
  outline: CvOutline = cvOutline(doc),
): QuickFix[] {
  return [titleFix(outline, context), languagesFix(outline)].filter((fix): fix is QuickFix => fix !== null);
}

export function quickFixAction(fix: QuickFix): QuickFixAction {
  return { action: fix.action };
}

/** Wiersz grupy „Poprawione”. */
export function quickFixLabel(action: QuickFixAction["action"]): string {
  switch (action) {
    case "languages_lines":
      return "Języki w osobnych liniach";
    case "title":
      return "Tytuł z numerem zapytania";
  }
}
