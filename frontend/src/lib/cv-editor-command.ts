/**
 * Polecenie własnymi słowami dla całego CV (Edytor CV 2, PR 4) — czysta logika.
 *
 * Edytor wysyła CV WIERSZ PO WIERSZU (blok dokumentu albo punkt listy, tekst
 * z pogrubieniem jako `**x**`), a serwer zwraca PLAN: operacje na numerach
 * wierszy, które przeszły kontrolę (`backend/app/services/cv_command_ai.py`).
 * Tutaj:
 *
 * - `cvLines` — wiersze dokumentu z pozycjami, po których plan da się nałożyć,
 * - `planMarks` — co pokazać na kartce, zanim rekruter cokolwiek zatwierdzi,
 * - `applyPlan` — wybrane operacje jako JEDNA transakcja i jeden krok historii.
 *
 * Plan odnosi się do zrzutu dokumentu z chwili zamówienia. Kartka jest wtedy
 * tylko do odczytu, a `applyPlan` i tak sprawdza, że wiersze się nie zmieniły.
 *
 * Moduł nie importuje `@tiptap/react`.
 */

import { Extension, type Editor } from "@tiptap/core";
import { closeHistory } from "@tiptap/pm/history";
import { Fragment, type Node as PMNode } from "@tiptap/pm/model";
import { Plugin, PluginKey, TextSelection, type EditorState, type Transaction } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

import type { CvCommandLine, CvLineKind, CvPlanOperation } from "@/lib/api/cvEditorCommand";
import { rangeMarkup } from "@/lib/cv-editor-ai";
import { cvOutline, isRodoNode, type CvSectionKey } from "@/lib/cv-editor-blocks";
import { parseBoldMarkup } from "@/lib/cv-qc";

/** Granice jak w schemacie trasy (`backend/app/api/cv_editor_ai.py`). */
export const CV_COMMAND_MAX = 300;
export const CV_COMMAND_LINES_MAX = 400;
export const CV_COMMAND_LINE_TEXT_MAX = 1200;
export const CV_COMMAND_TEXT_TOTAL_MAX = 60_000;

export interface CvLine {
  id: number;
  kind: CvLineKind;
  /** Tekst wiersza; pogrubienie jako `**x**`. */
  text: string;
  section: CvSectionKey | null;
  /** Numer stanowiska w CV (od zera), gdy wiersz do niego należy. */
  role: number | null;
  /** Węzeł wiersza: blok dokumentu albo punkt listy. */
  from: number;
  to: number;
  /** Wnętrze akapitu z treścią — tu podmienia się tekst. */
  innerFrom: number;
  innerTo: number;
  /** Blok dokumentu, w którym stoi wiersz (dla punktu — jego lista). */
  blockFrom: number;
  blockTo: number;
  /** Punkt listy: ile punktów ma jego lista. */
  siblings: number;
}

const MARKER_KIND: Record<string, CvLineKind> = {
  role: "role",
  employer: "employer",
  duties_label: "label",
  technologies: "technologies",
};

function isList(node: PMNode): boolean {
  return node.type.name === "bulletList" || node.type.name === "orderedList";
}

/** Pierwszy blok tekstowy węzła i jego pozycja (wnętrze akapitu punktu listy). */
function innerOf(node: PMNode, at: number): { from: number; to: number } {
  let found: { from: number; to: number } | null = null;
  if (node.isTextblock) return { from: at + 1, to: at + node.nodeSize - 1 };
  node.descendants((child, offset) => {
    if (found || !child.isTextblock) return !found;
    found = { from: at + 1 + offset + 1, to: at + 1 + offset + child.nodeSize - 1 };
    return false;
  });
  return found ?? { from: at + 1, to: at + 1 };
}

/** Wiersze CV w kolejności dokumentu; klauzula zgody nie jest wierszem. */
export function cvLines(doc: PMNode): CvLine[] {
  const outline = cvOutline(doc);
  const roleOf = (index: number): number | null => {
    const at = outline.roles.findIndex((role) => index >= role.fromIndex && index < role.toIndex);
    return at >= 0 ? at : null;
  };
  const lines: CvLine[] = [];
  const push = (line: Omit<CvLine, "id" | "text" | "kind"> & { kind: CvLineKind }) => {
    const text = rangeMarkup(doc, line.innerFrom, line.innerTo).replace(/\s+/g, " ").trim();
    // Wiersz dłuższy niż limit trasy idzie przycięty i jako nieedytowalny.
    const long = text.length > CV_COMMAND_LINE_TEXT_MAX;
    lines.push({
      ...line,
      id: lines.length,
      kind: long && (line.kind === "bullet" || line.kind === "text") ? "label" : line.kind,
      text: long ? text.slice(0, CV_COMMAND_LINE_TEXT_MAX) : text,
    });
  };
  for (const block of outline.blocks) {
    if (isRodoNode(block.node)) continue;
    const base = { section: block.section, role: roleOf(block.index), blockFrom: block.from, blockTo: block.to, siblings: 0 };
    if (isList(block.node)) {
      block.node.forEach((item, offset) => {
        const from = block.from + 1 + offset;
        const inner = innerOf(item, from);
        // Punkt z zagnieżdżoną listą ma więcej niż jeden blok — poprawia go człowiek.
        const plain = item.childCount === 1 && item.firstChild?.isTextblock === true;
        push({
          ...base,
          kind: plain ? "bullet" : "label",
          from,
          to: from + item.nodeSize,
          innerFrom: inner.from,
          innerTo: inner.to,
          siblings: block.node.childCount,
        });
      });
      continue;
    }
    const inner = innerOf(block.node, block.from);
    const heading = block.node.type.name === "heading";
    const level = heading ? Number(block.node.attrs.level) : 0;
    const kind: CvLineKind = heading
      ? level === 1
        ? "title"
        : level === 2
          ? "heading"
          : "label"
      : block.node.type.name !== "paragraph"
        ? "label"
        : ((block.marker ? MARKER_KIND[block.marker] : undefined) ?? "text");
    push({ ...base, kind, from: block.from, to: block.to, innerFrom: inner.from, innerTo: inner.to });
  }
  return lines;
}

/** Wiersze w kształcie żądania — bez pozycji w dokumencie. */
export function commandLines(lines: readonly CvLine[]): CvCommandLine[] {
  return lines.map((line) => ({
    id: line.id,
    kind: line.kind,
    text: line.text,
    ...(line.section ? { section: line.section } : {}),
    ...(line.role != null ? { role: line.role } : {}),
  }));
}

/** Powód, dla którego polecenia nie da się wysłać — albo `null`. */
export function commandBlocker(lines: readonly CvLine[]): string | null {
  if (lines.length === 0) return "CV jest puste — nie ma czego zmieniać.";
  const total = lines.reduce((sum, line) => sum + line.text.length, 0);
  if (lines.length > CV_COMMAND_LINES_MAX || total > CV_COMMAND_TEXT_TOTAL_MAX) {
    return "To CV jest za długie na polecenie dla całego dokumentu. Skróć je ręcznie albo użyj AI na zaznaczonym fragmencie.";
  }
  return null;
}

// ── Podgląd planu na kartce ──────────────────────────────────────────────────

export type PlanTone = "remove" | "change" | "move";

export interface PlanMark {
  operation: number;
  tone: PlanTone;
  /** Węzeł wiersza (dekoracja węzła). */
  from: number;
  to: number;
  /** Nowa treść pokazywana pod wierszem (`change`); `**x**` = pogrubienie. */
  text?: string;
  /** Koniec treści wiersza — tu staje podgląd nowej treści. */
  at?: number;
  /** Nowe miejsce punktu na liście (`move`), od 1. */
  order?: number;
}

/** Co wybrane operacje zrobią z kartką — do dekoracji, zanim cokolwiek się zmieni. */
export function planMarks(
  lines: readonly CvLine[],
  operations: readonly CvPlanOperation[],
  selected: ReadonlySet<number>,
): PlanMark[] {
  const byId = new Map(lines.map((line) => [line.id, line]));
  const marks: PlanMark[] = [];
  for (const operation of operations) {
    if (!selected.has(operation.id)) continue;
    const rows = operation.lines.map((id) => byId.get(id)).filter((line): line is CvLine => line != null);
    rows.forEach((line, index) => {
      const base = { operation: operation.id, from: line.from, to: line.to };
      if (operation.type === "reorder") {
        marks.push({ ...base, tone: "move", order: index + 1 });
      } else if ((operation.type === "replace" || operation.type === "merge") && index === 0) {
        marks.push({ ...base, tone: "change", text: operation.text ?? "", at: line.innerTo });
      } else {
        marks.push({ ...base, tone: "remove" });
      }
    });
  }
  return marks;
}

/** Długość treści CV teraz i po wybranych operacjach (znaki, bez znaczników). */
export function planEffect(
  lines: readonly CvLine[],
  operations: readonly CvPlanOperation[],
  selected: ReadonlySet<number>,
): { before: number; after: number } {
  const size = (text: string) => text.replace(/\*\*/g, "").length;
  const byId = new Map(lines.map((line) => [line.id, line]));
  const before = lines.reduce((sum, line) => sum + size(line.text), 0);
  let after = before;
  for (const operation of operations) {
    if (!selected.has(operation.id) || operation.type === "reorder") continue;
    for (const id of operation.lines) after -= size(byId.get(id)?.text ?? "");
    if (operation.type === "replace" || operation.type === "merge") after += size(operation.text ?? "");
  }
  return { before, after: Math.max(0, after) };
}

const planKey = new PluginKey<DecorationSet>("cvEditorPlanPreview");

function newTextWidget(text: string): HTMLElement {
  const dom = document.createElement("span");
  dom.className = "cv-plan-new";
  dom.setAttribute("contenteditable", "false");
  for (const run of parseBoldMarkup(text)) {
    const part = document.createElement(run.b ? "strong" : "span");
    part.textContent = run.t;
    dom.appendChild(part);
  }
  return dom;
}

/** Dekoracje podglądu planu: przekreślone, zmieniane i przestawiane wiersze. */
export const CvEditorPlanPreview = Extension.create({
  name: "cvEditorPlanPreview",
  addProseMirrorPlugins() {
    return [
      new Plugin<DecorationSet>({
        key: planKey,
        state: {
          init: () => DecorationSet.empty,
          apply(transaction, current) {
            const marks = transaction.getMeta(planKey) as PlanMark[] | undefined;
            if (!marks) return transaction.docChanged ? DecorationSet.empty : current;
            const decorations: Decoration[] = [];
            for (const mark of marks) {
              decorations.push(
                Decoration.node(mark.from, mark.to, {
                  class: `cv-plan-${mark.tone}`,
                  "data-cv-plan": String(mark.operation),
                  ...(mark.order != null ? { "data-cv-plan-order": String(mark.order) } : {}),
                }),
              );
              if (mark.tone === "change" && mark.at != null && mark.text) {
                const text = mark.text;
                decorations.push(Decoration.widget(mark.at, () => newTextWidget(text), { side: 1, key: `plan-${mark.operation}` }));
              }
            }
            return DecorationSet.create(transaction.doc, decorations);
          },
        },
        props: { decorations: (state) => planKey.getState(state) },
      }),
    ];
  },
});

export function setPlanMarks(editor: Editor, marks: readonly PlanMark[]): void {
  if (editor.isDestroyed) return;
  editor.view.dispatch(editor.state.tr.setMeta(planKey, [...marks]).setMeta("addToHistory", false));
}

export function planMarkCount(state: EditorState): number {
  return planKey.getState(state)?.find().length ?? 0;
}

// ── Zastosowanie planu ───────────────────────────────────────────────────────

interface Edit {
  from: number;
  to: number;
  content: Fragment;
}

function inlineNodes(state: EditorState, markup: string): Fragment {
  const bold = state.schema.marks.bold;
  const nodes = parseBoldMarkup(markup.trim())
    .filter((run) => run.t.length > 0)
    .map((run) => state.schema.text(run.t, run.b && bold ? [bold.create()] : []));
  return Fragment.fromArray(nodes);
}

function sameLine(a: CvLine | undefined, b: CvLine): boolean {
  return a != null && a.kind === b.kind && a.text === b.text && a.from === b.from && a.to === b.to;
}

/**
 * Wybrane operacje jako jedna transakcja; `null`, gdy dokument zmienił się od
 * zamówienia planu albo nie zostało nic do zrobienia.
 */
export function applyPlan(state: EditorState, lines: readonly CvLine[], operations: readonly CvPlanOperation[]): Transaction | null {
  const current = cvLines(state.doc);
  const byId = new Map(lines.map((line) => [line.id, line]));
  const touched = operations.flatMap((operation) => operation.lines);
  if (touched.some((id) => !byId.has(id) || !sameLine(current[id], byId.get(id)!))) return null;

  const edits: Edit[] = [];
  const removals: CvLine[] = [];
  for (const operation of operations) {
    const rows = operation.lines.map((id) => byId.get(id)!);
    if (rows.length === 0) continue;
    if (operation.type === "remove") {
      removals.push(...rows);
    } else if (operation.type === "replace" || operation.type === "merge") {
      const content = inlineNodes(state, operation.text ?? "");
      if (content.size === 0) continue;
      edits.push({ from: rows[0].innerFrom, to: rows[0].innerTo, content });
      removals.push(...rows.slice(1));
    } else if (operation.type === "reorder") {
      // Punkty jednego stanowiska stoją zwykle w jednej liście; rozbitych nie ruszamy.
      const list = rows[0];
      if (rows.some((row) => row.blockFrom !== list.blockFrom) || rows.length !== list.siblings) continue;
      const items = rows.map((row) => state.doc.nodeAt(row.from)).filter((node): node is PMNode => node != null);
      if (items.length !== rows.length) continue;
      edits.push({ from: list.blockFrom + 1, to: list.blockTo - 1, content: Fragment.fromArray(items) });
    } else {
      // Stanowisko albo sekcja: ciągły zakres bloków dokumentu.
      edits.push({
        from: Math.min(...rows.map((row) => row.blockFrom)),
        to: Math.max(...rows.map((row) => row.blockTo)),
        content: Fragment.empty,
      });
    }
  }

  // Punkty usuwane pojedynczo; lista, z której znikają wszystkie, znika cała
  // (pusta lista nie jest poprawnym dokumentem).
  const perList = new Map<number, CvLine[]>();
  for (const row of removals) {
    if (row.kind === "bullet") perList.set(row.blockFrom, [...(perList.get(row.blockFrom) ?? []), row]);
    else edits.push({ from: row.from, to: row.to, content: Fragment.empty });
  }
  for (const rows of perList.values()) {
    if (rows.length === rows[0].siblings) edits.push({ from: rows[0].blockFrom, to: rows[0].blockTo, content: Fragment.empty });
    else for (const row of rows) edits.push({ from: row.from, to: row.to, content: Fragment.empty });
  }
  if (edits.length === 0) return null;

  // Od końca dokumentu: wcześniejsze pozycje zostają ważne.
  edits.sort((a, b) => b.from - a.from);
  const transaction = state.tr;
  for (const edit of edits) {
    if (edit.content.size === 0) transaction.delete(edit.from, edit.to);
    else transaction.replaceWith(edit.from, edit.to, edit.content);
  }
  const first = Math.min(edits[edits.length - 1].from, transaction.doc.content.size);
  transaction.setSelection(TextSelection.near(transaction.doc.resolve(first)));
  return closeHistory(transaction);
}
