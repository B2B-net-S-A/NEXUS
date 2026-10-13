/**
 * Pilnowanie struktury CV w edytorze (jedna wtyczka ProseMirror):
 *
 * - **Klauzula zgody RODO jest stała** (decyzja Artura 12.10.2026). Po każdej
 *   zmianie dokument ma dokładnie jedną klauzulę — tę z wczytania — i stoi ona
 *   na końcu. Usuniętą w całości, przeniesioną albo wklejoną drugi raz naprawia
 *   transakcja DOŁĄCZANA: filtr odrzucający każdą zmianę blokowałby „zaznacz
 *   wszystko i usuń”, a odrzucone wczytanie nowszej wersji zostawiłoby w oknie
 *   starą treść do zapisania na cudzej. Filtr odrzuca tylko zmianę, po której
 *   KAWAŁEK klauzuli zostałby poza nią (`clauseLeaks`) — tego naprawa nie
 *   umie odkręcić. Serwer pilnuje klauzuli niezależnie
 *   (`cv_rodo_clause.keep_rodo_clause`).
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
import { CvEditorAiPending } from "./cv-editor-ai";
import { CvEditorIssueMarks } from "./cv-editor-issue-marks";
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

/**
 * Czy po tej zmianie tekst klauzuli przetrwałby POZA nietkniętą klauzulą.
 *
 * Tak kończy się Delete na końcu ostatniego akapitu albo punktu (ProseMirror
 * dokleja następny blok — klawisz obsługuje model, więc `contenteditable`
 * go nie zatrzyma), usunięcie zaznaczenia sięgającego w głąb klauzuli i tekst
 * wpisany w nią. Naprawa dołożyłaby wtedy klauzulę drugi raz, a jej doklejony
 * tekst poszedłby do klienta jako treść CV. Klauzula usunięta w całości
 * (zaznacz wszystko i usuń) nie przecieka — nic z niej nie zostaje.
 */
function clauseLeaks(tr: Transaction, doc: PMNode, clause: PMNode): boolean {
  const current = cvOutline(doc).rodo;
  if (!current || !current.node.eq(clause)) return false;
  const from = tr.mapping.map(current.from + 1, 1);
  const to = tr.mapping.map(current.to - 1, -1);
  if (to <= from) return false;
  const start = tr.doc.resolve(from);
  return !(start.depth === 1 && start.parent.eq(clause));
}

/** Zakres do usunięcia razem z punktem i listą, które po zniknięciu akapitu zostałyby puste. */
function removableRange(doc: PMNode, position: number, node: PMNode): [number, number] {
  const at = doc.resolve(position);
  let from = position;
  let to = position + node.nodeSize;
  for (let depth = at.depth; depth > 0 && at.node(depth).childCount === 1; depth -= 1) {
    from = at.before(depth);
    to = at.after(depth);
  }
  return [from, to];
}

/**
 * Kopia klauzuli w akapicie: cały akapit (`whole`) albo zakres jej tekstu na
 * początku lub końcu akapitu, z którym się skleiła — po wklejeniu ze schowka,
 * po Backspace na jej początku (w liście Tiptap przenosi treść przez „usuń
 * i wstaw”, czego mapowanie pozycji w `clauseLeaks` nie pokazuje).
 */
function clauseCopy(node: PMNode, clause: PMNode): "whole" | [number, number] | null {
  if (!node.isTextblock) return null;
  const own = clause.textContent;
  const size = node.content.size;
  if (node.textContent === own) return "whole";
  if (size <= own.length) return null;
  if (node.textBetween(0, own.length) === own) return [0, own.length];
  if (node.textBetween(size - own.length, size) === own) return [size - own.length, size];
  return null;
}

function repair(state: EditorState, clause: PMNode | null): Transaction | null {
  const tr = state.tr;
  const drop: Array<[number, number]> = [];
  const blocks = clause ? cvOutline(state.doc).blocks : [];
  const last = blocks[blocks.length - 1];
  const kept = clause && last && last.node.eq(clause) ? last : null;
  state.doc.descendants((node, position, parent) => {
    const top = parent === state.doc;
    if (kept && top && position === kept.from) return false;
    const copy = clause ? clauseCopy(node, clause) : null;
    if (copy === "whole") {
      // Także w głębi listy: wklejona z treścią innego CV poszłaby do klienta
      // jako punkt obowiązków.
      drop.push(removableRange(state.doc, position, node));
      return false;
    }
    if (copy) {
      // Z akapitu, z którym się skleiła, znika tylko jej tekst.
      drop.push([position + 1 + copy[0], position + 1 + copy[1]]);
      if (node.attrs.cvSection === "rodo") {
        tr.setNodeMarkup(position, undefined, { ...node.attrs, cvSection: null });
      }
      return false;
    }
    if (!top && typeof node.attrs.cvSection === "string") {
      tr.setNodeMarkup(position, undefined, { ...node.attrs, cvSection: null });
    }
    return true;
  });
  if (clause) {
    // Klauzula na koniec (dokument nie może zostać pusty); znikają też akapity,
    // które ją udają: zmieniona, przeniesiona, cudza ze znacznikiem.
    if (!kept) tr.insert(state.doc.content.size, clause);
    for (const block of blocks) {
      if (block !== kept && isRodoNode(block.node) && !clauseCopy(block.node, clause)) {
        drop.push([block.from, block.to]);
      }
    }
  }
  // Od końca: wcześniejsze pozycje zostają ważne.
  for (const [from, to] of drop.sort((first, second) => second[0] - first[0])) tr.delete(from, to);
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
        filterTransaction(tr, state) {
          if (!tr.docChanged || tr.getMeta(LOAD_META)) return true;
          const clause = structureKey.getState(state)?.clause;
          return !clause || !clauseLeaks(tr, state.doc, clause);
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
  return [StarterKit, CvEditorSection, CvEditorStructure, CvEditorIssueMarks, CvEditorAiPending];
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
