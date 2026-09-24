import { describe, expect, it } from "vitest";
import { MOBILE_CV_STYLE_MARKER, withMobileCvStyle } from "./cv-frame";

describe("withMobileCvStyle — publiczne CV czytelne na telefonie", () => {
  it("dokleja reguły wąskiego ekranu na końcu <head>, po arkuszu dokumentu", () => {
    const html =
      "<html><head><style>.cv-body{grid-template-columns:230px 1fr}</style></head><body></body></html>";
    const out = withMobileCvStyle(html);
    expect(out).toContain(MOBILE_CV_STYLE_MARKER);
    expect(out.indexOf(MOBILE_CV_STYLE_MARKER)).toBeGreaterThan(
      out.indexOf("230px 1fr"),
    );
    expect(out).toMatch(/\.cv-body\{grid-template-columns:1fr!important\}/);
    expect(out.endsWith("</head><body></body></html>")).toBe(true);
  });

  it("dokument bez <head> (HTML po sanitizacji) dostaje styl na początku", () => {
    const out = withMobileCvStyle('<article class="cv"><h1>Jan</h1></article>');
    expect(out.startsWith("<style")).toBe(true);
    expect(out).toContain('<article class="cv">');
  });

  it("nie dubluje reguł, gdy dokument je ma (nowy szablon z backendu)", () => {
    const html =
      "<html><head><style>@media (max-width: 640px) { .cv-body { grid-template-columns: 1fr; } }</style></head></html>";
    expect(withMobileCvStyle(html)).toBe(html);
    const once = withMobileCvStyle("<p>x</p>");
    expect(withMobileCvStyle(once)).toBe(once);
  });

  it("pusty dokument zostaje pusty", () => {
    expect(withMobileCvStyle("")).toBe("");
    expect(withMobileCvStyle(null)).toBe("");
  });
});
