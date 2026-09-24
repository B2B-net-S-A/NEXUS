/**
 * `/preview/b2b-documents` ma robić ZERO zapytań: każdy klucz, o który pytają
 * zamontowane komponenty, jest zasiany TĄ SAMĄ funkcją kluczy
 * (`b2bDocumentsKeys`), a interceptor odcina resztę. Klucze mają parametry,
 * więc strażnik literałów z `harness-seeds.test.ts` ich nie widzi — stąd
 * sprawdzenie po nazwach funkcji.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");
const read = (p: string) =>
  readFileSync(join(SRC, p), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/\/\/[^\n]*/g, " ");

describe("/preview/b2b-documents", () => {
  const harness = read("app/preview/b2b-documents/page.tsx");

  it("zasiewa klucze funkcjami komponentów, nie kopiami", () => {
    for (const fn of ["types", "list", "prefill", "effects"]) {
      expect(harness).toMatch(new RegExp(`setQueryData[^;]*b2bDocumentsKeys\\.${fn}\\(`));
    }
    const components = [
      "components/v2/b2b-generator/documents/DocumentsTab.tsx",
      "components/v2/b2b-generator/documents/DocumentWizard.tsx",
      "components/v2/b2b-generator/documents/DocumentDialogs.tsx",
    ].map(read);
    // Komponent pytający o te dane też bierze klucz z funkcji.
    expect(components.join("\n")).toMatch(/queryKey: b2bDocumentsKeys\.list\(/);
    expect(components.join("\n")).toMatch(/queryKey: b2bDocumentsKeys\.prefill\(/);
    expect(components.join("\n")).toMatch(/queryKey: b2bDocumentsKeys\.effects\(/);
  });

  it("odcina sieć i zdejmuje blokadę przy odmontowaniu", () => {
    expect(harness).toContain("api.interceptors.request.use(");
    expect(harness).toContain("api.interceptors.request.eject(");
  });

  it("jest publiczną ścieżką (harness bez logowania)", () => {
    // Surowy plik — w middleware są wzorce ścieżek z `/*`, których
    // wycinanie komentarzy by nie przeżyło.
    expect(readFileSync(join(SRC, "middleware.ts"), "utf8")).toContain(
      '"/preview/b2b-documents"',
    );
  });
});
