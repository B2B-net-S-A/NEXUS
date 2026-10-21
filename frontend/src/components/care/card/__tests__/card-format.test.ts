/**
 * Karta konsultanta: cztery liczby (z kręgiem D11 dla opinii), „Sprawy · N
 * otwarte” i filtry „Historii”.
 */
import { describe, expect, it } from "vitest";

import type { CardCase, TimelineEvent } from "@/lib/api/care";

import {
  casesHeading,
  daysAheadText,
  daysAgoText,
  historyCounts,
  historyEvents,
  lastContactKpi,
  managerFeedbackKpi,
  orderEndKpi,
  satisfactionKpi,
} from "../card-format";

const event = (kind: TimelineEvent["kind"], on: string, future = false): TimelineEvent => ({
  kind,
  on,
  title: kind,
  detail: null,
  link: null,
  future,
});

const kase = (id: number, status: string): CardCase => ({
  id,
  title: `Sprawa ${id}`,
  area: "administration",
  area_label: "Administracja",
  status,
  status_label: status,
  due_on: null,
  follow_up_on: null,
  assignee_name: null,
  source: "manual",
  content_hidden: false,
});

describe("card-format", () => {
  it("dni temu i do przodu", () => {
    expect(daysAgoText(0)).toBe("dziś");
    expect(daysAgoText(1)).toBe("wczoraj");
    expect(daysAgoText(12)).toBe("12 dni temu");
    expect(daysAheadText(34)).toBe("za 34 dni");
    expect(daysAheadText(1)).toBe("jutro");
    expect(daysAheadText(-1)).toBe("minął wczoraj");
    expect(daysAheadText(-4)).toBe("minął 4 dni temu");
  });

  it("ostatni kontakt i zadowolenie ze spadkiem", () => {
    expect(lastContactKpi(null)).toMatchObject({ value: "brak rozmów", tone: "warning" });
    expect(lastContactKpi({ on: "2026-10-10", days_ago: 12 })).toMatchObject({
      value: "12 dni temu",
      note: "10.10.2026",
    });
    expect(satisfactionKpi({ value: 3, previous: 5 })).toMatchObject({
      value: "3/5",
      note: "spadek z 5/5",
      tone: "warning",
    });
    expect(satisfactionKpi({ value: 5, previous: 5 }).note).toBe("bez zmiany");
    expect(satisfactionKpi(null).value).toBe("—");
  });

  it("opinia menedżera: spoza D11 nie widać nic; ocena i przedłużenie słowem", () => {
    const hidden = managerFeedbackKpi({ avg: 2.5, extension: "no", on: "2026-10-01" }, false);
    expect(hidden.value).toBe("—");
    expect(hidden.note).not.toMatch(/2,5/);
    expect(managerFeedbackKpi({ avg: 3.7, extension: "likely", on: "2026-10-01" }, true)).toMatchObject({
      value: "3,7 / 5",
      note: "przedłużenie: raczej tak · 01.10.2026",
      tone: "warning",
    });
    expect(managerFeedbackKpi(null, true).value).toBe("brak opinii");
  });

  it("koniec zamówienia: ≤ 30 dni czerwony, ≤ 60 żółty", () => {
    expect(orderEndKpi({ on: "2026-11-20", days: 29 }).tone).toBe("danger");
    expect(orderEndKpi({ on: "2026-12-10", days: 49 }).tone).toBe("warning");
    expect(orderEndKpi({ on: "2027-03-01", days: 130 }).tone).toBe("neutral");
    expect(orderEndKpi(null).value).toBe("bez daty");
  });

  it("nagłówek spraw liczy tylko otwarte", () => {
    expect(casesHeading([])).toBe("Sprawy");
    expect(casesHeading([kase(1, "new"), kase(2, "waiting"), kase(3, "closed")])).toBe("Sprawy · 2 otwarte");
    expect(casesHeading([kase(1, "in_progress")])).toBe("Sprawy · 1 otwarta");
  });

  it("filtry historii: przeszłe od najnowszych, przyszłe tylko we „Wszystko”", () => {
    const events = [
      event("start", "2026-01-05"),
      event("conversation", "2026-10-01"),
      event("case_opened", "2026-10-03"),
      event("feedback", "2026-09-20"),
      event("owner", "2026-08-01"),
      event("plan", "2026-11-01", true),
      event("tech_card", "2026-10-01"),
    ];
    expect(historyEvents(events, "all").past.map((e) => e.kind)).toEqual([
      "case_opened",
      "conversation",
      "tech_card",
      "feedback",
      "owner",
      "start",
    ]);
    expect(historyEvents(events, "all").ahead).toHaveLength(1);
    expect(historyEvents(events, "talks").past.map((e) => e.kind)).toEqual(["conversation", "tech_card"]);
    expect(historyEvents(events, "talks").ahead).toEqual([]);
    expect(historyEvents(events, "cases").past.map((e) => e.kind)).toEqual(["case_opened"]);
    expect(historyEvents(events, "contract").past.map((e) => e.kind)).toEqual(["start"]);
    expect(historyCounts(events)).toEqual({ all: 6, talks: 2, cases: 1, feedback: 1, contract: 1 });
  });
});
