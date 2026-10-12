/**
 * Pomiary `<textarea>` na ukrytej kopii (MentionTextarea, 12.10.2026).
 *
 * Przeglądarka nie podaje ani wysokości treści bez zwinięcia pola, ani pozycji
 * kursora. Zwinięcie prawdziwego pola na czas pomiaru (`height: auto`) skraca
 * stronę i potrafi przestawić przewinięcie, gdy ktoś pisze na samym dole —
 * dlatego mierzymy kopię poza ekranem, z tym samym krojem, szerokością
 * i zawijaniem. W jsdom układu nie ma: obie funkcje zwracają tam 0.
 */

const TEXT_STYLE = [
  "fontFamily",
  "fontSize",
  "fontStyle",
  "fontWeight",
  "letterSpacing",
  "lineHeight",
  "paddingTop",
  "paddingRight",
  "paddingBottom",
  "paddingLeft",
  "tabSize",
  "textTransform",
  "wordSpacing",
] as const;

const px = (value: string): number => parseFloat(value) || 0;

function offscreen<T extends HTMLElement>(
  node: T,
  field: HTMLTextAreaElement,
  fallbackWidth = 0,
): T {
  const style = getComputedStyle(field);
  for (const prop of TEXT_STYLE) node.style[prop] = style[prop];
  const paddingX = px(style.paddingLeft) + px(style.paddingRight);
  // Pole w ukrytym panelu (`display: none`) ma szerokość 0 — bierzemy wtedy
  // ostatnią zmierzoną szerokość z ramką, inaczej każdy znak szedłby do nowej
  // linii i pole wracałoby na ekran z wysokością sufitu.
  const innerWidth =
    field.clientWidth ||
    Math.max(fallbackWidth - px(style.borderLeftWidth) - px(style.borderRightWidth), 0);
  Object.assign(node.style, {
    position: "absolute",
    top: "0",
    left: "-9999px",
    visibility: "hidden",
    boxSizing: "content-box",
    // `clientWidth` nie liczy paska przewijania pola, więc kopia zawija tekst
    // w tym samym miejscu także wtedy, gdy pole już się przewija.
    width: `${Math.max(innerWidth - paddingX, 0)}px`,
    height: "auto",
    border: "0",
    overflow: "hidden",
    whiteSpace: "pre-wrap",
    overflowWrap: "break-word",
  });
  // Kopia nie może być polem ani etykietą dla czytnika ekranu.
  node.setAttribute("aria-hidden", "true");
  return node;
}

/**
 * Wysokość treści z paddingiem, bez ramki — co najmniej tyle, ile daje `rows`.
 * `fallbackWidth` to ostatnia znana szerokość pola z ramką, używana, gdy pole
 * jest właśnie ukryte.
 */
export function contentScrollHeight(field: HTMLTextAreaElement, fallbackWidth = 0): number {
  const copy = offscreen(document.createElement("textarea"), field, fallbackWidth);
  copy.tabIndex = -1;
  copy.rows = field.rows;
  copy.style.resize = "none";
  copy.value = field.value;
  document.body.append(copy);
  const height = copy.scrollHeight;
  copy.remove();
  return height;
}

/**
 * Odległość linii ze znakiem `index` od górnej krawędzi pola (px), po
 * uwzględnieniu przewinięcia treści w polu.
 */
export function caretOffsetTop(field: HTMLTextAreaElement, index: number): number {
  const copy = offscreen(document.createElement("div"), field);
  copy.textContent = field.value.slice(0, index);
  const marker = document.createElement("span");
  marker.textContent = "​";
  copy.append(marker);
  document.body.append(copy);
  const top = marker.offsetTop;
  copy.remove();
  return top + field.clientTop - field.scrollTop;
}
