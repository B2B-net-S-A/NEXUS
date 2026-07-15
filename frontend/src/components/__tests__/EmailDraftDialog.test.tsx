import { describe, expect, it } from "vitest";

import { sanitizeEmailDraftHtml } from "@/components/sourcing/EmailDraftDialog";

describe("sanitizeEmailDraftHtml", () => {
  it("keeps draft formatting while removing executable HTML", () => {
    const sanitized = sanitizeEmailDraftHtml(`
      <p style="background:url(https://attacker.test)">
        Witaj <strong>Anna</strong>
        <img src=x onerror="alert(document.cookie)">
        <script>alert(1)</script>
        <a href="javascript:alert(2)" onclick="alert(3)" target="_blank">link</a>
      </p>
    `);

    expect(sanitized).toContain("<p>");
    expect(sanitized).toContain("<strong>Anna</strong>");
    expect(sanitized).toContain("<a>link</a>");
    expect(sanitized).not.toMatch(/script|onerror|onclick|javascript:|style=|<img/i);
  });

  it("allows ordinary https links but strips unrelated attributes", () => {
    const sanitized = sanitizeEmailDraftHtml(
      '<a href="https://example.com/oferta" title="Oferta" data-id="7">Oferta</a>',
    );

    expect(sanitized).toBe(
      '<a href="https://example.com/oferta" title="Oferta">Oferta</a>',
    );
  });
});
