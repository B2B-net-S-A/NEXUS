import { describe, expect, it } from "vitest";

import { sanitizeRichHtml } from "@/lib/sanitize-html";

const XSS_PAYLOADS = [
  '<script>window.__xss = true</script><p>safe</p>',
  '<img src="x" onerror="window.__xss = true">',
  '<svg><a xlink:href="javascript:alert(1)">svg</a></svg>',
  '<math><mtext><img src=x onerror=alert(1)></mtext></math>',
  '<a href="javascript:alert(1)" style="background:url(javascript:alert(2))">link</a>',
  '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
  '<img src="data:text/html,<script>alert(1)</script>">',
];

describe("sanitizeRichHtml", () => {
  it.each(XSS_PAYLOADS)("neutralizes persisted XSS payload %#", (payload) => {
    const output = sanitizeRichHtml(payload).toLowerCase();

    expect(output).not.toContain("<script");
    expect(output).not.toContain("javascript:");
    expect(output).not.toContain("onerror");
    expect(output).not.toContain("srcdoc");
    expect(output).not.toContain("data:text/html");
    expect(output).not.toContain("<svg");
    expect(output).not.toContain("<math");
  });

  it("keeps the reviewed formatting and URL surface", () => {
    const output = sanitizeRichHtml(
      '<p class="lead"><strong>Hello</strong> <a href="https://example.com" target="_blank" rel="noopener">world</a></p>',
    );

    expect(output).toContain('<p class="lead">');
    expect(output).toContain("<strong>Hello</strong>");
    expect(output).toContain('href="https://example.com"');
    expect(output).not.toContain('target="_blank"');
    expect(output).not.toContain("javascript:");
  });
});
