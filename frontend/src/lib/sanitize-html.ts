import DOMPurify from "dompurify";

// Deliberately closed rich-text surface.  Adding a tag or attribute requires a
// security review and an XSS regression case; DOMPurify's much broader default
// HTML profile is not used for persisted backend content.
export const RICH_TEXT_ALLOWED_TAGS = [
  "a",
  "abbr",
  "aside",
  "b",
  "blockquote",
  "br",
  "code",
  "div",
  "em",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "i",
  "img",
  "li",
  "main",
  "ol",
  "p",
  "pre",
  "section",
  "span",
  "strong",
  "sub",
  "sup",
  "table",
  "tbody",
  "td",
  "tfoot",
  "th",
  "thead",
  "tr",
  "u",
  "ul",
] as const;

export const RICH_TEXT_ALLOWED_ATTRS = [
  "alt",
  "class",
  "colspan",
  "height",
  "href",
  "rel",
  "rowspan",
  "src",
  "title",
  "width",
] as const;

const SAFE_URI = /^(?:(?:https?|mailto|cid):|[\/#])/i;

export function sanitizeRichHtml(raw: string): string {
  if (!raw) return "";
  return DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: [...RICH_TEXT_ALLOWED_TAGS],
    ALLOWED_ATTR: [...RICH_TEXT_ALLOWED_ATTRS],
    ALLOWED_URI_REGEXP: SAFE_URI,
    ALLOW_ARIA_ATTR: false,
    ALLOW_DATA_ATTR: false,
    ALLOW_UNKNOWN_PROTOCOLS: false,
    FORBID_ATTR: ["formaction", "srcdoc", "style"],
    FORBID_TAGS: ["form", "iframe", "math", "object", "script", "style", "svg"],
  });
}
