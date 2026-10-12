/**
 * Pilnowanie struktury CV w edytorze (jedna wtyczka ProseMirror):
 *
 * - **Klauzula zgody RODO jest stała** (decyzja Artura 12.10.2026). Po każdej
 *   zmianie dokument ma dokładnie jedną klauzulę — tę z wczytania — i stoi ona
 *   na końcu. Naprawia to transakcja DOŁĄCZANA, a nie filtr odrzucający zmianę:
 *   filtr blokowałby „zaznacz wszystko i usuń”, a odrzucone wczytanie nowszej
 *   wersji zostawiłoby w oknie starą treść do zapisania na cudzej. Serwer
 *   pilnuje tego samego niezależnie (`cv_rodo_clause.keep_rodo_clause`).
 * - **Znaczniki struktury żyją tylko na poziomie dokumentu.** Akapit `role`,
 *   który trafił do listy, traci znacznik — serwer czytał taki punkt raz jako
 *   stanowisko, raz jako obowiązek.
 * - Dekoracje widoku (nie trafiają do HTML-a): blokada klauzuli, sekcja bloku
 *   dla arkusza kartki, stanowisko pod kursorem, etykieta technologii.
 */

import { Extension, type Editor, type Extensions } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";
import { Plugin, PluginKey, type EditorState, type Transaction } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import StarterKit from "@tiptap/starter-kit";

import { CV_TEMPLATE_LABELS, cvContext, cvOutline, isRodoNode } from "./cv-editor-blocks";
import { CvEditorSection } from "./cv-editor-section";

/** Transakcja wczytania treści: omija blokadę i odświeża zapamiętaną klauzulę. */
const LOAD_META = "cvEditorLoad";

interface StructureState {
  /** Klauzula zgody z wczytanej treści; `null`, gdy CV jej nie ma. */
  clause: PMNode | null;
}

const structureKey = new PluginKey<StructureState>("cvEditorStructure");

function clauseOf(doc: PMNode): PMNode | null {
  return cvOutline(doc).rodo?.node ?? null;
}

function repair(state: EditorState, clause: PMNode | null): Transaction | null {
  const tr = state.tr;
  state.doc.descendants((node, position, parent) => {
    if (parent && parent !== state.doc && typeof node.attrs.cvSection === "string") {
      tr.setNodeMarkup(position, undefined, { ...node.attrs, cvSection: null });
    }
  });
  if (clause) {
    const { blocks } = cvOutline(state.doc);
    const clauses = blocks.filter((block) => isRodoNode(block.node));
    const last = blocks[blocks.length - 1];
    const kept = last && last.node.eq(clause) ? last : null;
    if (!kept || clauses.length !== 1) {
      // Najpierw klauzula na koniec (dokument nie może zostać pusty), potem
      // od końca znikają zmienione, przeniesione i wklejone drugi raz.
      if (!kept) tr.insert(state.doc.content.size, clause);
      for (const block of [...clauses].reverse()) {
        if (block !== kept) tr.delete(block.from, block.to);
      }
    }
  }
  return tr.docChanged ? tr : null;
}

const TECH_LABELS = Object.values(CV_TEMPLATE_LABELS).map((labels) => labels.technologies);

function decorations(state: EditorState): DecorationSet {
  const { outline, role } = cvContext(state);
  const marks: Decoration[] = [];
  for (const block of outline.blocks) {
    if (block.marker === "technologies") {
      // Word pogrubia samą etykietę „Technologie:”, resztę linii zostawia zwykłą.
      const label = TECH_LABELS.find((text) => block.node.textContent.startsWith(text));
      if (label) {
        const start = block.from + 1;
        marks.push(Decoration.inline(start, start + label.length, { class: "cv-tech-label" }));
      }
    }
    const attrs: Record<string, string> = {};
    if (block.section) attrs["data-cv-in"] = block.section;
    if (block === outline.rodo) {
      attrs.class = "cv-rodo-locked";
      attrs.contenteditable = "false";
    } else if (role && block.index >= role.fromIndex && block.index < role.toIndex) {
      attrs.class = "cv-role-current";
    }
    if (Object.keys(attrs).length) marks.push(Decoration.node(block.from, block.to, attrs));
  }
  return DecorationSet.create(state.doc, marks);
}

export const CvEditorStructure = Extension.create({
  name: "cvEditorStructure",
  addProseMirrorPlugins() {
    return [
      new Plugin<StructureState>({
        key: structureKey,
        state: {
          init: (_config, state) => ({ clause: clauseOf(state.doc) }),
          apply: (tr, value) => (tr.getMeta(LOAD_META) ? { clause: clauseOf(tr.doc) } : value),
        },
        appendTransaction(transactions, _oldState, newState) {
          if (!transactions.some((tr) => tr.docChanged)) return null;
          if (transactions.some((tr) => tr.getMeta(LOAD_META))) return null;
          return repair(newState, structureKey.getState(newState)?.clause ?? null);
        },
        props: { decorations },
      }),
    ];
  },
});

/** Rozszerzenia edytora CV — jedna lista dla okna, harnessu i testów. */
export function cvEditorExtensions(): Extensions {
  return [StarterKit, CvEditorSection, CvEditorStructure];
}

/**
 * Wczytuje treść poza historią cofania. Zwykłe `setContent` jest cofalne:
 * „Cofnij” tuż po otwarciu opróżniało CV, a autozapis utrwalał pustą treść.
 */
export function loadCvHtml(editor: Editor, html: string): void {
  editor
    .chain()
    .setMeta("addToHistory", false)
    .setMeta(LOAD_META, true)
    .setContent(html, { emitUpdate: false })
    .run();
}
