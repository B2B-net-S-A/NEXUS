import { describe, expect, it } from "vitest";

import { cardBadges } from "@/lib/board-card-badges";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import {
  notifyLine,
  rateArrowLine,
  rateChangeBadgeText,
  toHourly,
  type RateChangeBadge,
} from "@/lib/rate-change";

const BADGE: RateChangeBadge = {
  id: 1,
  status: "requested",
  requires_decision: true,
  previous_hourly: 110,
  requested_hourly: 125,
  requested_label: "125 zł/h",
  agreed_hourly: null,
  negotiator_name: null,
  negotiation_due: null,
  created_at: null,
};

describe("zmiana stawki — teksty", () => {
  it("plakietka mówi, na kogo czeka sprawa", () => {
    expect(rateChangeBadgeText(BADGE)).toBe("stawka ↑ czeka na DL");
    expect(rateArrowLine(BADGE)).toBe("110 → 125 zł/h");
    expect(
      rateChangeBadgeText({
        ...BADGE,
        status: "negotiating",
        negotiator_name: "Anna Nowak",
        negotiation_due: "2026-10-06",
      }),
    ).toBe("w negocjacji · Anna Nowak do 06.10");
    expect(rateChangeBadgeText({ ...BADGE, status: "agreed", agreed_hourly: 115 })).toBe(
      "ustalona 115 zł/h · decyzja DL",
    );
  });

  it("zdanie o powiadomieniu zależy od etapu i kierunku zmiany", () => {
    expect(notifyLine({ notifies: false, cv_at_client: false }, { rising: true, reason: "conversation" })).toMatch(
      /przed weryfikacją/,
    );
    expect(notifyLine({ notifies: true, cv_at_client: false }, { rising: true, reason: "conversation" })).toBe(
      "Zapis od razu powiadomi Delivery Leada rekrutacji i Head of Recruitment.",
    );
    expect(notifyLine({ notifies: true, cv_at_client: true }, { rising: true, reason: "conversation" })).toMatch(
      /DL dostanie zadanie/,
    );
    expect(notifyLine({ notifies: true, cv_at_client: true }, { rising: false, reason: "conversation" })).not.toMatch(
      /zadanie/,
    );
    expect(notifyLine({ notifies: true, cv_at_client: true }, { rising: true, reason: "typo" })).not.toMatch(
      /zadanie/,
    );
  });

  it("przelicza na zł/h jak serwer", () => {
    expect(toHourly("880", "daily")).toBe(110);
    expect(toHourly("16800", "monthly")).toBe(100);
    expect(toHourly("125,5", "hourly")).toBe(125.5);
    expect(toHourly("0", "hourly")).toBeNull();
    expect(toHourly("abc", "hourly")).toBeNull();
  });

  it("karta Tablicy dostaje plakietkę zmiany stawki w każdej kolumnie", () => {
    const item = { candidate_id: 1, rate_change: BADGE } as unknown as KanbanItem;
    const badges = cardBadges(item, { column: "client_interview", cproEnabled: false, viewerId: 1, now: new Date() });
    const badge = badges.find((b) => b.key === "rate_change");
    expect(badge?.label).toBe("110 → 125 zł/h · stawka ↑ czeka na DL");
    expect(badge?.tone).toBe("wait");
  });
});
