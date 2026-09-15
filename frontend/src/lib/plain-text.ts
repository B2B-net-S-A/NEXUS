const ENTITIES: Record<string, string> = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
  // Polskie znaki — Fireflies/Traffit zapisują je jako encje nazwane
  // („dw&oacute;jce”, „og&oacute;le”; UAT B09), więc sama ich lista z HTML 4
  // nie wystarcza: brakuje ogonków, których HTML 4 nie nazywa.
  oacute: "ó",
  Oacute: "Ó",
  aogon: "ą",
  Aogon: "Ą",
  eogon: "ę",
  Eogon: "Ę",
  cacute: "ć",
  Cacute: "Ć",
  lstrok: "ł",
  Lstrok: "Ł",
  nacute: "ń",
  Nacute: "Ń",
  sacute: "ś",
  Sacute: "Ś",
  zacute: "ź",
  Zacute: "Ź",
  zdot: "ż",
  Zdot: "Ż",
  // Pozostałe łacińskie z transkrypcji anglo-/niemieckojęzycznych.
  aacute: "á",
  eacute: "é",
  iacute: "í",
  uacute: "ú",
  agrave: "à",
  egrave: "è",
  auml: "ä",
  ouml: "ö",
  uuml: "ü",
  Auml: "Ä",
  Ouml: "Ö",
  Uuml: "Ü",
  szlig: "ß",
  ccedil: "ç",
  ntilde: "ñ",
  // Typografia.
  ndash: "–",
  mdash: "—",
  hellip: "…",
  laquo: "«",
  raquo: "»",
  bdquo: "„",
  ldquo: "“",
  rdquo: "”",
  lsquo: "‘",
  rsquo: "’",
  copy: "©",
  reg: "®",
  trade: "™",
  euro: "€",
  deg: "°",
  middot: "·",
  bull: "•",
};

/**
 * Rozwiń encję HTML: numeryczną (`&#243;`, `&#xF3;`) albo nazwaną z tabeli.
 * Nieznana nazwa zostaje dosłownie — lepiej pokazać `&foo;` niż zgadywać.
 */
function decodeEntity(entity: string, body: string): string {
  if (body[0] === "#") {
    const isHex = body[1] === "x" || body[1] === "X";
    const code = Number.parseInt(body.slice(isHex ? 2 : 1), isHex ? 16 : 10);
    if (Number.isFinite(code) && code > 0 && code <= 0x10ffff) {
      try {
        return String.fromCodePoint(code);
      } catch {
        return entity;
      }
    }
    return entity;
  }
  return ENTITIES[body] ?? entity;
}

/** Same encje, bez znaczników — dla tekstu, który już nie jest HTML-em. */
export function decodeHtmlEntities(value: string | null | undefined): string {
  if (!value) return "";
  return value.replace(/&(#[xX]?[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);/g, decodeEntity);
}

/**
 * Tekst z pola, które bywa zapisane jako HTML (np. tytuł transkrypcji
 * Fireflies „<p>Rozmowa…</p>”) — bez znaczników, z rozwiniętymi encjami
 * (nazwanymi i numerycznymi) i zwiniętymi odstępami. Wynik renderujemy jako
 * tekst, nie HTML.
 */
export function stripHtmlTags(value: string | null | undefined): string {
  if (!value) return "";
  return decodeHtmlEntities(value.replace(/<[^>]*>/g, " "))
    .replace(/\s+/g, " ")
    .trim();
}

/** Czy pole tekstowe jest w rzeczywistości znacznikami HTML (np. treść maila z Outlooka). */
export function looksLikeHtml(value: string | null | undefined): boolean {
  if (!value) return false;
  return /<(?:!doctype|html|head|body|meta|style|div|p|br|span|table|font|a)\b[^>]*>|<\/[a-z][a-z0-9]*\s*>/i.test(
    value,
  );
}

/**
 * Wieloliniowy tekst z pola, które bywa pełnym dokumentem HTML — opis
 * wydarzenia zsynchronizowanego z M365 niesie całą treść maila
 * (`<html><head><meta…><style>…`). W odróżnieniu od `stripHtmlTags` zachowuje
 * podział na akapity: `<br>` i koniec bloku to nowa linia, a `<head>`,
 * `<style>`, `<script>` i komentarze znikają RAZEM Z TREŚCIĄ (inaczej CSS
 * z Outlooka wychodziłby jako tekst). Zwykły tekst (bez znaczników) wraca bez
 * zmian. Wynik renderujemy jako tekst z `whitespace-pre-line`, nigdy jako HTML.
 */
export function htmlToPlainText(value: string | null | undefined): string {
  if (!value) return "";
  if (!looksLikeHtml(value)) return value.trim();
  const text = value
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/<(head|style|script|title)\b[\s\S]*?<\/\1\s*>/gi, "")
    // Białe znaki w źródle HTML nie znaczą nic — strukturę dają znaczniki.
    .replace(/\s+/g, " ")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(?:p|div|li|tr|h[1-6]|table|blockquote|pre)\s*>/gi, "\n")
    .replace(/<[^>]*>/g, "");
  return decodeHtmlEntities(text)
    .split("\n")
    .map((line) => line.replace(/[ \t\u00a0]+/g, " ").trim())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
