import { describe, expect, it } from "vitest";

import {
  formatNotificationText,
  notificationTimeAgo,
} from "@/lib/notification-format";

describe("formatNotificationText (UAT M00-B05)", () => {
  it("zamienia daty RRRR-MM-DD na DD.MM.RRRR", () => {
    expect(
      formatNotificationText("Zamówienie ZAM-1 kończy się 2026-09-19 (za 7 dni)"),
    ).toBe("Zamówienie ZAM-1 kończy się 19.09.2026 (za 7 dni)");
  });

  it("zostawia tekst bez dat i pustą wartość", () => {
    expect(formatNotificationText("Nowy kandydat")).toBe("Nowy kandydat");
    expect(formatNotificationText(null)).toBe("");
  });

  it("nie rusza numerów przypominających datę w dłuższym ciągu", () => {
    expect(formatNotificationText("nr 12026-09-190")).toBe("nr 12026-09-190");
  });
});

describe("notificationTimeAgo (UAT M00-B05)", () => {
  const now = Date.parse("2026-09-14T12:00:00Z");
  const ago = (seconds: number) => new Date(now - seconds * 1000).toISOString();

  it("odmienia dni po polsku", () => {
    expect(notificationTimeAgo(ago(86400), now)).toBe("1 dzień temu");
    expect(notificationTimeAgo(ago(2 * 86400), now)).toBe("2 dni temu");
    expect(notificationTimeAgo(ago(5 * 86400), now)).toBe("5 dni temu");
  });

  it("krótsze odstępy bez zmian", () => {
    expect(notificationTimeAgo(ago(10), now)).toBe("Przed chwilą");
    expect(notificationTimeAgo(ago(300), now)).toBe("5 min temu");
    expect(notificationTimeAgo(ago(7200), now)).toBe("2 h temu");
  });
});
