/**
 * Bezpieczny podgląd DOCX (audyt 22.09 r2, SEC-01).
 *
 * `docx-preview` renderuje dokument jako zwykły HTML w drzewie strony. Dwie
 * jego domyślne cechy dawały kradzież tokenu z `localStorage`:
 *
 * - `renderAltChunks: true` — osadzony w DOCX fragment HTML („altChunk”)
 *   ląduje w `<iframe srcdoc>` BEZ `sandbox`, czyli z tym samym originem co
 *   NEXUS. Skrypt z CV wgranego anonimowo przez stronę kariery wykonywał się
 *   w sesji rekrutera, który otworzył podgląd.
 * - hiperłącza z dokumentu trafiają do `<a href>` bez sprawdzenia schematu,
 *   więc `javascript:` wykonuje się po kliknięciu.
 *
 * Dlatego: jedno miejsce woła `renderAsync` (pilnuje tego test czytający
 * źródła), wymusza bezpieczne opcje PO opcjach wołającego (nie da się ich
 * nadpisać) i po renderze czyści drzewo z elementów aktywnych, atrybutów
 * zdarzeń i linków o niedozwolonym schemacie.
 */

import type { Options } from "docx-preview";

/** Opcje, których wołający nie może nadpisać. */
export const SAFE_DOCX_OPTIONS = {
  renderAltChunks: false,
  renderComments: false,
  renderChanges: false,
} as const satisfies Partial<Options>;

const ACTIVE_ELEMENTS =
  "iframe,frame,frameset,object,embed,script,applet,base,meta,link,form,portal";

const LINK_ATTRIBUTES = new Set([
  "href",
  "xlink:href",
  "src",
  "action",
  "formaction",
  "srcdoc",
  "data",
]);

const SAFE_LINK_PROTOCOLS = new Set(["http:", "https:", "mailto:", "tel:"]);

/** Czy wartość linku z dokumentu wolno zostawić w `href`. */
export function isSafeDocxHref(raw: string | null | undefined): boolean {
  if (raw == null) return false;
  const value = raw.trim();
  if (!value) return false;
  // Kotwica wewnątrz dokumentu (zakładki Worda) — zostaje.
  if (value.startsWith("#")) return true;
  // Białe i sterujące znaki w środku to klasyczny sposób ukrycia
  // `java\tscript:` przed prostym porównaniem schematu.
  if (/[\u0000-\u001f\u007f\s\\]/.test(value)) return false;
  try {
    // Bez bazy: adres względny rzuca i jest odrzucany.
    const url = new URL(value);
    return SAFE_LINK_PROTOCOLS.has(url.protocol);
  } catch {
    return false;
  }
}

/** Usuwa z wyrenderowanego drzewa wszystko, co mogłoby wykonać kod. */
export function hardenDocxDom(host: HTMLElement): void {
  host.querySelectorAll(ACTIVE_ELEMENTS).forEach((node) => node.remove());

  host.querySelectorAll("*").forEach((element) => {
    const tag = element.tagName.toLowerCase();
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on")) {
        element.removeAttribute(attribute.name);
        continue;
      }
      if (!LINK_ATTRIBUTES.has(name)) continue;
      // Obrazy docx-preview osadza jako `data:`/`blob:` (useBase64URL) —
      // taki `src` obrazka nie wykonuje kodu, więc zostaje.
      if (name === "src" && tag === "img") {
        const value = attribute.value.trim().toLowerCase();
        if (value.startsWith("data:image/") || value.startsWith("blob:")) continue;
        element.removeAttribute(attribute.name);
        continue;
      }
      // Rysunki VML/SVG: `<image href="data:image/...">` też tylko obraz.
      if (tag === "image" && (name === "href" || name === "xlink:href")) {
        const value = attribute.value.trim().toLowerCase();
        if (value.startsWith("data:image/") || value.startsWith("blob:")) continue;
      }
      if ((name === "href" || name === "xlink:href") && isSafeDocxHref(attribute.value)) {
        continue;
      }
      element.removeAttribute(attribute.name);
    }
    if (tag === "a" && element.hasAttribute("href")) {
      const href = element.getAttribute("href") ?? "";
      if (!href.trim().startsWith("#")) {
        element.setAttribute("target", "_blank");
        element.setAttribute("rel", "noopener noreferrer nofollow");
      }
    }
  });
}

/**
 * JEDYNE miejsce w aplikacji, które woła `renderAsync` z `docx-preview`.
 * Leniwy import, żeby parser nie trafiał do głównego bundla.
 */
export async function renderDocxSafely(
  data: Blob,
  host: HTMLElement,
  options: Partial<Options> = {},
): Promise<void> {
  const { renderAsync } = await import("docx-preview");
  await renderAsync(data, host, undefined, { ...options, ...SAFE_DOCX_OPTIONS });
  hardenDocxDom(host);
}
