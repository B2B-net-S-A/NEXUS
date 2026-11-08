import { describe, expect, it } from "vitest";

import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import { cardBadges, fromPreviousOpening, type CardBadgeContext } from "@/lib/board-card-badges";

// Ponowne otwarcie rekrutacji (05.11.2026): karta, której ostatni ruch był
// przed otwarciem, zostaje na Tablicy wyszarzona i z etykietą.
const OPENED = "2026-10-08T07:30:00Z";

function item(movedAt: string | null): KanbanItem {
  return { id: 1, candidate_id: 11, stage: "acceptance", moved_at: movedAt } as KanbanItem;
}

function ctx(openingStartedAt: string | null): CardBadgeContext {
  return {
    column: "contract",
    cproEnabled: false,
    viewerId: 7,
    now: new Date("2026-11-05T10:00:00Z"),
    openingStartedAt,
  };
}

describe("karta z poprzedniego otwarcia rekrutacji", () => {
  it("ruch przed otwarciem = poprzednie otwarcie, od otwarcia = bieżące", () => {
    expect(fromPreviousOpening(item("2026-05-14T09:00:00Z"), OPENED)).toBe(true);
    expect(fromPreviousOpening(item(OPENED), OPENED)).toBe(false);
    expect(fromPreviousOpening(item("2026-10-20T09:00:00Z"), OPENED)).toBe(false);
  });

  it("rekrutacja nigdy nie otwarta ponownie i karta bez daty — bez etykiety", () => {
    expect(fromPreviousOpening(item("2026-05-14T09:00:00Z"), null)).toBe(false);
    expect(fromPreviousOpening(item(null), OPENED)).toBe(false);
  });

  it("etykieta podaje dzień otwarcia w Warszawie", () => {
    const [badge] = cardBadges(item("2026-05-14T09:00:00Z"), ctx("2026-10-07T22:30:00Z"));
    expect(badge.key).toBe("previous_opening");
    expect(badge.label).toBe("Sprzed otwarcia 08.10.2026");
    expect(badge.tone).toBe("neutral");
    expect(badge.title).toContain("Nie liczy się w „W drodze”");
  });

  it("karta ruszona po otwarciu nie ma etykiety", () => {
    const keys = cardBadges(item("2026-10-20T09:00:00Z"), ctx(OPENED)).map((b) => b.key);
    expect(keys).not.toContain("previous_opening");
  });
});
