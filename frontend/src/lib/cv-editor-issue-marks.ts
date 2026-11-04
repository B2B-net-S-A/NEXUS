/**
 * Znaczniki uwag przy tekście CV w edytorze (Edytor CV 2, PR 2).
 *
 * Wyłącznie dekoracje widoku: `getHTML()` ich nie zawiera, więc nie trafiają
 * do zapisu, do Worda ani do kontroli AI. Panel „Do poprawy” podaje zakresy
 * policzone w `lib/cv-editor-issues.ts`; między przeliczeniami znaczniki
 * przesuwają się razem z tekstem. „Pokaż w CV” ustawia jedno wyróżnione
 * miejsce (`focus`), które gaśnie po chwili albo przy następnym wskazaniu.
 */

import { Extension, type Editor } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";
import { Plugin, PluginKey, TextSelection } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

import type { IssueMark, IssueRange } from "./cv-editor-issues";

interface MarksMeta {
  marks?: readonly IssueMark[];
  focus?: readonly IssueRange[] | null;
}

interface MarksState {
  marks: DecorationSet;
  focus: DecorationSet;
}

const marksKey = new PluginKey<MarksState>("cvEditorIssueMarks");

function inBounds(doc: PMNode, range: IssueRange): boolean {
  return range.from >= 0 && range.to <= doc.content.size && range.from < range.to;
}

/** Zakres blokowy = dekoracja każdego bloku tekstu w zakresie; fragment linii = dekoracja w tekście. */
function decorate(doc: PMNode, range: IssueRange, className: string): Decoration[] {
  if (!inBounds(doc, range)) return [];
  if (!range.block) return [Decoration.inline(range.from, range.to, { class: className })];
  const blocks: Decoration[] = [];
  doc.nodesBetween(range.from, range.to, (node, position) => {
    if (!node.isTextblock) return true;
    blocks.push(Decoration.node(position, position + node.nodeSize, { class: className }));
    return false;
  });
  return blocks;
}

function markSet(doc: PMNode, marks: readonly IssueMark[]): DecorationSet {
  return DecorationSet.create(
    doc,
    marks.flatMap((mark) =>
      decorate(doc, mark, `${mark.block ? "cv-issue-block" : "cv-issue-term"} cv-issue--${mark.tone}`),
    ),
  );
}

export const CvEditorIssueMarks = Extension.create({
  name: "cvEditorIssueMarks",
  addProseMirrorPlugins() {
    return [
      new Plugin<MarksState>({
        key: marksKey,
        state: {
          init: () => ({ marks: DecorationSet.empty, focus: DecorationSet.empty }),
          apply(tr, value) {
            const meta = tr.getMeta(marksKey) as MarksMeta | undefined;
            let { marks, focus } = value;
            if (tr.docChanged) {
              marks = marks.map(tr.mapping, tr.doc);
              // Wyróżnione miejsce dotyczy treści sprzed zmiany.
              focus = DecorationSet.empty;
            }
            if (meta?.marks) marks = markSet(tr.doc, meta.marks);
            if (meta && "focus" in meta) {
              focus = meta.focus
                ? DecorationSet.create(
                    tr.doc,
                    meta.focus.flatMap((range) => decorate(tr.doc, range, "cv-issue-focus")),
                  )
                : DecorationSet.empty;
            }
            return marks === value.marks && focus === value.focus ? value : { marks, focus };
          },
        },
        props: {
          decorations(state) {
            const value = marksKey.getState(state);
            if (!value) return null;
            return value.focus === DecorationSet.empty
              ? value.marks
              : value.marks.add(state.doc, value.focus.find());
          },
        },
      }),
    ];
  },
});

/** Podmienia znaczniki uwag; transakcja nie zmienia treści ani historii cofania. */
export function setIssueMarks(editor: Editor, marks: readonly IssueMark[]): void {
  if (editor.isDestroyed) return;
  editor.view.dispatch(editor.state.tr.setMeta(marksKey, { marks }).setMeta("addToHistory", false));
}

export function clearIssueFocus(editor: Editor): void {
  if (editor.isDestroyed) return;
  editor.view.dispatch(editor.state.tr.setMeta(marksKey, { focus: null }).setMeta("addToHistory", false));
}

/**
 * „Pokaż w CV”: wyróżnia miejsca (po poprawce bywa ich kilka), stawia kursor
 * przy pierwszym i przewija do niego kartkę. Wołający gasi wyróżnienie przez
 * `clearIssueFocus` (po chwili).
 */
export function showIssueInCv(editor: Editor, where: IssueRange | readonly IssueRange[]): void {
  if (editor.isDestroyed) return;
  const ranges = (Array.isArray(where) ? where : [where as IssueRange]).filter((range) =>
    inBounds(editor.state.doc, range),
  );
  const range = ranges[0];
  if (!range) return;
  // Blok: kursor na początek jego tekstu; fragment: tuż przed nim.
  const anchor = Math.min(range.block ? range.from + 1 : range.from, editor.state.doc.content.size);
  const transaction = editor.state.tr
    .setSelection(TextSelection.near(editor.state.doc.resolve(anchor)))
    .setMeta(marksKey, { focus: ranges })
    .setMeta("addToHistory", false);
  editor.view.dispatch(transaction);
  const at = editor.view.domAtPos(anchor).node;
  const element = at instanceof Element ? at : at.parentElement;
  element?.scrollIntoView?.({ block: "center", behavior: "smooth" });
}

/** Liczba dekoracji (test i diagnostyka): znaczniki uwag i wyróżnione miejsce. */
export function issueMarkCount(editor: Editor): { marks: number; focus: number } {
  const value = marksKey.getState(editor.state);
  return { marks: value?.marks.find().length ?? 0, focus: value?.focus.find().length ?? 0 };
}
