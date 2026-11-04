import { describe, expect, it } from "vitest";

import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import { cardBadges, compactCardBadge, type CardBadgeContext } from "@/lib/board-card-badges";

const NOW = new Date("2026-11-03T12:00:00Z");

function ctx(column: CardBadgeContext["column"]): CardBadgeContext {
  return {
    column,
    cproEnabled: false,
    viewerId: 1,
    now: NOW,
    stageBadge: null,
    viewerOwnsDlReview: false,
  };
}

function item(start: string): KanbanItem {
  return {
    id: 1,
    candidate_id: 2,
    booked_call: { event_id: 3, start_time: start, owner_name: "Rekruter" },
  } as unknown as KanbanItem;
}

function badge(start: string, column: CardBadgeContext["column"] = "screening") {
  return cardBadges(item(start), ctx(column)).find((b) => b.key === "booked_call");
}

describe("plakietka umówionego telefonu", () => {
  it("dzisiejszy jest pełny, zaległy czerwony, późniejszy jasny", () => {
    expect(badge("2026-11-03T15:00:00Z")?.tone).toBe("call_today");
    expect(badge("2026-11-02T14:00:00Z")?.tone).toBe("urgent");
    expect(badge("2026-11-04T08:00:00Z")?.tone).toBe("own");
  });

  it("na karcie pokazuje samą godzinę, a pełną treść w podpowiedzi", () => {
    const compact = compactCardBadge(badge("2026-11-03T15:00:00Z")!);
    expect(compact?.short).toBe("dziś 16:00");
    expect(compact?.full).toContain("dzwoni Rekruter");
  });

  it("poza „Nowymi” i „Screeningiem” jej nie ma", () => {
    expect(badge("2026-11-03T15:00:00Z", "verified")).toBeUndefined();
  });
});
