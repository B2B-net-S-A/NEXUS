/**
 * Bloki CV w edytorze — czysta logika na dokumencie ProseMirror.
 *
 * Dokument edytora jest PŁASKI: `h1 | p | hr | h2[sekcja] | ul | p[role] |
 * p[employer] | p[duties_label] | ul | p[technologies] | … | p[rodo]`. Tiptap
 * gubi klasy i opakowania generatora (`div.job`), zostają znaczniki
 * `data-cv-section` (`lib/cv-editor-section.ts`). Z tego samego HTML-a serwer
 * składa Word dla klienta (`services/cv_approved_docx.py`), więc polecenia
 * tutaj trzymają jego gramatykę:
 *
 * - stanowisko to zakres od akapitu `role` do następnego stanowiska, nagłówka
 *   sekcji, klauzuli zgody albo końca dokumentu (nie ma opakowania),
 * - „Nazwa firmy:” dostaje tylko akapit `employer` TUŻ po stanowisku, a
 *   „Stanowisko:” tylko akapit zaczynający się pogrubieniem,
 * - etykieta obowiązków i technologii musi mieć dokładny tekst szablonu
 *   (`CV_TEMPLATE_LABELS` = lustro `docx_renderer.TRANSLATIONS`),
 * - jeden znacznik `role` przełącza serwer z rozpoznawania po kształcie na
 *   same znaczniki, więc w starym CV bez znaczników pierwsze oznaczenie
 *   stanowiska oznacza od razu wszystko, co serwer rozpoznałby sam.
 *
 * Polecenie zwraca transakcję albo `null`, gdy nie ma zastosowania (przycisk
 * wyłączony). Moduł nie importuje `@tiptap/react`.
 */

import type { Editor } from "@tiptap/core";
import { Fragment, type Node as PMNode, type Schema } from "@tiptap/pm/model";
import { TextSelection, type EditorState, type Transaction } from "@tiptap/pm/state";

export type CvLang = "pl" | "en";

export const CV_SECTION_KEYS = [
  "why_points",
  "education",
  "skills",
  "certifications",
  "languages",
  "experience",
] as const;
export type CvSectionKey = (typeof CV_SECTION_KEYS)[number];

export const CV_BLOCK_MARKERS = ["role", "employer", "duties_label", "technologies"] as const;
export type CvBlockMarker = (typeof CV_BLOCK_MARKERS)[number];

/** „Typ akapitu” w pasku: zwykły tekst, znacznik struktury albo nagłówek sekcji. */
export type CvBlockKind = "text" | CvBlockMarker | CvSectionKey;

export const CV_RODO_MARKER = "rodo";

/**
 * Pierwsze słowa klauzuli zgody z szablonu. Starsze CV zgubiły jej znacznik —
 * zostaje tekst (ta sama reguła co `services/cv_rodo_clause.py`, lustro pilnuje
 * `backend/tests/test_cv_editor_template_labels.py`).
 */
export const CV_RODO_OPENINGS = {
  pl: "Wyrażam zgodę na przetwarzanie moich",
  en: "I hereby consent to the",
} as const satisfies Record<CvLang, string>;

/**
 * Tytuły sekcji i etykiety szablonu Worda. Lustro `TRANSLATIONS`
 * w `backend/app/services/cv_generator_b2b/docx_renderer.py` — pilnuje
 * `backend/tests/test_cv_editor_template_labels.py`.
 */
export const CV_TEMPLATE_LABELS = {
  pl: {
    why_points: "DLACZEGO NASZ KANDYDAT?",
    education: "EDUKACJA",
    skills: "UMIEJĘTNOŚCI",
    certifications: "CERTYFIKATY",
    languages: "JĘZYKI",
    experience: "DOŚWIADCZENIE",
    responsibilities: "Zakres zadań:",
    technologies: "Technologie:",
  },
  en: {
    why_points: "WHY OUR CANDIDATE?",
    education: "EDUCATION",
    skills: "SKILLS",
    certifications: "CERTIFICATIONS",
    languages: "LANGUAGES",
    experience: "EXPERIENCE",
    responsibilities: "Tasks:",
    technologies: "Technologies:",
  },
} as const satisfies Record<CvLang, Record<CvSectionKey | "responsibilities" | "technologies", string>>;

/**
 * Pola do wypełnienia w nowo wstawionych blokach. Nawiasy kwadratowe są
 * celowe: widać je w Wordzie, a „Zapisz” nie zatwierdza CV, dopóki zostały.
 */
export const CV_PLACEHOLDERS = {
  pl: {
    position: "[Stanowisko]",
    dates: "[MM.RRRR – MM.RRRR]",
    company: "[Nazwa firmy]",
    duty: "[Obowiązek]",
    technologies: "[technologie]",
    educationDates: "[RRRR – RRRR]",
    school: "[Uczelnia]",
    degree: "[kierunek]",
    skillGroup: "[Kategoria]",
    skills: "[umiejętności]",
    language: "[Język – poziom]",
    certificate: "[Certyfikat]",
  },
  en: {
    position: "[Position]",
    dates: "[MM.YYYY – MM.YYYY]",
    company: "[Company]",
    duty: "[Task]",
    technologies: "[technologies]",
    educationDates: "[YYYY – YYYY]",
    school: "[University]",
    degree: "[degree]",
    skillGroup: "[Category]",
    skills: "[skills]",
    language: "[Language – level]",
    certificate: "[Certificate]",
  },
} as const;

const ALL_PLACEHOLDERS: readonly string[] = [
  ...new Set(Object.values(CV_PLACEHOLDERS).flatMap((set) => Object.values(set))),
];

/** Niewypełnione pola nowych bloków w treści CV (HTML albo zwykły tekst). */
export function cvPlaceholders(content: string): string[] {
  return ALL_PLACEHOLDERS.filter((placeholder) => content.includes(placeholder));
}

// ── Odczyt struktury ─────────────────────────────────────────────────────────

export interface CvBlock {
  index: number;
  /** Pozycja bloku w dokumencie (przed węzłem) i tuż za nim. */
  from: number;
  to: number;
  node: PMNode;
  /** Znacznik `data-cv-section` bloku. */
  marker: string | null;
  /** Sekcja, w której stoi blok; dla nagłówka sekcji — jego własna. */
  section: CvSectionKey | null;
}

export interface CvSection {
  key: CvSectionKey;
  headingIndex: number;
  from: number;
  /** Pierwszy blok ZA sekcją i jego pozycja — tu dopisuje się na koniec sekcji. */
  endIndex: number;
  end: number;
}

export interface CvRole {
  /** Bloki `[fromIndex, toIndex)` i ich pozycje w dokumencie. */
  fromIndex: number;
  toIndex: number;
  from: number;
  to: number;
  title: string;
}

export interface CvOutline {
  blocks: CvBlock[];
  sections: CvSection[];
  roles: CvRole[];
  rodo: CvBlock | null;
}

function normTitle(text: string): string {
  return text.replace(/\s+/g, " ").trim().toLowerCase().replace(/[:?]+$/, "").trim();
}

const SECTION_TITLES: ReadonlyMap<string, CvSectionKey> = (() => {
  const titles = new Map<string, CvSectionKey>([
    ["summary", "why_points"],
    ["podsumowanie", "why_points"],
  ]);
  for (const labels of Object.values(CV_TEMPLATE_LABELS)) {
    for (const key of CV_SECTION_KEYS) titles.set(normTitle(labels[key]), key);
  }
  return titles;
})();

function isSectionKey(value: unknown): value is CvSectionKey {
  return (CV_SECTION_KEYS as readonly unknown[]).includes(value);
}

function isBlockMarker(value: unknown): value is CvBlockMarker {
  return (CV_BLOCK_MARKERS as readonly unknown[]).includes(value);
}

function markerOf(node: PMNode): string | null {
  const value: unknown = node.attrs.cvSection;
  return typeof value === "string" ? value : null;
}

/** Nagłówek, który zamyka stanowisko i sekcję (h1 dokumentu, h2 sekcji). */
function isSectionHeading(node: PMNode): boolean {
  return node.type.name === "heading" && Number(node.attrs.level) <= 2;
}

function isList(node: PMNode): boolean {
  return node.type.name === "bulletList" || node.type.name === "orderedList";
}

const RODO_OPENINGS = Object.values(CV_RODO_OPENINGS).map((opening) => opening.toLowerCase());

/** Klauzula zgody: znacznik `rodo` albo akapit zaczynający się jak klauzula z szablonu. */
export function isRodoNode(node: PMNode): boolean {
  if (markerOf(node) === CV_RODO_MARKER) return true;
  if (node.type.name !== "paragraph") return false;
  const text = node.textContent.replace(/\s+/g, " ").trim().toLowerCase();
  return RODO_OPENINGS.some((opening) => text.startsWith(opening));
}

export function cvOutline(doc: PMNode): CvOutline {
  const blocks: CvBlock[] = [];
  let section: CvSectionKey | null = null;
  doc.forEach((node, offset, index) => {
    const marker = markerOf(node);
    if (isSectionHeading(node)) {
      section = isSectionKey(marker) ? marker : (SECTION_TITLES.get(normTitle(node.textContent)) ?? null);
    }
    blocks.push({ index, from: offset, to: offset + node.nodeSize, node, marker, section });
  });

  const rodo = blocks.find((block) => isRodoNode(block.node)) ?? null;
  const endOf = (start: number, closes: (block: CvBlock) => boolean): [number, number] => {
    for (let i = start; i < blocks.length; i += 1) {
      if (closes(blocks[i])) return [i, blocks[i].from];
    }
    return [blocks.length, doc.content.size];
  };
  const closesSection = (block: CvBlock) => isSectionHeading(block.node) || isRodoNode(block.node);

  const sections: CvSection[] = [];
  const roles: CvRole[] = [];
  for (const block of blocks) {
    if (block.node.type.name === "heading" && Number(block.node.attrs.level) === 2 && block.section) {
      const [endIndex, end] = endOf(block.index + 1, closesSection);
      sections.push({ key: block.section, headingIndex: block.index, from: block.from, endIndex, end });
    }
    if (block.marker === "role" && block.node.type.name === "paragraph") {
      const [toIndex, to] = endOf(
        block.index + 1,
        (next) => closesSection(next) || next.marker === "role",
      );
      roles.push({
        fromIndex: block.index,
        toIndex,
        from: block.from,
        to,
        title: block.node.textContent.replace(/\s+/g, " ").trim(),
      });
    }
  }
  return { blocks, sections, roles, rodo };
}

export interface CvContext {
  outline: CvOutline;
  /** Blok najwyższego poziomu pod kursorem. */
  block: CvBlock | null;
  role: CvRole | null;
  section: CvSectionKey | null;
  inList: boolean;
  /** Klauzula zgody — nie do edycji. */
  locked: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
}

export function cvContext(state: EditorState): CvContext {
  const outline = cvOutline(state.doc);
  const block = outline.blocks[state.selection.$from.index(0)] ?? null;
  const roleAt = block
    ? outline.roles.findIndex((role) => block.index >= role.fromIndex && block.index < role.toIndex)
    : -1;
  const role = roleAt >= 0 ? outline.roles[roleAt] : null;
  const previous = roleAt > 0 ? outline.roles[roleAt - 1] : null;
  const next = roleAt >= 0 ? (outline.roles[roleAt + 1] ?? null) : null;
  return {
    outline,
    block,
    role,
    section: block?.section ?? null,
    inList: block ? isList(block.node) : false,
    locked: !!block && isRodoNode(block.node),
    // Sąsiad musi stać bezpośrednio obok — nie przeskakujemy nagłówka sekcji.
    canMoveUp: !!role && !!previous && previous.toIndex === role.fromIndex,
    canMoveDown: !!role && !!next && role.toIndex === next.fromIndex,
  };
}

// ── Polecenia ────────────────────────────────────────────────────────────────

export type CvCommand = (state: EditorState) => Transaction | null;

/** Wykonuje polecenie w edytorze; `false`, gdy nie miało zastosowania. */
export function runCvCommand(editor: Editor, command: CvCommand): boolean {
  const transaction = command(editor.state);
  if (!transaction) return false;
  editor.view.dispatch(transaction.scrollIntoView());
  editor.view.focus();
  return true;
}

function paragraph(schema: Schema, marker: CvBlockMarker | null, content: PMNode[]): PMNode {
  return schema.nodes.paragraph.create({ cvSection: marker }, content);
}

function bold(schema: Schema, text: string): PMNode {
  return schema.text(text, [schema.marks.bold.create()]);
}

function listItem(schema: Schema, text: string): PMNode {
  const body = text ? [schema.text(text)] : [];
  return schema.nodes.listItem.create(null, schema.nodes.paragraph.create(null, body));
}

function sectionHeading(schema: Schema, key: CvSectionKey, lang: CvLang): PMNode {
  return schema.nodes.heading.create(
    { level: 2, cvSection: key },
    schema.text(CV_TEMPLATE_LABELS[lang][key]),
  );
}

/** Zaznacza pierwsze pole do wypełnienia w bloku wstawionym na `at`. */
function selectPlaceholder(tr: Transaction, at: number, placeholder: string): Transaction {
  const start = at + 1;
  return tr.setSelection(TextSelection.create(tr.doc, start, start + placeholder.length));
}

/** Gdzie wstawić brakującą sekcję: przed pierwszą późniejszą w kolejności szablonu. */
function newSectionPosition(outline: CvOutline, key: CvSectionKey, doc: PMNode): number {
  const order = CV_SECTION_KEYS.indexOf(key);
  const later = outline.sections.find((section) => CV_SECTION_KEYS.indexOf(section.key) > order);
  return later?.from ?? outline.rodo?.from ?? doc.content.size;
}

export function insertRole(lang: CvLang): CvCommand {
  return (state) => {
    const { schema, doc } = state;
    const { outline, role } = cvContext(state);
    const fields = CV_PLACEHOLDERS[lang];
    const labels = CV_TEMPLATE_LABELS[lang];
    const nodes = [
      paragraph(schema, "role", [bold(schema, fields.position), schema.text(` ${fields.dates}`)]),
      paragraph(schema, "employer", [schema.text(fields.company)]),
      paragraph(schema, "duties_label", [schema.text(labels.responsibilities)]),
      schema.nodes.bulletList.create(null, listItem(schema, fields.duty)),
      paragraph(schema, "technologies", [schema.text(`${labels.technologies} ${fields.technologies}`)]),
    ];
    const experience = outline.sections.find((section) => section.key === "experience");
    let at = role?.to ?? experience?.end;
    let roleAt = at;
    if (at === undefined) {
      at = newSectionPosition(outline, "experience", doc);
      const heading = sectionHeading(schema, "experience", lang);
      nodes.unshift(heading);
      roleAt = at + heading.nodeSize;
    }
    const tr = state.tr.insert(at, Fragment.fromArray(nodes));
    return selectPlaceholder(tr, roleAt ?? at, fields.position);
  };
}

/** Dopisuje punkt na końcu listy i zaznacza jego treść. Pozycje liczone w `tr.doc`. */
function appendItem(tr: Transaction, schema: Schema, list: CvBlock, text: string): Transaction {
  const at = list.to - 1;
  tr.insert(at, listItem(schema, text));
  const start = at + 2;
  return tr.setSelection(TextSelection.create(tr.doc, start, start + text.length));
}

/** Punkt na końcu sekcji-listy („dlaczego”, certyfikaty); zakłada listę, gdy jej nie ma. */
function appendToSection(
  tr: Transaction,
  schema: Schema,
  key: "why_points" | "certifications",
  lang: CvLang,
): Transaction | null {
  const outline = cvOutline(tr.doc);
  const target = outline.sections.find((section) => section.key === key);
  if (!target) return null;
  const text = key === "certifications" ? CV_PLACEHOLDERS[lang].certificate : "";
  const list = outline.blocks
    .slice(target.headingIndex + 1, target.endIndex)
    .find((block) => isList(block.node));
  if (list) return appendItem(tr, schema, list, text);
  tr.insert(target.end, schema.nodes.bulletList.create(null, listItem(schema, text)));
  const start = target.end + 3;
  return tr.setSelection(TextSelection.create(tr.doc, start, start + text.length));
}

export function insertBullet(lang: CvLang): CvCommand {
  return (state) => {
    const { schema, selection } = state;
    const { $from } = selection;
    for (let depth = $from.depth; depth > 0; depth -= 1) {
      if ($from.node(depth).type === schema.nodes.listItem) {
        const at = $from.after(depth);
        const tr = state.tr.insert(at, listItem(schema, ""));
        return tr.setSelection(TextSelection.create(tr.doc, at + 2));
      }
    }
    const { outline, role, section } = cvContext(state);
    const duty = CV_PLACEHOLDERS[lang].duty;
    if (role) {
      const blocks = outline.blocks.slice(role.fromIndex, role.toIndex);
      const list = blocks.find((block) => isList(block.node));
      if (list) return appendItem(state.tr, schema, list, duty);
      // Stanowisko bez listy: etykieta obowiązków (gdy jej nie ma) i lista
      // pod firmą — w tej kolejności szablon je rysuje.
      const label = blocks.find((block) => block.marker === "duties_label");
      const anchor = label ?? (blocks[1]?.marker === "employer" ? blocks[1] : blocks[0]);
      const nodes = [schema.nodes.bulletList.create(null, listItem(schema, duty))];
      if (!label) {
        const text = CV_TEMPLATE_LABELS[lang].responsibilities;
        nodes.unshift(paragraph(schema, "duties_label", [schema.text(text)]));
      }
      const tr = state.tr.insert(anchor.to, Fragment.fromArray(nodes));
      const start = anchor.to + (label ? 0 : nodes[0].nodeSize) + 3;
      return tr.setSelection(TextSelection.create(tr.doc, start, start + duty.length));
    }
    if (section === "why_points" || section === "certifications") {
      return appendToSection(state.tr, schema, section, lang);
    }
    return null;
  };
}

export type CvRowSection = "education" | "skills" | "certifications" | "languages";

/** Nowy wiersz sekcji; brakującą sekcję zakłada w kolejności szablonu. */
export function insertRow(key: CvRowSection, lang: CvLang): CvCommand {
  return (state) => {
    const { schema, doc } = state;
    const fields = CV_PLACEHOLDERS[lang];
    const tr = state.tr;
    const before = cvOutline(doc);
    if (!before.sections.some((section) => section.key === key)) {
      tr.insert(newSectionPosition(before, key, doc), sectionHeading(schema, key, lang));
    }
    if (key === "certifications") return appendToSection(tr, schema, key, lang);
    const section = cvOutline(tr.doc).sections.find((candidate) => candidate.key === key);
    if (!section) return null;
    const rows = {
      // Wiersz tabeli w Wordzie: daty zwykłym tekstem, uczelnia pogrubiona, reszta pod nią.
      education: {
        first: fields.educationDates,
        content: [
          schema.text(`${fields.educationDates} `),
          bold(schema, fields.school),
          schema.text(` — ${fields.degree}`),
        ],
      },
      skills: {
        first: `${fields.skillGroup}: `,
        content: [bold(schema, `${fields.skillGroup}: `), schema.text(fields.skills)],
      },
      languages: { first: fields.language, content: [schema.text(fields.language)] },
    }[key];
    tr.insert(section.end, paragraph(schema, null, rows.content));
    return selectPlaceholder(tr, section.end, rows.first);
  };
}

export function moveRole(direction: -1 | 1): CvCommand {
  return (state) => {
    const { outline, role, canMoveUp, canMoveDown } = cvContext(state);
    if (!role || (direction === -1 ? !canMoveUp : !canMoveDown)) return null;
    const at = outline.roles.indexOf(role);
    const content = state.doc.slice(role.from, role.to).content;
    const tr = state.tr;
    let target: number;
    if (direction === -1) {
      target = outline.roles[at - 1].from;
      tr.delete(role.from, role.to).insert(target, content);
    } else {
      const next = outline.roles[at + 1];
      tr.insert(next.to, content).delete(role.from, role.to);
      target = next.to - (role.to - role.from);
    }
    return tr.setSelection(TextSelection.near(tr.doc.resolve(target + 1)));
  };
}

export const duplicateRole: CvCommand = (state) => {
  const { role } = cvContext(state);
  if (!role) return null;
  const tr = state.tr.insert(role.to, state.doc.slice(role.from, role.to).content);
  return tr.setSelection(TextSelection.near(tr.doc.resolve(role.to + 1)));
};

export const deleteRole: CvCommand = (state) => {
  const { role } = cvContext(state);
  if (!role) return null;
  // Dokument nie może zostać pusty (schemat wymaga co najmniej jednego bloku).
  if (role.from === 0 && role.to === state.doc.content.size) return null;
  const tr = state.tr.delete(role.from, role.to);
  const at = Math.min(role.from, tr.doc.content.size);
  return tr.setSelection(TextSelection.near(tr.doc.resolve(at), -1));
};

// ── Typ akapitu ──────────────────────────────────────────────────────────────

// Lustro `_DATES_ONLY` z `cv_approved_docx.py`: za pogrubionym stanowiskiem
// stoi zakres dat i nic więcej.
const DATES_ONLY =
  /^(?=.*\b(?:19|20)\d{2}\b)[\d\s./()–—-]*(?:\b(?:present|obecnie|currently|now|teraz|nadal|ongoing)\b[\s.)]*)?$/i;
const DATE_START = /\(?\b(?:\d{1,2}[./])?(?:19|20)\d{2}\b/;

function splitLeadingBold(node: PMNode): { lead: string; rest: string } {
  let lead = "";
  let rest = "";
  let inLead = true;
  node.forEach((child) => {
    const text = child.isText ? (child.text ?? "") : " ";
    const isBold = child.marks.some((mark) => mark.type.name === "bold");
    if (inLead && isBold) lead += text;
    else {
      inLead = false;
      rest += text;
    }
  });
  return { lead, rest };
}

/** Kształt akapitu doświadczenia, jaki serwer rozpoznaje bez znaczników. */
function shapeOf(node: PMNode): CvBlockMarker | null {
  if (node.type.name !== "paragraph") return null;
  const text = node.textContent;
  const title = normTitle(text);
  const labels = Object.values(CV_TEMPLATE_LABELS);
  if (labels.some((set) => normTitle(set.responsibilities) === title)) return "duties_label";
  if (labels.some((set) => text.trim().startsWith(set.technologies))) return "technologies";
  const { lead, rest } = splitLeadingBold(node);
  return lead.trim() && DATES_ONLY.test(rest.trim()) ? "role" : null;
}

/**
 * Stare CV bez znaczników: zanim pierwszy akapit dostanie znacznik `role`,
 * oznacz wszystko, co serwer rozpoznałby po kształcie — inaczej pozostałe
 * stanowiska straciłyby w Wordzie etykiety „Nazwa firmy:” i „Stanowisko:”.
 */
function markLegacyStructure(tr: Transaction, outline: CvOutline): void {
  const blocks = outline.blocks.filter(
    (block) => block.section === "experience" && !block.marker && !isSectionHeading(block.node),
  );
  blocks.forEach((block, position) => {
    const shape = shapeOf(block.node);
    if (shape) {
      tr.setNodeMarkup(block.from, undefined, { ...block.node.attrs, cvSection: shape });
      return;
    }
    const previous = blocks[position - 1];
    const afterRole =
      !!previous && previous.index === block.index - 1 && shapeOf(previous.node) === "role";
    if (afterRole && block.node.type.name === "paragraph") {
      tr.setNodeMarkup(block.from, undefined, { ...block.node.attrs, cvSection: "employer" });
    }
  });
}

/** Stanowisko bez pogrubienia nie dostaje w Wordzie etykiety — pogrub część przed datami. */
function ensureLeadingBold(tr: Transaction, block: CvBlock, schema: Schema): void {
  if (splitLeadingBold(block.node).lead.trim()) return;
  const text = block.node.textBetween(0, block.node.content.size, undefined, " ");
  const dates = text.search(DATE_START);
  const lead = (dates > 0 ? text.slice(0, dates) : text).replace(/[\s—–\-,:·|(]+$/, "");
  if (!lead.trim()) return;
  tr.addMark(block.from + 1, block.from + 1 + lead.length, schema.marks.bold.create());
}

export function blockKindOf(block: CvBlock | null): CvBlockKind | null {
  if (!block || !block.node.isTextblock) return null;
  if (block.node.type.name === "heading") {
    return isSectionHeading(block.node) && block.section ? block.section : null;
  }
  return isBlockMarker(block.marker) ? block.marker : "text";
}

export function setBlockKind(kind: CvBlockKind, lang: CvLang): CvCommand {
  return (state) => {
    const { outline, block, locked, inList } = cvContext(state);
    if (!block || locked || inList || !block.node.isTextblock) return null;
    if (blockKindOf(block) === kind) return null;
    const { schema } = state;
    const tr = state.tr;
    if (isSectionKey(kind)) {
      tr.setNodeMarkup(block.from, schema.nodes.heading, { level: 2, cvSection: kind });
      if (!block.node.textContent.trim()) {
        tr.insertText(CV_TEMPLATE_LABELS[lang][kind], block.from + 1);
      }
      return tr;
    }
    if (kind === "text") {
      return tr.setNodeMarkup(block.from, schema.nodes.paragraph, { cvSection: null });
    }
    if (kind === "role" && outline.roles.length === 0) markLegacyStructure(tr, outline);
    tr.setNodeMarkup(block.from, schema.nodes.paragraph, { cvSection: kind });
    if (kind === "role") ensureLeadingBold(tr, block, schema);
    return tr;
  };
}
