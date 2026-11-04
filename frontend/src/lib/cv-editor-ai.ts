/**
 * AI na zaznaczonym fragmencie CV (Edytor CV 2, PR 3) — czysta logika.
 *
 * Trzy rzeczy, wszystkie na dokumencie ProseMirror:
 *
 * - `selectionTarget` — czy zaznaczenie nadaje się dla AI i co o nim wysłać.
 *   Serwer dostaje TEKST: fragment (pogrubienie jako `**x**`), jego akapit albo
 *   punkt i opis stanowiska. Bez HTML-a i bez pozycji w dokumencie.
 * - zakres czekający na propozycję — dekoracja widoku, która jedzie z tekstem,
 *   gdy rekruter pisze gdzie indziej, i gaśnie, gdy zmieni sam fragment.
 *   Odpowiedź modelu przychodzi po kilku sekundach; bez tego propozycja
 *   trafiałaby w miejsce, którego już nie ma.
 * - `acceptStep` — przyjęta propozycja jako JEDNA transakcja na dokładnie tym
 *   zakresie, osobny krok historii („Cofnij” zdejmuje samą propozycję).
 *
 * AI działa w obrębie jednego akapitu albo punktu ze zwykłą treścią. Nagłówki,
 * stanowisko, firma, etykieta obowiązków i lista technologii mają gramatykę,
 * z której serwer składa Word (`cv-editor-blocks.ts`) — te poprawia człowiek.
 * Klauzula zgody jest stała.
 *
 * Moduł nie importuje `@tiptap/react`.
 */

import { Extension, type Editor } from "@tiptap/core";
import { closeHistory } from "@tiptap/pm/history";
import type { Mark, Node as PMNode } from "@tiptap/pm/model";
import { Plugin, PluginKey, TextSelection, type EditorState, type Transaction } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

import type { CvAiRole } from "@/lib/api/cvEditorAi";
import { cvOutline, isRodoNode, type CvOutline } from "@/lib/cv-editor-blocks";
import type { IssueRange } from "@/lib/cv-editor-issues";
import { parseBoldMarkup } from "@/lib/cv-qc";

/** Granice jak w schemacie trasy (`backend/app/services/cv_selection_ai.py`). */
export const CV_AI_FRAGMENT_MIN = 3;
export const CV_AI_FRAGMENT_MAX = 1200;
export const CV_AI_BLOCK_MAX = 2000;
const ROLE_POINTS_MAX = 12;
const ROLE_POINT_CHARS = 400;
const ROLE_NAME_CHARS = 200;

export interface CvAiTarget {
  from: number;
  to: number;
  /** Zaznaczony tekst; pogrubienie jako `**tekst**`. */
  fragment: string;
  /** Akapit albo punkt, w którym stoi zaznaczenie. */
  blockText: string;
  blockKind: "li" | "p";
  section: string | null;
  role?: CvAiRole;
}

export type CvAiSelection =
  | { ok: true; target: CvAiTarget }
  /** `hidden` = nie pokazuj AI wcale (brak zaznaczenia, klauzula zgody); `reason` = przyciski wyłączone z powodem. */
  | { ok: false; reason: string | null; hidden?: boolean };

const STRUCTURE_MARKERS = new Set(["role", "employer", "duties_label", "technologies"]);

export const CV_AI_REASON = {
  oneBlock: "Zaznacz fragment w jednym akapicie albo punkcie.",
  heading: "Nagłówków AI nie zmienia — zaznacz tekst w akapicie albo punkcie.",
  structure: "Stanowisko, firmę i listę technologii popraw ręcznie — AI zmienia opisy.",
  lineBreak: "Zaznaczenie obejmuje łamanie wiersza — zaznacz jedną linię.",
  asterisks: "Ten akapit zawiera znaki „**” — usuń je, zanim poprosisz AI.",
  tooShort: "Zaznacz co najmniej kilka znaków.",
  tooLong: `Zaznaczenie jest za długie (najwyżej ${CV_AI_FRAGMENT_MAX} znaków).`,
} as const;

// ── Tekst z pogrubieniem jako `**x**` ────────────────────────────────────────

function isBold(marks: readonly Mark[]): boolean {
  return marks.some((mark) => mark.type.name === "bold");
}

/** Tekst zakresu jednego bloku; sąsiednie pogrubione kawałki to jedno `**…**`. */
export function rangeMarkup(doc: PMNode, from: number, to: number): string {
  let out = "";
  let bold = false;
  doc.nodesBetween(from, to, (node, position) => {
    if (!node.isText || !node.text) return true;
    const text = node.text.slice(Math.max(0, from - position), Math.max(0, to - position));
    if (!text) return false;
    const next = isBold(node.marks);
    if (next !== bold) out += "**";
    bold = next;
    out += text;
    return false;
  });
  return bold ? `${out}**` : out;
}

function hasInlineLeaf(doc: PMNode, from: number, to: number): boolean {
  let found = false;
  doc.nodesBetween(from, to, (node) => {
    if (node.isInline && !node.isText) found = true;
    return !found;
  });
  return found;
}

// ── Zaznaczenie → cel ────────────────────────────────────────────────────────

function roleOf(doc: PMNode, outline: CvOutline, blockIndex: number, selectedFrom: number): CvAiRole | undefined {
  const role = outline.roles.find((item) => blockIndex >= item.fromIndex && blockIndex < item.toIndex);
  if (!role) return undefined;
  const blocks = outline.blocks.slice(role.fromIndex, role.toIndex);
  const employer = blocks.find((block) => block.marker === "employer");
  const points: string[] = [];
  for (const block of blocks) {
    if (block.node.type.name !== "bulletList" && block.node.type.name !== "orderedList") continue;
    block.node.descendants((node, offset) => {
      if (!node.isTextblock) return true;
      const start = block.from + 1 + offset;
      const selected = selectedFrom >= start && selectedFrom <= start + node.nodeSize;
      const text = node.textContent.trim();
      if (!selected && text && points.length < ROLE_POINTS_MAX) points.push(text.slice(0, ROLE_POINT_CHARS));
      return false;
    });
  }
  return {
    title: role.title.slice(0, ROLE_NAME_CHARS),
    employer: (employer?.node.textContent.trim() ?? "").slice(0, ROLE_NAME_CHARS),
    points,
  };
}

/** Czy zaznaczenie nadaje się dla AI i co o nim wysłać. */
export function selectionTarget(state: EditorState): CvAiSelection {
  const { selection, doc } = state;
  if (selection.empty) return { ok: false, reason: null, hidden: true };
  const outline = cvOutline(doc);
  const { $from, $to } = selection;
  const first = outline.blocks[$from.index(0)];
  const last = outline.blocks[$to.index(0)] ?? first;
  if (!first || isRodoNode(first.node) || isRodoNode(last.node)) return { ok: false, reason: null, hidden: true };
  if (!$from.sameParent($to) || !$from.parent.isTextblock) return { ok: false, reason: CV_AI_REASON.oneBlock };
  if ($from.parent.type.name === "heading") return { ok: false, reason: CV_AI_REASON.heading };
  if (first.marker && STRUCTURE_MARKERS.has(first.marker)) return { ok: false, reason: CV_AI_REASON.structure };

  // Odstępy na brzegach zostają w tekście — AI dostaje i zastępuje same słowa.
  const raw = doc.textBetween(selection.from, selection.to, undefined, "￼");
  const lead = raw.length - raw.trimStart().length;
  const trail = raw.length - raw.trimEnd().length;
  const from = selection.from + lead;
  const to = selection.to - trail;
  if (to - from < CV_AI_FRAGMENT_MIN) return { ok: false, reason: CV_AI_REASON.tooShort };
  // `**` to zapis pogrubienia w żądaniu — dosłowne gwiazdki w tekście byłyby dwuznaczne.
  if ($from.parent.textContent.includes("**")) return { ok: false, reason: CV_AI_REASON.asterisks };
  if (hasInlineLeaf(doc, from, to)) return { ok: false, reason: CV_AI_REASON.lineBreak };
  const fragment = rangeMarkup(doc, from, to);
  if (fragment.length > CV_AI_FRAGMENT_MAX) return { ok: false, reason: CV_AI_REASON.tooLong };

  const blockStart = $from.start();
  const whole = rangeMarkup(doc, blockStart, blockStart + $from.parent.content.size);
  const inList = $from.depth > 1 && $from.node($from.depth - 1).type.name === "listItem";
  return {
    ok: true,
    target: {
      from,
      to,
      fragment,
      // Bardzo długi akapit: kontekstem zostaje sam fragment (serwer wymaga, żeby w nim był).
      blockText: whole.length <= CV_AI_BLOCK_MAX ? whole : fragment,
      blockKind: inList ? "li" : "p",
      section: first.section,
      role: first.section === "experience" ? roleOf(doc, outline, first.index, from) : undefined,
    },
  };
}

// ── Zakres czekający na propozycję ───────────────────────────────────────────

interface Pending {
  from: number;
  to: number;
  fragment: string;
}

type PendingMeta = { set: Pending } | { clear: true };

const pendingKey = new PluginKey<Pending | null>("cvEditorAiPending");

function stillThere(doc: PMNode, from: number, to: number, fragment: string): boolean {
  if (from < 0 || to > doc.content.size || to <= from) return false;
  const $from = doc.resolve(from);
  return $from.parent.isTextblock && $from.sameParent(doc.resolve(to)) && rangeMarkup(doc, from, to) === fragment;
}

export const CvEditorAiPending = Extension.create({
  name: "cvEditorAiPending",
  addProseMirrorPlugins() {
    return [
      new Plugin<Pending | null>({
        key: pendingKey,
        state: {
          init: () => null,
          apply(tr, value) {
            const meta = tr.getMeta(pendingKey) as PendingMeta | undefined;
            if (meta && "clear" in meta) return null;
            if (meta && "set" in meta) return meta.set;
            if (!value || !tr.docChanged) return value;
            const from = tr.mapping.map(value.from, 1);
            const to = tr.mapping.map(value.to, -1);
            if (stillThere(tr.doc, from, to, value.fragment)) return { ...value, from, to };
            // Wczytanie tej samej treści od nowa (nowy szkic) zastępuje cały dokument —
            // mapowanie gubi zakres, ale tekst stoi tam, gdzie stał.
            if (stillThere(tr.doc, value.from, value.to, value.fragment)) return value;
            return null;
          },
        },
        props: {
          decorations(state) {
            const pending = pendingKey.getState(state);
            if (!pending) return null;
            return DecorationSet.create(state.doc, [
              Decoration.inline(pending.from, pending.to, { class: "cv-ai-pending" }),
            ]);
          },
        },
      }),
    ];
  },
});

/** Zapamiętuje zakres, dla którego zamówiono propozycję (bez zmiany treści i historii). */
export function setPending(editor: Editor, target: Pick<CvAiTarget, "from" | "to" | "fragment">): void {
  if (editor.isDestroyed) return;
  const pending: Pending = { from: target.from, to: target.to, fragment: target.fragment };
  editor.view.dispatch(editor.state.tr.setMeta(pendingKey, { set: pending }).setMeta("addToHistory", false));
}

export function clearPending(editor: Editor): void {
  if (editor.isDestroyed || !pendingKey.getState(editor.state)) return;
  editor.view.dispatch(editor.state.tr.setMeta(pendingKey, { clear: true }).setMeta("addToHistory", false));
}

/** Bieżące położenie zakresu albo `null`, gdy fragment zmieniono albo usunięto. */
export function pendingTarget(state: EditorState): Pending | null {
  return pendingKey.getState(state) ?? null;
}

// ── Przyjęcie propozycji ─────────────────────────────────────────────────────

/** Znaczniki inne niż pogrubienie, które obejmują CAŁY zakres (kursywa, odnośnik). */
function sharedMarks(doc: PMNode, from: number, to: number): Mark[] {
  let shared: Mark[] | null = null;
  doc.nodesBetween(from, to, (node) => {
    if (!node.isText) return true;
    const own = node.marks.filter((mark) => mark.type.name !== "bold");
    shared = shared === null ? own : shared.filter((mark) => own.some((other) => other.eq(mark)));
    return false;
  });
  return shared ?? [];
}

export interface AcceptStep {
  transaction: Transaction;
  /** Wstawiony tekst w nowym dokumencie — do wyróżnienia po przyjęciu. */
  changed: IssueRange;
}

/**
 * Transakcja wstawiająca propozycję w miejsce zakresu czekającego; `null`,
 * gdy zakresu już nie ma albo propozycja jest pusta.
 */
export function acceptStep(state: EditorState, proposed: string): AcceptStep | null {
  const pending = pendingTarget(state);
  if (!pending || !stillThere(state.doc, pending.from, pending.to, pending.fragment)) return null;
  const runs = parseBoldMarkup(proposed.trim());
  if (runs.length === 0) return null;
  const bold = state.schema.marks.bold;
  const keep = sharedMarks(state.doc, pending.from, pending.to);
  const nodes = runs.map((run) => state.schema.text(run.t, run.b && bold ? [...keep, bold.create()] : keep));
  const transaction = state.tr.replaceWith(pending.from, pending.to, nodes);
  const end = pending.from + nodes.reduce((size, node) => size + node.nodeSize, 0);
  transaction.setSelection(TextSelection.create(transaction.doc, end)).setMeta(pendingKey, { clear: true });
  return { transaction: closeHistory(transaction), changed: { from: pending.from, to: end, block: false } };
}
