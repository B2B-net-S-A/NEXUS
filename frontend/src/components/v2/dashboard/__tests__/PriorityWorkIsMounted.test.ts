/**
 * Konsola Priority Work musi mieć wejście — inaczej cały model jest martwy.
 *
 * Cutover RBAC z #1031 odmontował `TeamAllocationBoard` i `MyPriorityQueue`
 * i nie zamontował ich nigdzie indziej. `grep` po nazwach poza ich własnym
 * katalogiem nie zwracał NICZEGO, a mimo to utrzymywaliśmy 1743 linie routera,
 * 1131 serwisu, 817 polityki, 9 tabel produkcyjnych i pętlę w lifespanie.
 *
 * Od 21.09.2026 pulpit jest własny (kafelki), więc wejściem jest KATALOG
 * kafelków: oba boardy muszą być w nim jako typy i faktycznie renderowane
 * przez `TileContent`. Test czyta ŹRÓDŁO — render ciągnie sesję i kilkanaście
 * zapytań, więc padałby z powodów niezwiązanych z montażem.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { TILE_DEFINITIONS, TILE_TEMPLATES } from "@/lib/dashboard-tiles/catalog";

const CONTENT = readFileSync(
  join(__dirname, "..", "custom", "TileContent.tsx"),
  "utf8",
);

describe("Priority Work — wejście z katalogu kafelków", () => {
  it("oba boardy są typami kafelków i są w katalogu", () => {
    expect(TILE_DEFINITIONS.team_allocation).toBeDefined();
    expect(TILE_DEFINITIONS.my_priority_queue).toBeDefined();
    const keys = TILE_TEMPLATES.map((t) => t.key);
    expect(keys).toContain("team_allocation");
    expect(keys).toContain("my_priority_queue");
  });

  it("TileContent RENDERUJE oba boardy, nie tylko je importuje", () => {
    expect(CONTENT).toMatch(/case "team_allocation":\s*return <TeamAllocationBoard \/>/);
    expect(CONTENT).toMatch(/case "my_priority_queue":\s*return <MyPriorityQueue \/>/);
  });
});
