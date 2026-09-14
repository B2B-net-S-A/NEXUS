import { describe, expect, it } from "vitest";

import {
  NOTIFICATIONS_INITIAL_LIMIT,
  canShowMoreNotifications,
  nextNotificationsLimit,
} from "@/lib/notifications-paging";

// B51: dzwonek pokazywał sztywno 20 pozycji bez drogi do starszych.
describe("notifications paging", () => {
  it("progi rosną 20 → 50 → 200 i kończą się na suficie backendu", () => {
    expect(NOTIFICATIONS_INITIAL_LIMIT).toBe(20);
    expect(nextNotificationsLimit(20)).toBe(50);
    expect(nextNotificationsLimit(50)).toBe(200);
    expect(nextNotificationsLimit(200)).toBeNull();
  });

  it("„Pokaż więcej” tylko przy pełnej liście i dostępnym wyższym progu", () => {
    expect(canShowMoreNotifications(20, 20)).toBe(true);
    expect(canShowMoreNotifications(19, 20)).toBe(false);
    expect(canShowMoreNotifications(0, 20)).toBe(false);
    expect(canShowMoreNotifications(200, 200)).toBe(false);
  });
});
