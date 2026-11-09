/**
 * Strona `/k/{token}` jest publiczna: nie może wołać instancji axios z tokenem
 * użytkownika, bo ta wysłałaby sesję pracownika, który otworzył link, a przy 401
 * wyrzuciła klienta na logowanie. Instancję ma tylko okno Delivery Leada.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");
const DIR = join(SRC, "components/v2/client-panel");
const INTERNAL = new Set(["ClientPanelManage.tsx"]);

const AUTH_CLIENT = /from\s+["']@\/lib\/api["']|clientPanelAdmin["']/;

describe("panel klienta: granica publiczna", () => {
  it("komponenty klienta nie importują klienta API z tokenem", () => {
    const files = readdirSync(DIR).filter(
      (name) => /\.tsx?$/.test(name) && !INTERNAL.has(name),
    );
    expect(files).toContain("ClientPanelApp.tsx");
    const offenders = files.filter((name) => AUTH_CLIENT.test(readFileSync(join(DIR, name), "utf8")));
    expect(offenders).toEqual([]);
  });

  it("klient publiczny stoi na gołym axios", () => {
    const source = readFileSync(join(SRC, "lib/api/clientPanel.ts"), "utf8");
    expect(source).not.toMatch(/from\s+["']@\/lib\/api["']/);
    expect(source).not.toMatch(/Authorization|getAccessToken/);
  });

  it("strona ma noindex i nie oddaje adresu w Refererze", () => {
    const source = readFileSync(join(SRC, "app/k/[token]/page.tsx"), "utf8");
    expect(source).toMatch(/index:\s*false/);
    expect(source).toMatch(/referrer:\s*"no-referrer"/);
  });

  it("linki do plików nie przekazują adresu z tokenem", () => {
    for (const name of ["FilesTab.tsx", "EvidenceTab.tsx"]) {
      const source = readFileSync(join(DIR, name), "utf8");
      expect(source).toContain('rel="noopener noreferrer"');
    }
  });
});
