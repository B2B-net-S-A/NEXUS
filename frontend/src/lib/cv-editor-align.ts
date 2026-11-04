/**
 * Wyrównanie tekstu w edytorze CV (decyzja J1 Artura, 14.10.2026).
 *
 * CV jest domyślnie wyjustowane; reguła klienta może przełączyć je „do lewej”
 * (serwer podaje to jako `text_align` stanu CV). Akapit może mieć wyrównanie
 * jawne (`style="text-align: …"`, rozszerzenie TextAlign) — to wygrywa także
 * w pliku Word (`cv_approved_docx`). Klauzula zgody RODO nie jest ruszana:
 * ma stałe wyrównanie i jest chroniona przez `CvEditorStructure`.
 */

import type { Node as PMNode } from "@tiptap/pm/model";
import type { EditorState } from "@tiptap/pm/state";

import { isRodoNode, type CvCommand } from "./cv-editor-blocks";

export type CvAlign = "left" | "justify";

export const CV_DEFAULT_ALIGN: CvAlign = "justify";

/** Wartość z serwera albo domyślna — nieznana wartość nie psuje kartki. */
export function normalizeCvAlign(value: unknown): CvAlign {
  return value === "left" ? "left" : CV_DEFAULT_ALIGN;
}

/**
 * Wyrównanie akapitu z kursorem, tak jak zobaczy je Word: jawne albo domyślne
 * CV. `null`, gdy kursor nie stoi w akapicie, który da się wyrównać
 * (nagłówek, klauzula zgody).
 */
export function cvAlignAt(state: EditorState, fallback: CvAlign): CvAlign | null {
  const alignOf = (node: PMNode): CvAlign => {
    const explicit = node.attrs.textAlign;
    return explicit === "left" || explicit === "justify" ? explicit : fallback;
  };
  const { $from, from, to, empty } = state.selection;
  if (!empty) {
    // Zaznaczenie przez kilka akapitów (także „zaznacz wszystko”): stan
    // pierwszego akapitu, który da się wyrównać.
    let found: CvAlign | null = null;
    state.doc.nodesBetween(from, to, (node) => {
      if (found !== null) return false;
      if (node.type.name !== "paragraph") return true;
      if (!isRodoNode(node)) found = alignOf(node);
      return false;
    });
    return found;
  }
  for (let depth = $from.depth; depth > 0; depth -= 1) {
    const node = $from.node(depth);
    if (node.type.name !== "paragraph") continue;
    return isRodoNode(node) ? null : alignOf(node);
  }
  return null;
}

/**
 * Ustawia wyrównanie akapitów w zaznaczeniu (albo akapitu z kursorem) — jak
 * w Wordzie. Pomija klauzulę zgody. `null`, gdy nic się nie zmienia.
 */
export function setCvAlign(align: CvAlign): CvCommand {
  return (state) => alignBetween(state, state.selection.from, state.selection.to, align);
}

/**
 * „Wyjustuj całe CV” / „Całe CV do lewej” z menu „Więcej” (Edytor CV 3, PR 3):
 * wszystkie akapity poza klauzulą zgody, bez ruszania zaznaczenia.
 */
export function setCvAlignEverywhere(align: CvAlign): CvCommand {
  return (state) => alignBetween(state, 0, state.doc.content.size, align);
}

function alignBetween(state: EditorState, from: number, to: number, align: CvAlign) {
  const tr = state.tr;
  let changed = false;
  state.doc.nodesBetween(from, to, (node, pos) => {
    if (node.type.name !== "paragraph") return true;
    if (!isRodoNode(node) && node.attrs.textAlign !== align) {
      tr.setNodeAttribute(pos, "textAlign", align);
      changed = true;
    }
    return false;
  });
  return changed ? tr : null;
}
