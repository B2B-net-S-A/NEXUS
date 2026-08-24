/**
 * Konsola Priority Work musi mieć wejście — inaczej cały model jest martwy.
 *
 * Cutover RBAC z #1031 odmontował `TeamAllocationBoard` i `MyPriorityQueue`
 * i nie zamontował ich nigdzie indziej. `grep` po nazwach poza ich własnym
 * katalogiem nie zwracał NICZEGO, a mimo to utrzymywaliśmy 1743 linie routera,
 * 1131 serwisu, 817 polityki, 9 tabel produkcyjnych i pętlę w lifespanie.
 *
 * Najgorsza konsekwencja nie była kosztem utrzymania, tylko tym, że bezpieczny
 * rollout stał się NIEWYKONALNY: `config.py` zaleca `off -> shadow -> enforce`,
 * ale przestawienie `RECRUITMENT_PRIORITY_MODE` na `enforce` bez opublikowanego
 * planu zablokowałoby każdemu rekruterowi otwarcie nowej pary kandydat/
 * rekrutacja — a nie było ekranu, żeby plan opublikować albo blokadę zdjąć.
 *
 * Test czyta ŹRÓDŁO, nie renderuje dashboardu: ten ciągnie sesję i kilkanaście
 * zapytań, więc test renderujący padałby z powodów niezwiązanych z montażem.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = readFileSync(
  join(__dirname, "..", "RoleDashboard.tsx"),
  "utf8",
);

describe("Priority Work — wejście z dashboardu", () => {
  it("importuje oba boardy", () => {
    expect(SRC).toContain("TeamAllocationBoard");
    expect(SRC).toContain("MyPriorityQueue");
  });

  it("TeamAllocationBoard jest RENDEROWANY, nie tylko zaimportowany", () => {
    // Sam import nie daje wejścia — dokładnie tak wyglądał stan przed
    // odmontowaniem, gdy komponenty istniały i nie były osiągalne.
    expect(SRC).toMatch(/<TeamAllocationBoard\s*\/>/);
  });

  it("MyPriorityQueue jest RENDEROWANY", () => {
    expect(SRC).toMatch(/<MyPriorityQueue\s*\/>/);
  });

  it("oba trafiają do drzewa, a nie tylko do zmiennej", () => {
    // Wcześniejsza wersja tego pliku miała `oversight` i `myQueue` wpięte
    // w zwracany JSX; nowe boardy muszą być tam TEŻ, inaczej powstaje
    // martwa zmienna, którą TypeScript przepuści.
    const ret = SRC.slice(SRC.indexOf("return (") );
    expect(ret).toContain("{teamAllocation}");
    expect(ret).toContain("{priorityQueue}");
  });

  it("warunek skrótu uwzględnia nowe boardy", () => {
    // `if (!oversight && !myQueue) return <Preset/>` odcinałoby je zawsze,
    // bo skrót wykonałby się przed dołożeniem ich do drzewa.
    expect(SRC).toMatch(/!teamAllocation\s*&&\s*!priorityQueue/);
  });
});
