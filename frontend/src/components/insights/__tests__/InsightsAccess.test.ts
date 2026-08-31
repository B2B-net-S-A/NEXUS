import { describe, expect, it } from "vitest";

import {
  getDefaultTabForUser,
  getVisibleInsightTabIds,
} from "@/components/insights/InsightsView";

type AuthUser = Parameters<typeof getVisibleInsightTabIds>[0];

const user = (role: string): AuthUser =>
  ({ role, roles: [role] }) as AuthUser;

describe("Insights business-read dla Finance", () => {
  it("pokazuje wszystkie trzy zakładki i otwiera Klientów domyślnie", () => {
    const finance = user("finance");

    expect(getVisibleInsightTabIds(finance)).toEqual([
      "rekrutacja",
      "klienci",
      "zarzad",
    ]);
    expect(getDefaultTabForUser(finance)).toBe("klienci");
  });

  it("nie poszerza zakładek rekrutera", () => {
    expect(getVisibleInsightTabIds(user("recruiter"))).toEqual([
      "rekrutacja",
    ]);
  });
});
