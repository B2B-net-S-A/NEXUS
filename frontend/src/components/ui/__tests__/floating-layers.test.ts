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

  it.each([
    "ui/popover.tsx",
    "ui/dropdown-menu.tsx",
    "ui/select.tsx",
    "ui/tooltip.tsx",
    "ui/dialog.tsx",
  ])("%s leży nad oknem AppShell", (file) => {
    const values = zValues(read(file));
    expect(values.length).toBeGreaterThan(0);
    for (const z of values) expect(z).toBeGreaterThan(modalZ);
  });

  // Okno dialogowe (`Dialog`, `ConfirmV2`) i lista wyboru otwierają się
  // nawzajem w obie strony: lista w oknie i potwierdzenie z okienka listy
  // (14.10.2026: potwierdzenie „Zdejmij” z okienka kolumny „Rekruter” leżało
  // POD okienkiem — z-50 pod z-110). Stała różnica warstw psuje zawsze jeden
  // kierunek, więc obie stoją na jednej warstwie, a wyżej leży to, co
  // otwarto później (portal dopisywany na koniec `<body>`).
  it("okno dialogowe stoi na tej samej warstwie co lista wyboru", () => {
    const layer = (file: string) => new Set(zValues(read(file)));
    const popover = layer("ui/popover.tsx");
    expect([...layer("ui/dialog.tsx")]).toEqual([...popover]);
    expect([...layer("ui/dropdown-menu.tsx")]).toEqual([...popover]);
    expect([...layer("ui/select.tsx")]).toEqual([...popover]);
  });
});
