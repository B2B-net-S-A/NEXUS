/**
 * Historia wersji i powrót pliku Word w edytorze CV (Edytor CV 2, PR 5) — czysta logika.
 *
 * Przywrócenie zatwierdzonej wersji i przyjęcie treści z pliku Word to ta sama
 * operacja: treść PRZYCHODZĄCA (HTML z serwera) zastępuje treść edytora jedną
 * cofalną zmianą, a przedtem rekruter widzi listę różnic wiersz po wierszu.
 *
 * - `htmlToDoc` — przychodzący HTML jako dokument schematu edytora,
 * - `contentLines` + `diffLines` — czym bieżąca treść różni się od przychodzącej,
 * - `replaceContentStep` — JEDNA transakcja i jeden krok historii.
 *
 * Klauzula zgody jest stała (decyzja D3): po zmianie na końcu stoi dokładnie
 * ta, która jest w edytorze — bez względu na to, co przyniosła treść
 * przychodząca (inną, żadną, w środku tekstu).
 *
 * Moduł nie importuje `@tiptap/react`.
 */

import { createDocument } from "@tiptap/core";
import { closeHistory } from "@tiptap/pm/history";
import { Fragment, type Node as PMNode, type Schema } from "@tiptap/pm/model";
import type { EditorState, Transaction } from "@tiptap/pm/state";

import { cvOutline, isRodoNode } from "@/lib/cv-editor-blocks";
import { docStep } from "@/lib/cv-editor-issues";

/**
 * Przychodzący HTML w schemacie edytora. Nie musi mieć kształtu edytora: plik
 * Word przychodzi w opakowaniu (`article`), z punktami bez akapitu i klauzulą
 * jako `p.rodo` — parser ProseMirrora pomija nieznane znaczniki, a tekst
 * punktu owija akapitem.
 */
export function htmlToDoc(schema: Schema, html: string): PMNode {
  return createDocument(html, schema);
}

// ── Wiersze do porównania ────────────────────────────────────────────────────

export interface CvDiffLine {
  /** Tekst bloku: pogrubienie jako `**x**`, odstępy znormalizowane. */
  text: string;
  /** Stanowisko albo sekcja, w której stoi wiersz. */
  place: string | null;
}

/** Tekst bloku z pogrubieniem jako `**x**`; twarde złamanie wiersza to odstęp. */
function markup(block: PMNode): string {
  let out = "";
  let bold = false;
  block.forEach((child) => {
    const next = child.isText && child.marks.some((mark) => mark.type.name === "bold");
    if (next !== bold) out += "**";
    bold = next;
    out += child.isText ? (child.text ?? "") : " ";
  });
  return (bold ? `${out}**` : out).replace(/\s+/g, " ").trim();
}

/**
 * Wiersze treści CV w kolejności dokumentu: każdy blok tekstu, także punkt
 * zagnieżdżonej listy. Klauzula zgody nie jest wierszem (zostaje z bieżącej
 * treści), pusty akapit i linia pozioma też nie.
 */
export function contentLines(doc: PMNode): CvDiffLine[] {
  const outline = cvOutline(doc);
  const lines: CvDiffLine[] = [];
  let heading: string | null = null;
  for (const block of outline.blocks) {
    if (isRodoNode(block.node)) continue;
    // Tytuł CV i nagłówek sekcji same są miejscem — nie stoją „w” niczym.
    const level = block.node.type.name === "heading" ? Number(block.node.attrs.level) : 0;
    if (level === 1 || level === 2) heading = null;
    const role = outline.roles.find((item) => block.index > item.fromIndex && block.index < item.toIndex);
    const place = role?.title ?? heading;
    const push = (node: PMNode) => {
      const text = markup(node);
      if (text) lines.push({ text, place });
    };
    if (block.node.isTextblock) push(block.node);
    else
      block.node.descendants((node) => {
        if (!node.isTextblock) return true;
        push(node);
        return false;
      });
    if (level === 2) heading = block.node.textContent.replace(/\s+/g, " ").trim() || null;
  }
  return lines;
}

// ── Różnice ──────────────────────────────────────────────────────────────────

export type CvDiffKind = "changed" | "added" | "removed";

export interface CvDiffItem {
  kind: CvDiffKind;
  /** Wiersz bieżącej treści — po zmianie zniknie (`removed`) albo zostanie zastąpiony (`changed`). */
  before?: string;
  /** Wiersz treści przychodzącej — po zmianie dojdzie (`added`) albo zastąpi poprzedni (`changed`). */
  after?: string;
  place: string | null;
}

/** Powyżej tylu wierszy po którejś stronie nie porównujemy (koszt tabeli rośnie z iloczynem). */
export const CV_DIFF_LINES_MAX = 600;

/**
 * Różnice między wierszami bieżącej treści (`before`) a przychodzącej (`after`)
 * — najdłuższy wspólny podciąg, porównanie po całym tekście wiersza (zmiana
 * pogrubienia to też różnica). Wiersze usunięte i dodane obok siebie łączą się
 * po kolei w „zmienione”; nadwyżka zostaje usunięta albo dodana.
 *
 * `null` = za dużo wierszy, żeby porównać.
 */
export function diffLines(before: readonly CvDiffLine[], after: readonly CvDiffLine[]): CvDiffItem[] | null {
  if (before.length > CV_DIFF_LINES_MAX || after.length > CV_DIFF_LINES_MAX) return null;
  // Wspólny początek i koniec nie wchodzą do tabeli — zwykle zostaje kilka wierszy.
  let head = 0;
  const shorter = Math.min(before.length, after.length);
  while (head < shorter && before[head].text === after[head].text) head += 1;
  let tail = 0;
  while (tail < shorter - head && before[before.length - 1 - tail].text === after[after.length - 1 - tail].text) tail += 1;
  const a = before.slice(head, before.length - tail);
  const b = after.slice(head, after.length - tail);

  // common[i][j] = długość najdłuższego wspólnego podciągu a[i..] i b[j..].
  const width = b.length + 1;
  const common = new Uint16Array((a.length + 1) * width);
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      common[i * width + j] =
        a[i].text === b[j].text
          ? common[(i + 1) * width + j + 1] + 1
          : Math.max(common[(i + 1) * width + j], common[i * width + j + 1]);
    }
  }

  const items: CvDiffItem[] = [];
  let removed: CvDiffLine[] = [];
  let added: CvDiffLine[] = [];
  const flush = () => {
    const pairs = Math.min(removed.length, added.length);
    for (let k = 0; k < pairs; k += 1) {
      items.push({ kind: "changed", before: removed[k].text, after: added[k].text, place: added[k].place });
    }
    for (const line of removed.slice(pairs)) items.push({ kind: "removed", before: line.text, place: line.place });
    for (const line of added.slice(pairs)) items.push({ kind: "added", after: line.text, place: line.place });
    removed = [];
    added = [];
  };
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i].text === b[j].text) {
      flush();
      i += 1;
      j += 1;
    } else if (j >= b.length || (i < a.length && common[(i + 1) * width + j] >= common[i * width + j + 1])) {
      removed.push(a[i]);
      i += 1;
    } else {
      added.push(b[j]);
      j += 1;
    }
  }
  flush();
  return items;
}

// ── Zastąpienie treści ───────────────────────────────────────────────────────

/**
 * Treść przychodząca z klauzulą zgody BIEŻĄCEGO dokumentu na końcu. Akapity
 * udające klauzulę w treści przychodzącej (inna, przeniesiona w środek) znikają;
 * CV bez klauzuli zostaje bez niej.
 */
function withCurrentClause(current: PMNode, incoming: PMNode): PMNode {
  const clause = cvOutline(current).rodo?.node ?? null;
  const blocks: PMNode[] = [];
  incoming.forEach((node) => {
    if (!isRodoNode(node)) blocks.push(node);
  });
  if (clause) blocks.push(clause);
  // Sama klauzula w pliku i CV bez klauzuli: dokument nie może zostać pusty.
  if (blocks.length === 0) return current.type.createAndFill() ?? incoming;
  return current.copy(Fragment.fromArray(blocks));
}

/**
 * Jedna transakcja (i jeden krok „Cofnij”), po której dokument to treść
 * przychodząca z bieżącą klauzulą zgody na końcu; `null`, gdy nic by się nie
 * zmieniło.
 *
 * Wtyczka struktury odrzuca zmianę, po której kawałek klauzuli zostałby poza
 * nią (`clauseLeaks`), i „naprawia” dokument z inną klauzulą. Dokument docelowy
 * kończy się TYM SAMYM węzłem klauzuli co bieżący, więc zamiany tylko
 * różniących się bloków (`docStep`) zwykle kończą się przed nią. Wyjątek:
 * klauzula bez znacznika (starsze CV) ma budowę zwykłego akapitu i akapit
 * dopisany tuż przed nią, zaczynający się tą samą literą, przesuwa początek
 * zamiany w jej środek. Dlatego zamiany są sprawdzane na stanie edytora; gdy
 * wtyczka by je odrzuciła, treść jest zamieniana cała naraz — klauzula znika
 * wtedy i wraca w jednym kroku, czego wtyczka nie uznaje za przeciek.
 */
export function replaceContentStep(state: EditorState, incoming: PMNode | string): Transaction | null {
  const doc = typeof incoming === "string" ? htmlToDoc(state.schema, incoming) : incoming;
  const next = withCurrentClause(state.doc, doc);
  const step = docStep(state, next);
  if (!step) return null;
  const minimal = step.transaction;
  // Odrzucona transakcja nie trafia na listę zastosowanych.
  if (minimal.doc.eq(next) && state.applyTransaction(minimal).transactions.includes(minimal)) return minimal;
  return closeHistory(state.tr.replaceWith(0, state.doc.content.size, next.content));
}
