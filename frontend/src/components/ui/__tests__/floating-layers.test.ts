import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Pływające elementy (lista wyboru, menu, select, podpowiedź) renderują się
// w portalu i muszą leżeć NAD oknem `Modal` z AppShell. Zgłoszenie 30.09.2026:
// lista „Współpracownicy” w oknie edycji rekrutacji otwierała się pod oknem.
const root = join(__dirname, "..", "..");
const read = (rel: string) => readFileSync(join(root, rel), "utf8");

function zValues(source: string): number[] {
  const code = source
    .split("\n")
    .filter((line) => !line.trim().startsWith("//"))
    .join("\n");
  return [...code.matchAll(/(?:^|[\s"'`])z-(\d+)(?=[\s"'`])/g)].map((m) => Number(m[1]));
}

describe("warstwy pływających elementów", () => {
  const modalZ = Math.max(
    ...zValues(read("AppShell.tsx").match(/DialogPrimitive\.Overlay className="[^"]+"/)![0]),
  );

  it.each(["ui/popover.tsx", "ui/dropdown-menu.tsx", "ui/select.tsx", "ui/tooltip.tsx"])(
    "%s leży nad oknem AppShell",
    (file) => {
      const values = zValues(read(file));
      expect(values.length).toBeGreaterThan(0);
      for (const z of values) expect(z).toBeGreaterThan(modalZ);
    },
  );
});
