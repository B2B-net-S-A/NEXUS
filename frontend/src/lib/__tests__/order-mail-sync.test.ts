import { describe, expect, it } from "vitest";

import type { OrderMailLastRun, OrderMailSyncStatus } from "@/lib/api/orderMail";
import {
  baselineOf,
  checkOutcome,
  formatAge,
  formatLastRunSummary,
  plural,
  reasonLabel,
} from "@/lib/order-mail-sync";

function run(over: Partial<OrderMailLastRun> = {}): OrderMailLastRun {
  return {
    reason: "scheduled", started_at: "2031-03-03T08:00:00+00:00", finished_at: "2031-03-03T08:00:41+00:00",
    status: "ok", error: null, messages: 3, new_messages: 2, attachments: 2, auto_applied: 1, needs_review: 1,
    unrecognized: 0, duplicates: 0, skipped_existing: 1, ignored_no_pdf: 0, ignored_sender: 0, failed: 0, errors: [],
    ...over,
  };
}

function status(over: Partial<OrderMailSyncStatus> = {}): OrderMailSyncStatus {
  return {
    enabled: true, interval_minutes: 60, autoapply_enabled: false, running: false,
    started_at: "2031-03-03T08:00:00+00:00", interrupted: false, last_completed: run(), can_trigger: true,
    ...over,
  };
}

describe("checkOutcome", () => {
  it("is pending while the run is in progress and completes on a NEW finished_at", () => {
    const before = baselineOf(status());
    expect(checkOutcome(status({ running: true }), before)).toBe("pending");
    // Ten sam finished_at co przed kliknięciem = to jeszcze stary wynik.
    expect(checkOutcome(status(), before)).toBe("pending");
    const done = status({ last_completed: run({ finished_at: "2031-03-03T09:05:00+00:00", reason: "manual" }) });
    expect(checkOutcome(done, before)).toBe("completed");
  });

  it("reports an interruption only for a run started after the click", () => {
    const before = baselineOf(status({ interrupted: true, started_at: "2031-03-03T08:30:00+00:00" }));
    // Przerwany bieg SPRZED kliknięcia to stan zastany, nie wynik sprawdzenia.
    expect(checkOutcome(status({ interrupted: true, started_at: "2031-03-03T08:30:00+00:00" }), before)).toBe("pending");
    expect(checkOutcome(status({ interrupted: true, started_at: "2031-03-03T09:00:00+00:00" }), before)).toBe("interrupted");
  });

  it("baseline of no status yet is empty and the first completion counts", () => {
    const before = baselineOf(null);
    expect(before).toEqual({ finishedAt: null, startedAt: null });
    expect(checkOutcome(status(), before)).toBe("completed");
  });
});

describe("formatLastRunSummary", () => {
  it("always names the three ticket numbers and adds the optional ones when non-zero", () => {
    expect(formatLastRunSummary(run())).toBe("2 nowe wiadomości · 1 zapisane automatycznie · 1 do weryfikacji");
    expect(formatLastRunSummary(run({ new_messages: 0, auto_applied: 0, needs_review: 0 }))).toBe(
      "0 nowych wiadomości · 0 zapisanych automatycznie · 0 do weryfikacji",
    );
    expect(formatLastRunSummary(run({ new_messages: 1, unrecognized: 2, failed: 1 }))).toBe(
      "1 nowa wiadomość · 1 zapisane automatycznie · 1 do weryfikacji · 2 nierozpoznanych klientów · 1 błąd",
    );
  });

  it("plural follows Polish rules including 12–14", () => {
    expect(plural(1, "a", "b", "c")).toBe("a");
    expect(plural(3, "a", "b", "c")).toBe("b");
    expect(plural(5, "a", "b", "c")).toBe("c");
    expect(plural(12, "a", "b", "c")).toBe("c");
    expect(plural(22, "a", "b", "c")).toBe("b");
    expect(plural(0, "a", "b", "c")).toBe("c");
  });

  it("labels reasons in Polish", () => {
    expect(reasonLabel("manual")).toBe("ręcznie");
    expect(reasonLabel("scheduled")).toBe("automatycznie");
    expect(reasonLabel(null)).toBe("—");
  });
});

describe("formatAge", () => {
  const now = Date.parse("2031-03-03T10:00:00Z");
  it("speaks in minutes, hours, days", () => {
    expect(formatAge(null, now)).toBe("nigdy");
    expect(formatAge("2031-03-03T09:59:40Z", now)).toBe("przed chwilą");
    expect(formatAge("2031-03-03T09:48:00Z", now)).toBe("12 min temu");
    expect(formatAge("2031-03-03T07:00:00Z", now)).toBe("3 h temu");
    expect(formatAge("2031-02-28T10:00:00Z", now)).toBe("3 dni temu");
    expect(formatAge("garbage", now)).toBe("nieznany");
  });
});
