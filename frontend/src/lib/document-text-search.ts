/**
 * Wyszukiwanie tekstu w podglądzie dokumentu renderowanym jako zwykły HTML
 * (DOCX przez `docx-preview`). PDF ma własny silnik (`PDFFindController`
 * z pdf.js) — tu jest wyłącznie ścieżka DOM.
 *
 * Reguły dopasowania są te same co w pdf.js dla PDF-a, żeby lupa zachowywała
 * się identycznie niezależnie od formatu CV: bez wielkości liter i bez
 * polskich znaków („poznan” trafia „Poznań”, „LODZ” trafia „Łódź”).
 */

/** Krótsze zapytanie to setki trafień na pojedynczą literę — nie szukamy. */
export const MIN_DOCUMENT_QUERY_LENGTH = 2;

const HIT_ATTR = "data-doc-search-hit";
const ACTIVE_ATTR = "data-active";

/**
 * Składa znak do postaci porównywalnej — ZAWSZE dokładnie jeden znak na
 * wejściu daje jeden znak na wyjściu. Na tej równości stoi przeliczanie
 * pozycji trafienia z powrotem na węzły tekstu.
 */
function foldChar(ch: string): string {
  const lower = ch.toLowerCase();
  if (lower === "ł") return "l";
  const stripped = lower.normalize("NFD").replace(/\p{M}+/gu, "");
  return stripped.length === 1 ? stripped : lower.length === 1 ? lower : ch;
}

export function foldForSearch(text: string): string {
  let out = "";
  for (const ch of text) out += foldChar(ch);
  return out;
}

export function normalizeDocumentQuery(query: string): string {
  return foldForSearch(query.trim().replace(/\s+/g, " "));
}

export function isSearchableQuery(query: string): boolean {
  return query.trim().length >= MIN_DOCUMENT_QUERY_LENGTH;
}

/** Wszystkie pozycje (w jednostkach kodowych UTF-16) trafień bez nakładania. */
export function findMatchOffsets(
  text: string,
  query: string,
): Array<[number, number]> {
  const needle = normalizeDocumentQuery(query);
  if (needle.length < MIN_DOCUMENT_QUERY_LENGTH) return [];
  // Składamy znak po znaku po jednostkach kodowych, żeby indeksy zgadzały się
  // z `Text.data` (surogaty zostają nietknięte — `foldChar` ich nie zmienia).
  let haystack = "";
  for (let i = 0; i < text.length; i++) haystack += foldChar(text[i]);
  // Wielokrotne białe znaki w dokumencie zwijamy w zapytaniu, więc w tekście
  // też muszą pasować do pojedynczej spacji.
  const pattern = new RegExp(
    needle
      .split(" ")
      .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("\\s+"),
    "g",
  );
  const offsets: Array<[number, number]> = [];
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(haystack)) !== null) {
    if (match[0].length === 0) {
      pattern.lastIndex += 1;
      continue;
    }
    offsets.push([match.index, match.index + match[0].length]);
  }
  return offsets;
}

const BLOCK_TAGS = new Set([
  "P",
  "LI",
  "TD",
  "TH",
  "H1",
  "H2",
  "H3",
  "H4",
  "H5",
  "H6",
  "DIV",
  "SECTION",
  "ARTICLE",
  "HEADER",
  "FOOTER",
  "TABLE",
  "TR",
]);

// `docx-preview` wstawia do hosta własny `<style>` — jego treść to CSS, nie CV.
const NON_CONTENT_TAGS = new Set(["STYLE", "SCRIPT", "NOSCRIPT", "TEMPLATE"]);

function visibleTextNodes(root: Element): Text[] {
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => {
      if (!node.nodeValue) return NodeFilter.FILTER_REJECT;
      for (let el = node.parentElement; el && el !== root; el = el.parentElement) {
        if (NON_CONTENT_TAGS.has(el.tagName)) return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes: Text[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    nodes.push(node as Text);
  }
  return nodes;
}

function blockAncestor(node: Node, root: Element): Node {
  let current = node.parentNode;
  while (current && current !== root) {
    if (current instanceof Element && BLOCK_TAGS.has(current.tagName)) {
      return current;
    }
    current = current.parentNode;
  }
  return root;
}

/** Zdejmuje poprzednie podświetlenia i skleja rozcięte węzły tekstu. */
export function clearDocumentHighlights(root: Element): void {
  const marks = root.querySelectorAll(`mark[${HIT_ATTR}]`);
  if (marks.length === 0) return;
  const parents = new Set<Node>();
  marks.forEach((mark) => {
    const parent = mark.parentNode;
    if (!parent) return;
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
    parent.removeChild(mark);
    parents.add(parent);
  });
  parents.forEach((parent) => parent.normalize());
}

/**
 * Podświetla trafienia w drzewie `root`. Trafienie może przechodzić przez
 * kilka węzłów tekstu tego samego akapitu (Word dzieli tekst na „runy”, więc
 * „Comarch” bywa dwoma spanami), ale nigdy przez granicę akapitu — inaczej
 * koniec jednej linii i początek następnej dawałyby fałszywe trafienia.
 *
 * Zwraca liczbę trafień. Każde trafienie to jeden lub kilka `<mark>` z tym
 * samym `data-doc-search-hit="<numer>"`.
 */
export function highlightDocumentMatches(root: Element, query: string): number {
  clearDocumentHighlights(root);
  if (!isSearchableQuery(query)) return 0;

  const doc = root.ownerDocument;
  const groups: Array<{ nodes: Text[] }> = [];
  let currentBlock: Node | null = null;
  for (const node of visibleTextNodes(root)) {
    const block = blockAncestor(node, root);
    if (block !== currentBlock || groups.length === 0) {
      groups.push({ nodes: [] });
      currentBlock = block;
    }
    groups[groups.length - 1].nodes.push(node);
  }

  type Segment = { node: Text; start: number; end: number; hit: number };
  const segments: Segment[] = [];
  let hitIndex = 0;

  for (const group of groups) {
    const starts: number[] = [];
    let text = "";
    for (const node of group.nodes) {
      starts.push(text.length);
      text += node.data;
    }
    for (const [matchStart, matchEnd] of findMatchOffsets(text, query)) {
      group.nodes.forEach((node, i) => {
        const nodeStart = starts[i];
        const nodeEnd = nodeStart + node.data.length;
        const start = Math.max(matchStart, nodeStart);
        const end = Math.min(matchEnd, nodeEnd);
        if (start < end) {
          segments.push({
            node,
            start: start - nodeStart,
            end: end - nodeStart,
            hit: hitIndex,
          });
        }
      });
      hitIndex += 1;
    }
  }

  // Od końca: rozcięcie węzła w późniejszym miejscu nie przesuwa wcześniejszych
  // pozycji w tym samym węźle.
  for (let i = segments.length - 1; i >= 0; i--) {
    const { node, start, end, hit } = segments[i];
    const range = doc.createRange();
    range.setStart(node, start);
    range.setEnd(node, end);
    const mark = doc.createElement("mark");
    mark.setAttribute(HIT_ATTR, String(hit));
    range.surroundContents(mark);
  }

  return hitIndex;
}

/** Wyróżnia trafienie `index` (0-based) i przewija do niego. */
export function activateDocumentMatch(root: Element, index: number): void {
  root
    .querySelectorAll(`mark[${HIT_ATTR}][${ACTIVE_ATTR}]`)
    .forEach((mark) => mark.removeAttribute(ACTIVE_ATTR));
  const marks = root.querySelectorAll(`mark[${HIT_ATTR}="${index}"]`);
  marks.forEach((mark) => mark.setAttribute(ACTIVE_ATTR, ""));
  const first = marks[0] as HTMLElement | undefined;
  first?.scrollIntoView?.({ block: "center", inline: "nearest" });
}

/** Czy wyrenderowany dokument ma jakikolwiek tekst (skan = sam obraz). */
export function hasSearchableText(root: Element): boolean {
  return visibleTextNodes(root).some((node) => node.data.trim().length > 0);
}
