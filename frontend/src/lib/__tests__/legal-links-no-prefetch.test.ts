import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// NEXUS-FE-A4: `/kariera/rodo` w NEXUSIE to 307 na domenę kariery. Prefetch
// next/link (fetch `?_rsc=`) szedł za przekierowaniem cross-origin i CSP
// `connect-src` go blokowała. Link do RODO musi być zwykłym `<a>`.
const FILES = [
  "src/components/candidate-terms/TermsPage.tsx",
  "src/components/competence-report/ReportConditionsPage.tsx",
];

describe("link do RODO na stronach /warunki i /raport", () => {
  it.each(FILES)("%s używa zwykłego <a>, nie next/link", (file) => {
    const src = readFileSync(resolve(process.cwd(), file), "utf8");
    expect(src).toContain('<a href="/kariera/rodo" target="_blank"');
    expect(src).not.toMatch(/<Link[^>]*href="\/kariera\//);
  });
});
