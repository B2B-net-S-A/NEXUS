import { describe, expect, it } from "vitest";

import {
  NOTIFICATION_TYPES,
  selectableNotificationTypes,
} from "@/components/settings/TeamsNotificationsCard";

describe("Teams: typy powiadomień do wyboru (runda 7, R7-N5-6)", () => {
  it("nowy kanał widzi tylko typy, które NEXUS wysyła", () => {
    expect(selectableNotificationTypes([]).map((o) => o.value)).toEqual([
      "candidate_added",
    ]);
  });

  it("zapisany wcześniej martwy typ zostaje widoczny, żeby dało się go zdjąć", () => {
    const values = selectableNotificationTypes(["contract_signed"]).map(
      (o) => o.value,
    );
    expect(values).toEqual(["candidate_added", "contract_signed"]);
  });

  it("martwe typy mówią wprost, że nie są wysyłane", () => {
    for (const opt of NOTIFICATION_TYPES.filter((o) => !o.sent)) {
      expect(opt.label).toContain("nie jest wysyłane");
    }
  });
});
