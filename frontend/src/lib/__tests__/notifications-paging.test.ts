import { describe, expect, it } from "vitest";

import {
  NOTIFICATIONS_INITIAL_LIMIT,
  canShowMoreNotifications,
  nextNotificationsLimit,
  previousNotificationsLimit,
  shownNotificationsLimit,
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

  it("w trakcie doładowania liczy z poprzedniego progu, więc przycisk nie znika", () => {
    expect(previousNotificationsLimit(20)).toBeNull();
    expect(previousNotificationsLimit(50)).toBe(20);
    expect(previousNotificationsLimit(200)).toBe(50);
    // Kliknięto „Pokaż więcej" (limit 50), na ekranie wciąż 20 starych pozycji.
    expect(shownNotificationsLimit(50, true)).toBe(20);
    expect(canShowMoreNotifications(20, shownNotificationsLimit(50, true))).toBe(true);
    // Po doładowaniu liczy się już nowy limit.
    expect(shownNotificationsLimit(50, false)).toBe(50);
    expect(shownNotificationsLimit(20, true)).toBe(20);
  });
});
