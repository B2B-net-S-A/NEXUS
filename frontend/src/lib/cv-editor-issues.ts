/**
 * Panel „Do poprawy” w edytorze CV (Edytor CV 2, PR 2) — czysta logika.
 *
 * QC, uwagi generatora i kontrola AI opisują ZAPISANĄ treść blokami tekstu,
 * a edytor trzyma dokument ProseMirror, który rekruter właśnie zmienia. Nie
 * mają wspólnego indeksu bloków, więc miejsce uwagi szuka się po tym, co
 * widać: po numerze stanowiska w sekcji doświadczenia (lustro `cv_qc.cv_roles`),
 * po etykiecie roli, po terminie w tekście albo po treści całej linii. Uwaga,
 * której miejsca już nie ma, po prostu nie ma znacznika — nic nie zgaduje.
 *
 * Poprawki liczy serwer na treści z edytora (`POST …/qc/transform`), a tutaj
 * wynik zamienia się w JEDNĄ transakcję obejmującą tylko zmieniony zakres:
 * jedno „Cofnij” wraca do stanu sprzed poprawki, kursor zostaje na miejscu.
 *
 * Moduł nie importuje `@tiptap/react`.
 */

import { createDocument } from "@tiptap/core";
import { closeHistory } from "@tiptap/pm/history";
import { Fragment, Slice, type Node as PMNode } from "@tiptap/pm/model";
import { TextSelection, type EditorState, type Transaction } from "@tiptap/pm/state";

import type { CvReviewFinding } from "@/lib/api/cvEditorIssues";
import type { QcCheck, QcFix, QcFixAction } from "@/lib/api/cvQc";
import { cvOutline, type CvOutline, type CvRole } from "@/lib/cv-editor-blocks";
import {
  countForm,
  itemTarget,
  normalizeQcText,
  roleGaps,
  roleLabelParts,
  termRegExp,
  type IssueTarget,
} from "@/lib/cv-qc";

export interface IssueRange {
  from: number;
  to: number;
  /** Całe bloki tekstu (akapit, punkt) zamiast fragmentu linii. */
  block: boolean;
}

/** `blocking` zatrzymuje wysyłkę CV, `note` to podpowiedź. */
export type IssueTone = "blocking" | "note";

export interface IssueMark extends IssueRange {
  tone: IssueTone;
}

// ── Tekst dokumentu ──────────────────────────────────────────────────────────

/** Znak w miejscu węzła bez tekstu (twarda spacja wiersza) — pozycje zostają zgodne z dokumentem. */
const LEAF = "￼";

interface TextBlock {
  node: PMNode;
  /** Pozycja PRZED blokiem; tekst zaczyna się na `position + 1`. */
  position: number;
  text: string;
}

/** Bloki tekstu dokumentu bez klauzuli zgody (jest stała — uwagi jej nie dotyczą). */
function textBlocks(doc: PMNode, outline: CvOutline, within?: { from: number; to: number }): TextBlock[] {
  const blocks: TextBlock[] = [];
  doc.descendants((node, position) => {
    if (outline.rodo && position === outline.rodo.from) return false;
    if (within && (position + node.nodeSize <= within.from || position >= within.to)) return false;
    if (!node.isTextblock) return true;
    blocks.push({ node, position, text: node.textBetween(0, node.content.size, undefined, LEAF) });
    return false;
  });
  return blocks;
}

// ── Miejsce uwagi w dokumencie ───────────────────────────────────────────────

/** Stanowiska w sekcji doświadczenia — w tej kolejności serwer nadaje `role_index`. */
function experienceRoles(outline: CvOutline): CvRole[] {
  return outline.roles.filter((role) => outline.blocks[role.fromIndex]?.section === "experience");
}

function findRole(doc: PMNode, outline: CvOutline, roleIndex: number | null, label: string | null): CvRole | null {
  const numbered = roleIndex != null ? experienceRoles(outline)[roleIndex] : undefined;
  if (numbered) return numbered;
  const parts = label ? roleLabelParts(label) : [];
  if (parts.length === 0) return null;
  return (
    outline.roles.find((role) => {
      const text = normalizeQcText(doc.textBetween(role.from, role.to, " "));
      return parts.every((part) => text.includes(part));
    }) ?? null
  );
}

interface TermSearch {
  within?: { from: number; to: number };
  /** Pomiń wystąpienia z pogrubieniem (sprawdzenia „pogrubione w CV”). */
  unboldedOnly?: boolean;
  limit?: number;
}

/** Wystąpienia terminu w tekście CV (granice słowa jak w QC), w kolejności dokumentu. */
export function termRanges(doc: PMNode, term: string, search: TermSearch = {}, outline = cvOutline(doc)): IssueRange[] {
  const pattern = termRegExp(term);
  if (!pattern) return [];
  const bold = doc.type.schema.marks.bold;
  const ranges: IssueRange[] = [];
  for (const block of textBlocks(doc, outline, search.within)) {
    for (const match of block.text.matchAll(pattern)) {
      if (!match[0]) continue;
      const from = block.position + 1 + (match.index ?? 0);
      const to = from + match[0].length;
      if (search.unboldedOnly && bold && doc.rangeHasMark(from, to, bold)) continue;
      ranges.push({ from, to, block: false });
      if (search.limit && ranges.length >= search.limit) return ranges;
    }
  }
  return ranges;
}

/** Blok, którego cały tekst to podana linia (odstępy i wielkość liter bez znaczenia). */
function lineRange(doc: PMNode, outline: CvOutline, text: string): IssueRange | null {
  const wanted = normalizeQcText(text);
  if (!wanted) return null;
  const block = textBlocks(doc, outline).find((candidate) => normalizeQcText(candidate.text) === wanted);
  return block ? { from: block.position, to: block.position + block.node.nodeSize, block: true } : null;
}

/** Tytuł stanowiska — pierwszy blok roli. */
function roleTitleRange(outline: CvOutline, role: CvRole): IssueRange {
  return { from: role.from, to: outline.blocks[role.fromIndex].to, block: true };
}

/**
 * Pozycja w dokumencie dla miejsca z uwagi; `null`, gdy tego miejsca już nie
 * ma (tekst zmieniono po zapisie, na którym policzono listę).
 */
export function locateTarget(doc: PMNode, target: IssueTarget, outline = cvOutline(doc)): IssueRange | null {
  if (target.kind === "line") return lineRange(doc, outline, target.text);
  const role = findRole(doc, outline, target.roleIndex, target.label);
  if (target.kind === "role") return role ? roleTitleRange(outline, role) : null;
  const inRole = role ? termRanges(doc, target.term, { within: role, limit: 1 }, outline)[0] : undefined;
  return inRole ?? termRanges(doc, target.term, { limit: 1 }, outline)[0] ?? (role ? roleTitleRange(outline, role) : null);
}

// ── Znaczniki przy tekście ───────────────────────────────────────────────────

const BOLD_CHECKS = new Set(["must_bolded", "nice_bolded"]);
/** Górny limit znaczników — długie CV z częstym terminem nie zamula widoku. */
const MAX_MARKS = 300;

/**
 * Znaczniki uwag w bieżącym dokumencie: stanowiska z brakiem opisu, terminy
 * z niezaliczonych sprawdzeń i linie wskazane przez kontrolę AI. Liczone od
 * zera po każdej zmianie treści — uwaga, której miejsce zniknęło, znika.
 */
export function issueMarks(doc: PMNode, checks: readonly QcCheck[], findings: readonly CvReviewFinding[]): IssueMark[] {
  const outline = cvOutline(doc);
  const marks: IssueMark[] = [];
  for (const gap of roleGaps([...checks])) {
    const role = findRole(doc, outline, gap.roleIndex, gap.role);
    if (role) marks.push({ ...roleTitleRange(outline, role), tone: gap.blocking.length > 0 ? "blocking" : "note" });
  }
  const seen = new Set<string>();
  for (const check of checks) {
    if (check.status !== "fail" && check.status !== "manual") continue;
    const tone: IssueTone = check.status === "fail" && check.severity === "blocking" ? "blocking" : "note";
    for (const item of check.items) {
      const target = itemTarget(item);
      if (target?.kind !== "term") continue;
      const key = `${tone}:${normalizeQcText(target.term)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const search = { unboldedOnly: BOLD_CHECKS.has(check.key), limit: MAX_MARKS - marks.length };
      if (search.limit <= 0) return marks;
      for (const range of termRanges(doc, target.term, search, outline)) marks.push({ ...range, tone });
    }
  }
  for (const finding of findings) {
    const range = lineRange(doc, outline, finding.text);
    if (range) marks.push({ ...range, tone: "note" });
  }
  return marks.slice(0, MAX_MARKS);
}

/** Uwagi kontroli AI, których linia nadal stoi w CV — poprawiona linia nie wraca na listę. */
export function findingsInCv(doc: PMNode, findings: readonly CvReviewFinding[]): CvReviewFinding[] {
  const outline = cvOutline(doc);
  return findings.filter((finding) => lineRange(doc, outline, finding.text) != null);
}

/**
 * Czy zdanie z propozycji AI już stoi w CV. Liczone z treści, nie z pamięci
 * panelu: po „Cofnij” propozycja wraca na listę sama.
 */
export function fixAlreadyInCv(doc: PMNode, fix: QcFix): boolean {
  return lineRange(doc, cvOutline(doc), fix.proposed_text.replace(/\*\*/g, "")) != null;
}

export const REVIEW_FINDING_LABEL: Record<string, string> = {
  unsupported: "bez pokrycia w źródłach",
  contradicted: "sprzeczne ze źródłem",
  private: "dane prywatne",
  invalid_evidence: "kontrola nie wskazała źródła",
};

// ── „Popraw wszystko” ────────────────────────────────────────────────────────

export interface BulkPlan {
  actions: QcFixAction[];
  /** Co zostanie zrobione — do zdania pod przyciskiem i do potwierdzenia. */
  parts: string[];
}

/**
 * Poprawki, które wolno nałożyć hurtem (decyzja Artura D2, 12.10.2026):
 * formalne (pogrubienie wymagań, pisownia technologii) i zdania AI
 * w brzmieniu z serwera, czyli z cytatem sprawdzonym w źródle. Usunięcie
 * terminu i zdanie AI po edycji zatwierdza się pojedynczo — serwer i tak
 * odrzuca je w trybie `bulk` (`cv_qc.BULK_ACTIONS`). Zdania AI idą pierwsze:
 * szukają swojej linii po tekście, który pisownia by zmieniła (serwer ustawia
 * tę kolejność także sam).
 */
export function bulkPlan(checks: readonly QcCheck[], fixes: readonly QcFix[]): BulkPlan {
  const actions: QcFixAction[] = fixes.map((fix) => ({ action: "ai_fix", fix_id: fix.id }));
  const parts: string[] = [];
  let spelling = 0;
  for (const check of checks) {
    if (check.status !== "fail") continue;
    const terms = check.items.filter((item) => item.fix === "bold_all").length;
    if (terms > 0) {
      const scope = check.key === "nice_bolded" ? "nice" : "must";
      if (!actions.some((action) => action.action === "bold_all" && action.scope === scope)) {
        actions.push({ action: "bold_all", scope });
        parts.push(
          `pogrubienie ${countForm(terms, ["wymagania", "wymagań", "wymagań"])} ${scope === "nice" ? "mile widzianych" : "must-have"}`,
        );
      }
    }
    spelling += check.items.filter((item) => item.fix === "spelling").length;
  }
  if (spelling > 0) {
    actions.push({ action: "spelling" });
    parts.push(`pisownia ${countForm(spelling, ["technologii", "technologii", "technologii"])}`);
  }
  if (fixes.length > 0) {
    parts.push(`${countForm(fixes.length, ["zdanie", "zdania", "zdań"])} AI z cytatem ze źródła`);
  }
  return { actions, parts };
}

// ── Nałożenie wyniku serwera ─────────────────────────────────────────────────

interface Change {
  /** Zakres w bieżącym dokumencie i to, co go zastępuje. */
  from: number;
  to: number;
  slice: Slice;
  /** Ten sam fragment w nowym dokumencie — do wyróżnienia po poprawce. */
  placed: IssueRange;
}

/** Zamiana różniącego się zakresu treści węzła (początek i koniec wspólne zostają). */
function contentChange(current: PMNode, next: PMNode, currentAt: number, nextAt: number): Change | null {
  const start = current.content.findDiffStart(next.content);
  if (start == null) return null;
  const end = current.content.findDiffEnd(next.content);
  if (!end) return null;
  let { a: endCurrent, b: endNext } = end;
  // Powtórzony fragment (np. dopisany taki sam punkt) daje koniec przed początkiem.
  const overlap = start - Math.min(endCurrent, endNext);
  if (overlap > 0) {
    endCurrent += overlap;
    endNext += overlap;
  }
  return {
    from: currentAt + start,
    to: currentAt + endCurrent,
    slice: next.slice(start, endNext),
    placed: { from: nextAt + start, to: nextAt + endNext, block: true },
  };
}

/**
 * Najmniejsze zamiany prowadzące od `current` do `next`. Węzły o tej samej
 * budowie porównuje dziecko po dziecku — pogrubienie w jednym punkcie i literówka
 * trzy sekcje wyżej to dwie małe zamiany, a nie jedna na pół dokumentu.
 * `currentAt` / `nextAt` to pozycje początku TREŚCI węzła.
 */
function collectChanges(current: PMNode, next: PMNode, currentAt: number, nextAt: number, out: Change[]): void {
  if (current.content.eq(next.content)) return;
  if (current.isTextblock || current.childCount !== next.childCount) {
    const change = contentChange(current, next, currentAt, nextAt);
    if (change) out.push(change);
    return;
  }
  let a = currentAt;
  let b = nextAt;
  for (let index = 0; index < current.childCount; index += 1) {
    const mine = current.child(index);
    const theirs = next.child(index);
    if (!mine.eq(theirs)) {
      if (!mine.isLeaf && !mine.isTextblock && mine.sameMarkup(theirs)) {
        collectChanges(mine, theirs, a + 1, b + 1, out);
      } else {
        out.push({
          from: a,
          to: a + mine.nodeSize,
          slice: new Slice(Fragment.from(theirs), 0, 0),
          placed: { from: b, to: b + theirs.nodeSize, block: true },
        });
      }
    }
    a += mine.nodeSize;
    b += theirs.nodeSize;
  }
}

export interface FixStep {
  transaction: Transaction;
  /** Zmienione miejsca w nowym dokumencie, w kolejności czytania. */
  changed: IssueRange[];
}

/**
 * Transakcja zamieniająca TYLKO to, czym nowa treść różni się od bieżącej;
 * `null`, gdy po wczytaniu do schematu edytora nic się nie zmienia. Wszystkie
 * zamiany są jednym krokiem historii, zaczętym od nowa: „Cofnij” zdejmuje samą
 * poprawkę, a nie poprawkę razem z tym, co rekruter wpisał chwilę wcześniej.
 */
export function fixStep(state: EditorState, html: string): FixStep | null {
  return docStep(state, createDocument(html, state.schema));
}

/**
 * Czy wtyczki przyjmą zmianę ORAZ jej cofnięcie.
 *
 * Wtyczka struktury odrzuca transakcję, która rozcina klauzulę zgody. Klauzula
 * bez znacznika (starsze CV) ma tę samą budowę co zwykły akapit, więc
 * najmniejsza zamiana sąsiedniego akapitu zaczynającego się tą samą literą
 * („W…” jak „Wyrażam…”) wchodziła w jej środek. Dopisany akapit wtyczka
 * odrzucała po cichu; usunięty wchodził, ale jego odwrotność już nie —
 * „Cofnij” nic nie robiło i blokowało cały stos cofania (przegląd 13.10.2026).
 * Historia cofa, odwracając kroki — sprawdzamy to samo.
 */
export function acceptedBothWays(state: EditorState, transaction: Transaction): boolean {
  // Odrzucona transakcja nie trafia na listę zastosowanych.
  const applied = state.applyTransaction(transaction);
  if (!applied.transactions.includes(transaction)) return false;
  try {
    const back = applied.state.tr;
    for (let index = transaction.steps.length - 1; index >= 0; index -= 1) {
      back.step(transaction.steps[index].invert(transaction.docs[index]));
    }
    return applied.state.applyTransaction(back).transactions.includes(back);
  } catch {
    // Wtyczka coś dopisała po zmianie i odwrotność już nie pasuje do dokumentu.
    return false;
  }
}

/** Całe bloki dokumentu, którymi nowa treść różni się od bieżącej (od początku i od końca). */
function blockChange(current: PMNode, next: PMNode): Change {
  const shared = Math.min(current.childCount, next.childCount);
  let head = 0;
  while (head < shared && current.child(head).eq(next.child(head))) head += 1;
  let tail = 0;
  while (
    tail < shared - head &&
    current.child(current.childCount - 1 - tail).eq(next.child(next.childCount - 1 - tail))
  ) {
    tail += 1;
  }
  const span = (doc: PMNode) => {
    let from = 0;
    for (let index = 0; index < head; index += 1) from += doc.child(index).nodeSize;
    let to = doc.content.size;
    for (let index = 0; index < tail; index += 1) to -= doc.child(doc.childCount - 1 - index).nodeSize;
    return { from, to };
  };
  const mine = span(current);
  const theirs = span(next);
  return { from: mine.from, to: mine.to, slice: next.slice(theirs.from, theirs.to), placed: { ...theirs, block: true } };
}

/**
 * To samo dla gotowego dokumentu — bez przejścia przez HTML (`lib/cv-editor-diff.ts`).
 *
 * Trzy próby, każda musi przejść w obie strony (`acceptedBothWays`): najmniejsze
 * zamiany, potem całe różniące się bloki, na końcu cała treść jednym krokiem.
 * `null` = nie ma czego zmieniać albo edytor nie przyjąłby żadnej z nich.
 */
export function docStep(state: EditorState, next: PMNode): FixStep | null {
  const changes: Change[] = [];
  collectChanges(state.doc, next, 0, 0, changes);
  if (changes.length === 0) return null;
  let transaction = state.tr;
  // Od końca: wcześniejsze pozycje zostają ważne.
  for (const change of [...changes].sort((first, second) => second.from - first.from)) {
    transaction.replace(change.from, change.to, change.slice);
  }
  let changed = changes.map((change) => change.placed).sort((first, second) => first.from - second.from);
  if (!transaction.doc.eq(next)) {
    // Zamiany po kawałku nie złożyły się w nową treść — jedna zamiana całego różniącego się zakresu.
    const whole = contentChange(state.doc, next, 0, 0);
    if (!whole) return null;
    transaction = state.tr.replace(whole.from, whole.to, whole.slice);
    changed = [whole.placed];
  }
  const minimal = closeHistory(transaction);
  if (acceptedBothWays(state, minimal)) return { transaction: minimal, changed };

  // Całe bloki: zamiana kończy się na granicy bloku, więc nie wchodzi w klauzulę.
  const blocks = blockChange(state.doc, next);
  const placed = blocks.placed.to > blocks.placed.from ? [blocks.placed] : [];
  const byBlocks = closeHistory(state.tr.replace(blocks.from, blocks.to, blocks.slice));
  if (byBlocks.doc.eq(next) && acceptedBothWays(state, byBlocks)) return { transaction: byBlocks, changed: placed };

  // Cała treść jednym krokiem: klauzula znika i wraca w całości, w obie strony.
  const everything = closeHistory(state.tr.replaceWith(0, state.doc.content.size, next.content));
  // Kursor na początek treści — domyślnie lądował w zablokowanej klauzuli na końcu.
  everything.setSelection(TextSelection.atStart(everything.doc));
  return acceptedBothWays(state, everything) ? { transaction: everything, changed: placed } : null;
}
