import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Panel szczegółów `ListDetailLayout` od 1600 px jest `sticky` w kolumnie obok
 * tabeli. `overflow-hidden|auto|scroll` na którymkolwiek przodku robi z niego
 * kontener przewijania i sticky przestaje działać: panel staje na górze listy.
 * 18.11.2026 w Zamówieniach klienta stał 4668 px nad klikniętym wierszem, bo
 * karta profilu klienta miała `overflow-hidden`. Rogi przycina `overflow-clip`,
 * który kontenera przewijania nie tworzy. jsdom nie liczy layoutu, stąd
 * strażnik na źródle.
 */

const SRC = join(__dirname, "..");

describe("panel obok listy (ListDetailLayout) zostaje przyklejony", () => {
  it("karta profilu klienta nie jest kontenerem przewijania (Zamówienia, Kontrakty u klienta)", () => {
    const source = readFileSync(join(SRC, "app/clients/[id]/page.tsx"), "utf8");
    const card = source
      .split("\n")
      .find((line) => line.includes('className="bg-card dark:bg-muted rounded-xl border border-border shadow-xs'));
    expect(card, "nie znaleziono karty profilu klienta").toBeDefined();
    expect(card).not.toMatch(/\boverflow-(hidden|auto|scroll)\b/);
  });
});
