/**
 * Polecenie własnymi słowami dla całego CV (Edytor CV 2, PR 4) — czysta logika.
 *
 * Edytor wysyła CV WIERSZ PO WIERSZU (blok dokumentu albo punkt listy, tekst
 * z pogrubieniem jako `**x**`), a serwer zwraca PLAN: operacje na numerach
 * wierszy, które przeszły kontrolę (`backend/app/services/cv_command_ai.py`).
 * Tutaj:
 *
 * - `cvLines` — wiersze dokumentu z pozycjami, po których plan da się nałożyć,
 * - `applyPlan` — wybrane operacje jako JEDNA transakcja i jeden krok historii.
 *
 * Plan odnosi się do zrzutu dokumentu z chwili zamówienia. Kartka jest wtedy
 * tylko do odczytu, a `applyPlan` i tak sprawdza, że wiersze się nie zmieniły.
 *
 * Edytor CV 3, PR 4 (asystent): `applyChanges` nakłada też nowe operacje
 * (`add`, `bold`, `unbold`, `considered_for`) i zwraca zakresy zmienionej
 * treści — `CvAssistantHighlight` pokazuje je na kartce na zielono.
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
import { termRanges } from "@/lib/cv-editor-issues";
import { parseBoldMarkup } from "@/lib/cv-qc";

/** Granice jak w schemacie trasy (`backend/app/api/cv_editor_ai.py`). */
/** Lista poprawek, ok. 15–20 punktów (15.10.2026; wcześniej 300 znaków). */
export const CV_COMMAND_MAX = 2000;
/** Tyle zmian asystent robi naraz; nadmiar serwer zgłasza (`truncated`). */
export const CV_COMMAND_OPERATIONS_MAX = 40;
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

/**
 * Czy edytor umie nałożyć operację na te wiersze. Jedyny przypadek „nie”:
 * zmiana kolejności punktów, które stoją w więcej niż jednej liście (serwer
 * widzi punkty stanowiska, nie listy dokumentu).
 */
export function canApply(operation: CvPlanOperation, lines: readonly CvLine[]): boolean {
  if (operation.type === "bold" || operation.type === "unbold") return (operation.terms ?? []).length > 0;
  const rows = operation.lines.map((id) => lines[id]);
  if (rows.length === 0 || rows.some((row) => row == null)) return false;
  if (operation.type === "reorder_roles") return rows.length >= 2 && rows.every((row) => row.kind === "role" && row.role != null);
  if (operation.type !== "reorder") return true;
  return rows.every((row) => row.kind === "bullet" && row.blockFrom === rows[0].blockFrom);
}

function sameLine(a: CvLine | undefined, b: CvLine): boolean {
  return a != null && a.kind === b.kind && a.text === b.text && a.from === b.from && a.to === b.to;
}

/** Zmieniona treść po nałożeniu planu — do podświetlenia na kartce. */
export interface ChangedRange {
  from: number;
  to: number;
}

/**
 * Wybrane operacje jako jedna transakcja; `null`, gdy dokument zmienił się od
 * zamówienia planu albo nie zostało nic do zrobienia.
 */
export function applyPlan(state: EditorState, lines: readonly CvLine[], operations: readonly CvPlanOperation[]): Transaction | null {
  return applyChanges(state, lines, operations)?.transaction ?? null;
}

/** Nowy punkt listy albo akapit — ten sam rodzaj co wiersz, za którym staje. */
function newBlock(state: EditorState, after: CvLine, markup: string): PMNode | null {
  const { listItem, paragraph } = state.schema.nodes;
  const content = inlineNodes(state, markup);
  if (content.size === 0 || !paragraph) return null;
  const block = paragraph.create(null, content);
  if (after.kind === "bullet") return listItem ? listItem.create(null, block) : null;
  return block;
}

/**
 * Całe stanowiska w nowej kolejności (`reorder_roles`) — jeden krok na
 * zakresie od pierwszego do ostatniego stanowiska. `order[k]` = numer
 * stanowiska na miejscu `k`. Zwraca przesunięcie pozycji sprzed kroku (treść
 * stanowisk przenosi się bez zmian, więc pozycja w stanowisku jedzie z nim)
 * i linie stanowisk, które zmieniły miejsce; `null`, gdy stanowiska nie stoją
 * jedno za drugim albo kolejność nie obejmuje każdego z nich raz.
 */
function moveRoles(
  transaction: Transaction,
  order: readonly (number | null)[],
): { shift: (range: ChangedRange) => ChangedRange; heads: ChangedRange[] } | null {
  const { roles } = cvOutline(transaction.doc);
  const valid = order.every((role) => role != null && roles[role] != null);
  if (!valid || order.length !== roles.length || new Set(order).size !== roles.length) return null;
  if (roles.some((role, index) => index > 0 && roles[index - 1].toIndex !== role.fromIndex)) return null;
  const start = roles[0].from;
  const end = roles[roles.length - 1].to;
  const doc = transaction.doc;
  const placed = new Map<number, number>();
  let content = Fragment.empty;
  let at = start;
  for (const role of order as number[]) {
    placed.set(role, at);
    content = content.append(doc.slice(roles[role].from, roles[role].to).content);
    at += roles[role].to - roles[role].from;
  }
  const heads: ChangedRange[] = [];
  (order as number[]).forEach((role, index) => {
    const head = doc.nodeAt(roles[role].from);
    if (role === index || !head) return;
    const from = placed.get(role)! + 1;
    heads.push({ from, to: from + head.content.size });
  });
  transaction.replaceWith(start, end, content);
  const shift = (range: ChangedRange): ChangedRange => {
    const index = roles.findIndex((role) => range.from >= role.from && range.from < role.to);
    if (index < 0) return range;
    const from = placed.get(index)! + (range.from - roles[index].from);
    return { from, to: from + (range.to - range.from) };
  };
  return { shift, heads };
}

/** Wystąpienia terminu poza tytułem i nagłówkami sekcji (tam pogrubienie nie służy). */
function termsInContent(doc: PMNode, terms: readonly string[]): ChangedRange[] {
  const ranges: ChangedRange[] = [];
  for (const term of terms) {
    for (const range of termRanges(doc, term)) {
      if (doc.resolve(range.from).parent.type.name === "heading") continue;
      ranges.push({ from: range.from, to: range.to });
    }
  }
  return ranges;
}

/**
 * Jak `applyPlan`, a do tego zakresy zmienionej treści w dokumencie po
 * zmianie (nowe i przeredagowane wiersze, pogrubione terminy).
 */
export function applyChanges(
  state: EditorState,
  lines: readonly CvLine[],
  operations: readonly CvPlanOperation[],
): { transaction: Transaction; changed: ChangedRange[] } | null {
  const current = cvLines(state.doc);
  const byId = new Map(lines.map((line) => [line.id, line]));
  const touched = operations.flatMap((operation) => operation.lines);
  if (touched.some((id) => !byId.has(id) || !sameLine(current[id], byId.get(id)!))) return null;
  // Operacji, której nie umiemy nałożyć, nie pomijamy po cichu — plan jest wtedy nieważny.
  if (operations.some((operation) => !canApply(operation, lines))) return null;

  const edits: Edit[] = [];
  const removals: CvLine[] = [];
  for (const operation of operations) {
    const rows = operation.lines.map((id) => byId.get(id)!);
    // Formatowanie i kolejność stanowisk idą po zmianach treści, na dokumencie po nich.
    if (operation.type === "bold" || operation.type === "unbold" || operation.type === "reorder_roles") continue;
    if (rows.length === 0) continue;
    if (operation.type === "remove") {
      removals.push(...rows);
    } else if (operation.type === "add") {
      const node = newBlock(state, rows[0], operation.text ?? "");
      if (!node) continue;
      edits.push({ from: rows[0].to, to: rows[0].to, content: Fragment.from(node) });
    } else if (operation.type === "replace" || operation.type === "merge" || operation.type === "considered_for") {
      const content = inlineNodes(state, operation.text ?? "");
      if (content.size === 0) continue;
      edits.push({ from: rows[0].innerFrom, to: rows[0].innerTo, content });
      removals.push(...rows.slice(1));
    } else if (operation.type === "reorder") {
      // Nowa kolejność dotyczy punktów z planu; pusty albo złożony punkt tej
      // samej listy (serwer go nie liczy) zostaje na swoim miejscu.
      const list = rows[0];
      const listNode = state.doc.nodeAt(list.blockFrom);
      const ordered = rows.map((row) => state.doc.nodeAt(row.from));
      if (!listNode || ordered.some((node) => node == null)) return null;
      const moved = new Set(rows.map((row) => row.from));
      const items: PMNode[] = [];
      let next = 0;
      listNode.forEach((child, offset) => {
        items.push(moved.has(list.blockFrom + 1 + offset) ? ordered[next++]! : child);
      });
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
  const formatting = operations.filter((operation) => operation.type === "bold" || operation.type === "unbold");
  const roleOrder = operations.find((operation) => operation.type === "reorder_roles");
  if (edits.length === 0 && formatting.length === 0 && !roleOrder) return null;

  // Od końca dokumentu: wcześniejsze pozycje zostają ważne. W tym samym
  // miejscu najpierw dłuższa zmiana (usunięcie następnego wiersza przed
  // wstawieniem za poprzednim), a wstawienia od ostatniego w planie — staną
  // w kolejności planu.
  const order = new Map(edits.map((edit, index) => [edit, index]));
  edits.sort((a, b) => b.from - a.from || b.to - a.to || order.get(b)! - order.get(a)!);
  const transaction = state.tr;
  const inserted: Array<{ range: ChangedRange; afterStep: number }> = [];
  for (const edit of edits) {
    if (edit.content.size === 0) transaction.delete(edit.from, edit.to);
    else {
      transaction.replaceWith(edit.from, edit.to, edit.content);
      inserted.push({ range: { from: edit.from, to: edit.from + edit.content.size }, afterStep: transaction.steps.length });
    }
  }
  // Nowa treść w dokumencie po wszystkich krokach (wcześniejsze edycje przesuwają ją).
  let changed: ChangedRange[] = inserted.map(({ range, afterStep }) => {
    const later = transaction.mapping.slice(afterStep);
    return { from: later.map(range.from, 1), to: later.map(range.to, -1) };
  });
  let first =
    edits.length > 0 ? Math.min(transaction.mapping.map(edits[edits.length - 1].from), transaction.doc.content.size) : null;
  // Kolejność stanowisk na dokumencie po zmianach treści: numery stanowisk się
  // nie zmieniły (usunięcia stanowiska z tą operacją serwer nie przepuszcza).
  if (roleOrder) {
    const moved = moveRoles(
      transaction,
      roleOrder.lines.map((id) => byId.get(id)!.role),
    );
    if (!moved) return null;
    changed = [...changed.map(moved.shift), ...moved.heads];
    first = first != null ? moved.shift({ from: first, to: first }).from : (moved.heads[0]?.from ?? null);
  }
  // Pogrubienie na treści po zmianach — także na właśnie dopisanych wierszach.
  const bold = state.schema.marks.bold;
  if (bold) {
    for (const operation of formatting) {
      for (const range of termsInContent(transaction.doc, operation.terms ?? [])) {
        const has = transaction.doc.rangeHasMark(range.from, range.to, bold);
        if (operation.type === "bold" && !has) transaction.addMark(range.from, range.to, bold.create());
        else if (operation.type === "unbold" && has) transaction.removeMark(range.from, range.to, bold);
        else continue;
        changed.push(range);
      }
    }
  }
  if (!transaction.docChanged) return null;
  if (first != null) {
    transaction.setSelection(TextSelection.near(transaction.doc.resolve(Math.min(first, transaction.doc.content.size))));
  }
  return { transaction: closeHistory(transaction), changed: changed.filter((range) => range.to > range.from) };
}

/** Plan podzielony na to, co edytor nałoży, i to, czego nałożyć nie umie albo co nic nie zmienia. */
export interface CvPlanSplit {
  /** Zmiana do nałożenia (wszystkie `applied` naraz) albo `null`, gdy nic nie weszło. */
  result: { transaction: Transaction; changed: ChangedRange[] } | null;
  applied: CvPlanOperation[];
  /** Edytor nie umie nałożyć (`canApply`: np. punkty z dwóch list). */
  unsupported: CvPlanOperation[];
  /** Nic by nie zmieniła (np. pogrubienie słów, które już są pogrubione). */
  idle: CvPlanOperation[];
}

/**
 * Jak `applyChanges`, ale operacja, która nic nie zmienia albo której edytor
 * nie umie nałożyć, wypada z planu zamiast unieważniać cały plan (zgłoszenie
 * 23.10.2026: pogrubienie już pogrubionych wymagań kończyło się „CV zmieniło
 * się w międzyczasie”). Operacje idą po kolei: każda wchodzi, gdy plan z nią
 * daje inny dokument niż bez niej — pogrubienie liczone jest więc także na
 * treści dopisanej wcześniejszymi operacjami. Wiersze muszą być bieżące —
 * zmienione CV sprawdza wołający.
 */
export function splitPlan(state: EditorState, lines: readonly CvLine[], operations: readonly CvPlanOperation[]): CvPlanSplit {
  const split: CvPlanSplit = { result: null, applied: [], unsupported: [], idle: [] };
  let doc = state.doc;
  for (const operation of operations) {
    if (!canApply(operation, lines)) {
      split.unsupported.push(operation);
      continue;
    }
    const trial = applyChanges(state, lines, [...split.applied, operation]);
    if (!trial || trial.transaction.doc.eq(doc)) {
      split.idle.push(operation);
      continue;
    }
    split.applied.push(operation);
    split.result = trial;
    doc = trial.transaction.doc;
  }
  return split;
}

// ── Podświetlenie zmian asystenta (Edytor CV 3, PR 4) ───────────────────────

const highlightKey = new PluginKey<DecorationSet>("cvAssistantHighlight");

/**
 * Zielone tło na treści, którą asystent właśnie zmienił. Dekoracja widoku —
 * nie trafia do `getHTML()`, przesuwa się razem z pisaniem i znika przy
 * następnej wiadomości (albo po „Cofnij”).
 */
export const CvAssistantHighlight = Extension.create({
  name: "cvAssistantHighlight",
  addProseMirrorPlugins() {
    return [
      new Plugin<DecorationSet>({
        key: highlightKey,
        state: {
          init: () => DecorationSet.empty,
          apply(transaction, current) {
            const ranges = transaction.getMeta(highlightKey) as ChangedRange[] | undefined;
            if (ranges) {
              return DecorationSet.create(
                transaction.doc,
                ranges
                  .filter((range) => range.to > range.from && range.to <= transaction.doc.content.size)
                  .map((range) => Decoration.inline(range.from, range.to, { class: "cv-assistant-new" })),
              );
            }
            return current.map(transaction.mapping, transaction.doc);
          },
        },
        props: { decorations: (state) => highlightKey.getState(state) },
      }),
    ];
  },
});

export function setAssistantHighlight(editor: Editor, ranges: readonly ChangedRange[]): void {
  if (editor.isDestroyed) return;
  editor.view.dispatch(editor.state.tr.setMeta(highlightKey, [...ranges]).setMeta("addToHistory", false));
}

export function assistantHighlightCount(state: EditorState): number {
  return highlightKey.getState(state)?.find().length ?? 0;
}
