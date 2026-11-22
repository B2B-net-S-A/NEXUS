/**
 * Formularze „Strona 1” i „Stanowiska” w edytorze nowego CV (22.11.2026) —
 * czysta logika: pole ↔ akapit dokumentu edytora.
 *
 * Formularz nie ma własnej kopii treści. Każde pole czyta tekst akapitu
 * z dokumentu Tiptapa i pisze do niego transakcją, więc Word i PDF zostają
 * jedną treścią, a autozapis, historia cofania i QC działają jak przy
 * pisaniu na kartce (`docs/claude/generator-cv/edytor-cv-pelny-ekran.md`).
 *
 * - Zmiana tekstu to NAJMNIEJSZA podmiana (wspólny początek i koniec zostają),
 *   więc pogrubienia wokół zmienionego fragmentu nie giną — jak przy pisaniu.
 * - Stanowisko trzyma gramatykę szablonu Worda: nazwa to pogrubiony początek
 *   akapitu `role`, daty — reszta; firma to akapit `employer` tuż po nim;
 *   etykieta technologii ma dokładny tekst `CV_TEMPLATE_LABELS`.
 * - Moduł nie importuje `@tiptap/react`.
 */

import type { Mark, Node as PMNode, Schema } from "@tiptap/pm/model";
import { Fragment } from "@tiptap/pm/model";
import type { EditorState, Transaction } from "@tiptap/pm/state";

import { currentMonthIndex, monthsText, unionMonths } from "./client-form-years";
import {
  CV_TEMPLATE_LABELS,
  cvOutline,
  splitLeadingBold,
  type CvBlock,
  type CvCommand,
  type CvLang,
  type CvOutline,
  type CvRole,
  type CvSectionKey,
} from "./cv-editor-blocks";
import { countForm } from "./cv-qc";

// ── Tekst akapitu ────────────────────────────────────────────────────────────

/** Pole formularza ma jedną linię treści — akapit CV nie niesie nowych linii. */
export function fieldText(value: string): string {
  return value.replace(/\s*[\r\n]+\s*/g, " ");
}

/** Pozycja w dokumencie dla znaku `offset` tekstu akapitu stojącego na `nodePos`. */
function positionAt(node: PMNode, nodePos: number, offset: number): number {
  let position = nodePos + 1;
  let left = offset;
  for (let i = 0; i < node.childCount; i += 1) {
    const child = node.child(i);
    if (child.isText) {
      const length = child.text?.length ?? 0;
      if (left <= length) return position + left;
      left -= length;
    } else if (left === 0) {
      return position;
    }
    position += child.nodeSize;
  }
  return position;
}

/**
 * Podmienia znaki `[start, end)` tekstu akapitu na `next`, zmieniając tylko
 * to, co się różni. `marks` wymusza znaczniki wstawianego tekstu (nazwa
 * stanowiska zawsze pogrubiona); bez nich wstawka bierze znaczniki z miejsca
 * wstawienia, jak przy pisaniu.
 */
function replaceText(
  tr: Transaction,
  nodePos: number,
  start: number,
  end: number,
  next: string,
  marks?: readonly Mark[],
): boolean {
  const node = tr.doc.nodeAt(nodePos);
  if (!node || !node.isTextblock) return false;
  const current = node.textContent.slice(start, end);
  if (current === next) return false;
  let prefix = 0;
  const max = Math.min(current.length, next.length);
  while (prefix < max && current[prefix] === next[prefix]) prefix += 1;
  let suffix = 0;
  while (
    suffix < max - prefix &&
    current[current.length - 1 - suffix] === next[next.length - 1 - suffix]
  ) {
    suffix += 1;
  }
  const from = positionAt(node, nodePos, start + prefix);
  const to = positionAt(node, nodePos, end - suffix);
  const middle = next.slice(prefix, next.length - suffix);
  if (!middle) {
    tr.delete(from, to);
    return true;
  }
  const text = node.textContent;
  const glue = {
    before: WORD.test(text[start + prefix - 1] ?? "") && WORD.test(middle[0]),
    after: WORD.test(text[end - suffix] ?? "") && WORD.test(middle[middle.length - 1]),
  };
  tr.replaceWith(from, to, tr.doc.type.schema.text(middle, marks ?? marksFor(tr.doc, from, to, glue)));
  return true;
}

const WORD = /[\p{L}\p{N}]/u;

/**
 * Znaczniki wstawki z pola bez formatowania. Podmiana bierze znaczniki
 * pierwszego zastępowanego znaku; dopisek doklejony do słowa — znaczniki tego
 * słowa („7 lat” → „17 lat” zostaje pogrubione); inny dopisek — tylko te,
 * które ma tekst po obu stronach. Pole nie pokazuje pogrubienia, więc
 * „, Docker” za pogrubioną „Kafką” nie może po cichu stać się pogrubione.
 */
function marksFor(
  doc: PMNode,
  from: number,
  to: number,
  glue: { before: boolean; after: boolean },
): readonly Mark[] {
  const at = doc.resolve(from);
  if (to > from) return at.nodeAfter?.marks ?? [];
  const before = at.nodeBefore?.marks ?? [];
  const after = at.nodeAfter?.marks ?? [];
  if (glue.before) return before;
  if (glue.after) return after;
  return before.filter((mark) => mark.isInSet(after));
}

function setParagraphText(state: EditorState, nodePos: number, value: string): Transaction | null {
  const node = state.doc.nodeAt(nodePos);
  if (!node) return null;
  const tr = state.tr;
  return replaceText(tr, nodePos, 0, node.textContent.length, fieldText(value)) ? tr : null;
}

// ── „Dlaczego nasz kandydat” ─────────────────────────────────────────────────

export interface CvWhyPoint {
  text: string;
  /** Pozycja akapitu punktu w dokumencie (przed węzłem). */
  pos: number;
}

function isList(node: PMNode): boolean {
  return node.type.name === "bulletList" || node.type.name === "orderedList";
}

/** Akapity punktów listy stojącej na `listPos` (pierwszy akapit każdego punktu). */
function listParagraphs(list: PMNode, listPos: number): CvWhyPoint[] {
  const points: CvWhyPoint[] = [];
  list.forEach((item, offset) => {
    const first = item.firstChild;
    if (!first || !first.isTextblock) return;
    points.push({ text: first.textContent, pos: listPos + 1 + offset + 1 });
  });
  return points;
}

function sectionBlocks(outline: CvOutline, key: CvSectionKey): CvBlock[] {
  const section = outline.sections.find((candidate) => candidate.key === key);
  return section ? outline.blocks.slice(section.headingIndex + 1, section.endIndex) : [];
}

/** Punkty sekcji „Dlaczego nasz kandydat” w kolejności CV (te same co w Wordzie). */
export function whyPoints(doc: PMNode): CvWhyPoint[] {
  return sectionBlocks(cvOutline(doc), "why_points")
    .filter((block) => isList(block.node))
    .flatMap((block) => listParagraphs(block.node, block.from));
}

/** Punkt `index` (od zera) „Dlaczego nasz kandydat” = nowy tekst. */
export function setWhyPoint(index: number, value: string): CvCommand {
  return (state) => {
    const point = whyPoints(state.doc)[index];
    return point ? setParagraphText(state, point.pos, value) : null;
  };
}

// ── Stanowiska ───────────────────────────────────────────────────────────────

export interface CvRoleFields {
  /** Numer stanowiska w CV (od zera, kolejność `cvOutline`). */
  index: number;
  title: string;
  /** Daty z linii stanowiska („03.2021 – 06.2024”). */
  period: string;
  /** Akapit `employer` tuż po stanowisku; `null`, gdy go nie ma. */
  company: string | null;
  duties: string[];
  /** Tekst po etykiecie „Technologie:”; `null`, gdy stanowisko nie ma tego akapitu. */
  technologies: string | null;
}

interface RoleParts {
  role: CvRole;
  line: CvBlock;
  employer: CvBlock | null;
  label: CvBlock | null;
  list: CvBlock | null;
  technologies: CvBlock | null;
}

function roleParts(outline: CvOutline, index: number): RoleParts | null {
  const role = outline.roles[index];
  if (!role) return null;
  const blocks = outline.blocks.slice(role.fromIndex, role.toIndex);
  const line = blocks[0];
  return {
    role,
    line,
    employer: blocks[1]?.marker === "employer" ? blocks[1] : null,
    label: blocks.find((block) => block.marker === "duties_label") ?? null,
    list: blocks.find((block) => isList(block.node)) ?? null,
    technologies: blocks.find((block) => block.marker === "technologies") ?? null,
  };
}

const TECH_LABELS = Object.values(CV_TEMPLATE_LABELS).map((labels) => labels.technologies);

/** Etykieta technologii na początku akapitu (PL albo EN) i jej długość z odstępem. */
function techLabelLength(text: string): number {
  const label = TECH_LABELS.find((candidate) => text.startsWith(candidate));
  if (!label) return 0;
  return label.length + (text[label.length] === " " ? 1 : 0);
}

export function roleFields(doc: PMNode, index: number): CvRoleFields | null {
  const parts = roleParts(cvOutline(doc), index);
  if (!parts) return null;
  const { lead, rest } = splitLeadingBold(parts.line.node);
  const tech = parts.technologies?.node.textContent ?? null;
  return {
    index,
    title: lead.trim(),
    period: rest.trim(),
    company: parts.employer ? parts.employer.node.textContent : null,
    duties: parts.list ? listParagraphs(parts.list.node, parts.list.from).map((point) => point.text) : [],
    technologies: tech === null ? null : tech.slice(techLabelLength(tech)),
  };
}

export function allRoleFields(doc: PMNode): CvRoleFields[] {
  return cvOutline(doc).roles.flatMap((_, index) => roleFields(doc, index) ?? []);
}

/** Długość pogrubionego początku linii stanowiska (w znakach tekstu). */
function leadLength(node: PMNode): number {
  return splitLeadingBold(node).lead.length;
}

function boldMarks(schema: Schema, node: PMNode): readonly Mark[] {
  const first = node.firstChild;
  const bold = schema.marks.bold.create();
  if (first?.isText && first.marks.some((mark) => mark.type === schema.marks.bold)) return first.marks;
  return [bold];
}

export function setRoleTitle(index: number, value: string): CvCommand {
  return (state) => {
    const parts = roleParts(cvOutline(state.doc), index);
    if (!parts) return null;
    const node = parts.line.node;
    const lead = leadLength(node);
    const text = fieldText(value);
    const tr = state.tr;
    // Bez pogrubionego początku serwer nie da „Stanowisko:” — nazwa zawsze pogrubiona,
    // a od dat oddziela ją odstęp.
    const restStartsWithSpace = /^\s/.test(node.textContent.slice(lead));
    const next = lead === 0 && text && !restStartsWithSpace && node.textContent.length > 0 ? `${text} ` : text;
    return replaceText(tr, parts.line.from, 0, lead, next, boldMarks(state.schema, node)) ? tr : null;
  };
}

export function setRolePeriod(index: number, value: string): CvCommand {
  return (state) => {
    const parts = roleParts(cvOutline(state.doc), index);
    if (!parts) return null;
    const node = parts.line.node;
    const lead = leadLength(node);
    const text = fieldText(value);
    const tr = state.tr;
    return replaceText(tr, parts.line.from, lead, node.textContent.length, text ? ` ${text}` : "", [])
      ? tr
      : null;
  };
}

export function setRoleCompany(index: number, value: string): CvCommand {
  return (state) => {
    const parts = roleParts(cvOutline(state.doc), index);
    if (!parts) return null;
    if (parts.employer) return setParagraphText(state, parts.employer.from, value);
    const text = fieldText(value);
    if (!text) return null;
    const { schema } = state;
    const paragraph = schema.nodes.paragraph.create({ cvSection: "employer" }, schema.text(text));
    return state.tr.insert(parts.line.to, paragraph);
  };
}

export function setRoleDuty(index: number, duty: number, value: string): CvCommand {
  return (state) => {
    const parts = roleParts(cvOutline(state.doc), index);
    if (!parts?.list) return null;
    const point = listParagraphs(parts.list.node, parts.list.from)[duty];
    return point ? setParagraphText(state, point.pos, value) : null;
  };
}

function emptyItem(schema: Schema): PMNode {
  return schema.nodes.listItem.create(null, schema.nodes.paragraph.create());
}

/** Pusty punkt na końcu obowiązków; stanowisko bez listy dostaje etykietę i listę. */
export function addRoleDuty(index: number, lang: CvLang): CvCommand {
  return (state) => {
    const parts = roleParts(cvOutline(state.doc), index);
    if (!parts) return null;
    const { schema } = state;
    if (parts.list) return state.tr.insert(parts.list.to - 1, emptyItem(schema));
    const anchor = parts.label ?? parts.employer ?? parts.line;
    const nodes = [schema.nodes.bulletList.create(null, emptyItem(schema))];
    if (!parts.label) {
      const text = CV_TEMPLATE_LABELS[lang].responsibilities;
      nodes.unshift(schema.nodes.paragraph.create({ cvSection: "duties_label" }, schema.text(text)));
    }
    return state.tr.insert(anchor.to, Fragment.fromArray(nodes));
  };
}

/** Usuwa punkt obowiązków; ostatni znika razem z listą i etykietą „Zakres zadań:”. */
export function removeRoleDuty(index: number, duty: number): CvCommand {
  return (state) => {
    const parts = roleParts(cvOutline(state.doc), index);
    if (!parts?.list) return null;
    const list = parts.list.node;
    if (duty < 0 || duty >= list.childCount) return null;
    if (list.childCount === 1) {
      const tr = state.tr.delete(parts.list.from, parts.list.to);
      if (parts.label && parts.label.to === parts.list.from) tr.delete(parts.label.from, parts.label.to);
      return tr;
    }
    let offset = 0;
    for (let i = 0; i < duty; i += 1) offset += list.child(i).nodeSize;
    const from = parts.list.from + 1 + offset;
    return state.tr.delete(from, from + list.child(duty).nodeSize);
  };
}

export function setRoleTechnologies(index: number, value: string, lang: CvLang): CvCommand {
  return (state) => {
    const parts = roleParts(cvOutline(state.doc), index);
    if (!parts) return null;
    const text = fieldText(value);
    const label = CV_TEMPLATE_LABELS[lang].technologies;
    if (!parts.technologies) {
      if (!text) return null;
      const { schema } = state;
      const anchor = parts.list ?? parts.label ?? parts.employer ?? parts.line;
      const paragraph = schema.nodes.paragraph.create(
        { cvSection: "technologies" },
        schema.text(`${label} ${text}`),
      );
      return state.tr.insert(anchor.to, paragraph);
    }
    const node = parts.technologies.node;
    const current = node.textContent;
    const start = techLabelLength(current);
    const tr = state.tr;
    // Akapit bez etykiety szablonu dostaje ją z powrotem — serwer rozpoznaje go po niej.
    const changed =
      start === 0
        ? replaceText(tr, parts.technologies.from, 0, current.length, `${label} ${text}`)
        : replaceText(tr, parts.technologies.from, start, current.length, text);
    return changed ? tr : null;
  };
}

// ── Daty i podsumowania ──────────────────────────────────────────────────────

const PRESENT = /\b(?:obecnie|present|currently|now|teraz|nadal|ongoing|today|dziś|dzis)\b/i;
const DATE = /(?:\b(\d{1,2})[./])?\b((?:19|20)\d{2})\b/g;

function iso(month: string | undefined, year: string): string {
  return month ? `${year}-${month.padStart(2, "0")}` : year;
}

/** Okres z linii stanowiska jako `YYYY(-MM)`; `end: null` = do dziś. */
export function parsePeriod(text: string): { start: string; end: string | null } | null {
  const dates = [...text.matchAll(DATE)].map((match) => iso(match[1], match[2]));
  if (dates.length === 0) return null;
  if (dates.length >= 2) return { start: dates[0], end: dates[1] };
  return { start: dates[0], end: PRESENT.test(text) ? null : dates[0] };
}

/** „03.2021 – 06.2024” → od i do (do formularza z dwoma polami). */
export function splitPeriod(period: string): { start: string; end: string } {
  const match = /^(.*?)\s*(?:\s[-–—]\s|[–—])\s*(.*)$/.exec(period.trim());
  return match ? { start: match[1], end: match[2] } : { start: period.trim(), end: "" };
}

/** Od i do z powrotem w linię stanowiska; samo „do” zostaje po łączniku, żeby nie przeskoczyło do „od”. */
export function joinPeriod(start: string, end: string): string {
  const from = start.trim();
  const to = end.trim();
  if (from && to) return `${from} – ${to}`;
  return to ? `– ${to}` : from;
}

/** Ile miesięcy obejmują okresy (nakładki raz, „obecnie” do bieżącego miesiąca). */
export function periodsMonths(periods: readonly string[], now: number = currentMonthIndex()): number {
  const ranges = periods.flatMap((period) => parsePeriod(period) ?? []);
  return unionMonths(ranges, now);
}

/** „Z dat stanowisk: 8 lat 10 mies.” — cały staż z dat stanowisk; `null` bez dat. */
export function tenureHint(doc: PMNode, now: number = currentMonthIndex()): string | null {
  const months = periodsMonths(
    allRoleFields(doc).map((role) => role.period),
    now,
  );
  return months > 0 ? `Z dat stanowisk: ${monthsText(months)}` : null;
}

/** Czas jednego stanowiska („1 rok”, „3 lata 4 mies.”); `null` bez dat. */
export function roleDuration(period: string, now: number = currentMonthIndex()): string | null {
  const months = periodsMonths([period], now);
  return months > 0 ? monthsText(months) : null;
}

/** Firma bez branży z akapitu `employer` („Bank S.A. · Bankowość” → „Bank S.A.”). */
export function companyName(company: string | null): string {
  return (company ?? "").split(" · ")[0].trim();
}

function sectionTexts(outline: CvOutline, key: CvSectionKey): string[] {
  return sectionBlocks(outline, key)
    .map((block) => block.node.textContent.replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

export interface CvPage1Summaries {
  /** „6 firm na osi”. */
  career: string;
  /** „8 kategorii”. */
  skills: string | null;
  education: string | null;
  languages: string | null;
}

/** Jednolinijkowe podsumowania zwiniętych wierszy „Strony 1”. */
export function page1Summaries(doc: PMNode): CvPage1Summaries {
  const outline = cvOutline(doc);
  const companies = new Set(
    allRoleFields(doc)
      .map((role) => companyName(role.company).toLowerCase())
      .filter(Boolean),
  );
  const skills = sectionBlocks(outline, "skills").filter((block) => block.node.isTextblock && block.node.textContent.trim());
  const education = sectionTexts(outline, "education");
  const languages = sectionTexts(outline, "languages");
  return {
    career: `${countForm(companies.size, ["firma", "firmy", "firm"])} na osi`,
    skills: skills.length ? countForm(skills.length, ["kategoria", "kategorie", "kategorii"]) : null,
    education: education[0] ?? null,
    languages: languages.length ? languages.join(" · ") : null,
  };
}

/** Pozycja pierwszego bloku sekcji (kursor „Cały tekst” po kliknięciu wiersza). */
export function sectionStart(doc: PMNode, key: CvSectionKey): number | null {
  const outline = cvOutline(doc);
  const section = outline.sections.find((candidate) => candidate.key === key);
  if (!section) return null;
  const first = outline.blocks[section.headingIndex + 1];
  return (first && first.index < section.endIndex ? first.from : section.from) + 1;
}
