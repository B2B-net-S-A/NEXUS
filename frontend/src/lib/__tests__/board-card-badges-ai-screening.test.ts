import { describe, expect, it } from "vitest";

import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import { aiScreeningBadge, cardBadges, type CardBadgeContext } from "@/lib/board-card-badges";

const NOW = new Date("2026-09-29T10:00:00Z");

function item(extra: Partial<KanbanItem> = {}): KanbanItem {
  return { id: 1, candidate_id: 11, stage: "new", ...extra } as KanbanItem;
}

function ctx(): CardBadgeContext {
  return { column: "new", cproEnabled: false, viewerId: 7, now: NOW };
}

const meta = (over: Partial<NonNullable<KanbanItem["entry_ai_screening"]>> = {}) => ({
  verdict: "fits" as const,
  assessed: true,
  must_found: 2,
  must_total: 3,
  overridden: false,
  ...over,
});

describe("plakietka przeglądu AI na karcie zgłoszenia (0404)", () => {
  it("zgłoszenie bez przeglądu zostaje „Z ogłoszenia”", () => {
    const labels = cardBadges(item({ entry_source: "application" }), ctx()).map((b) => b.label);
    expect(labels[0]).toBe("Z ogłoszenia");
  });

  it("werdykt serwera zastępuje „Z ogłoszenia”", () => {
    const badges = cardBadges(
      item({ entry_source: "application", entry_ai_screening: meta() }),
      ctx(),
    );
    expect(badges[0]).toMatchObject({ key: "source", label: "AI: pasuje", tone: "ok" });
    expect(badges[0].title).toContain("Must-have w CV: 2 z 3.");
  });

  it("do sprawdzenia, nieocenione i dodane mimo odrzucenia mają własne etykiety", () => {
    expect(aiScreeningBadge(meta({ verdict: "unclear" }))?.label).toBe("AI: do sprawdzenia");
    expect(aiScreeningBadge(meta({ verdict: "unclear", assessed: false }))?.label).toBe(
      "AI nie oceniło",
    );
    expect(aiScreeningBadge(meta({ verdict: "not_fit", overridden: true }))?.label).toBe(
      "AI: odrzucony · dodany ręcznie",
    );
    expect(aiScreeningBadge(null)).toBeNull();
  });

  it("rekrutacja bez must-have nie dopisuje liczby do podpowiedzi", () => {
    expect(aiScreeningBadge(meta({ must_total: 0, must_found: 0 }))?.title).not.toContain(
      "Must-have",
    );
  });
});

describe("plakietka linku rekrutacji (etap 2 linków, 19.10.2026)", () => {
  const fromLink = (over: Partial<KanbanItem> = {}) =>
    item({
      entry_source: "application",
      entry_link_owner_id: 7,
      entry_link_owner_name: "Tomasz Kowal",
      ...over,
    });

  it("właściciel linku widzi „Z Twojego linku”, a werdykt AI zostaje obok", () => {
    const badges = cardBadges(fromLink({ entry_ai_screening: meta() }), ctx());
    expect(badges[0]).toMatchObject({ key: "link", label: "Z Twojego linku" });
    expect(badges[1]).toMatchObject({ key: "source", label: "AI: pasuje" });
  });

  it("inni widzą, czyj to link", () => {
    const badges = cardBadges(fromLink({ entry_link_owner_id: 8 }), ctx());
    expect(badges[0]).toMatchObject({ key: "link", label: "Z linku: Tomasz" });
    expect(badges[0].title).toContain("Tomasz Kowal");
  });

  it("bez przeglądu AI nie dubluje „Z ogłoszenia”", () => {
    const labels = cardBadges(fromLink(), ctx()).map((b) => b.label);
    expect(labels).toContain("Z Twojego linku");
    expect(labels).not.toContain("Z ogłoszenia");
  });

  it("plakietka linku zostaje także przy etapie „Z ogłoszenia”", () => {
    const badges = cardBadges(fromLink({ entry_ai_screening: meta() }), {
      ...ctx(),
      stageBadge: "posting",
    });
    expect(badges.map((b) => b.key)).toEqual(expect.arrayContaining(["link"]));
    expect(badges.map((b) => b.key)).not.toContain("source");
  });

  it("karta spoza zgłoszenia nie ma plakietki linku", () => {
    const badges = cardBadges(
      item({ entry_source: "added_manual", entry_link_owner_id: 7 }),
      ctx(),
    );
    expect(badges.map((b) => b.key)).not.toContain("link");
  });
});
