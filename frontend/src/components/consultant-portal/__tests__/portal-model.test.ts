import { describe, expect, it } from "vitest";

import type { PortalFaqItem, PortalMonth } from "@/lib/api/consultant-portal";

import {
  formatDay,
  groupFaq,
  matchesFaq,
  monthActionLabel,
  monthLabel,
  offsetLabel,
  rateLabel,
  slotLabel,
} from "../portal-model";

const item = (id: number, topic: PortalFaqItem["topic"], question: string, answer = ""): PortalFaqItem => ({
  id,
  topic,
  question,
  answer,
  position: 0,
});

describe("portal-model", () => {
  it("szuka po pytaniu i odpowiedzi, wszystkimi słowami", () => {
    const faq = item(1, "invoice", "Do kiedy faktura?", "Do piątego dnia miesiąca.");
    expect(matchesFaq(faq, "")).toBe(true);
    expect(matchesFaq(faq, "FAKTURA piątego")).toBe(true);
    expect(matchesFaq(faq, "faktura urlop")).toBe(false);
  });

  it("grupuje po tematach i pomija puste", () => {
    const topics = [
      { key: "invoice" as const, label: "Faktury" },
      { key: "leave" as const, label: "Urlop" },
      { key: "data" as const, label: "Dane" },
    ];
    const groups = groupFaq(
      [item(1, "invoice", "Faktura"), item(2, "leave", "Urlop")],
      topics,
      "urlop",
    );
    expect(groups.map((group) => group.key)).toEqual(["leave"]);
  });

  it("pokazuje termin w strefie firmy", () => {
    const now = new Date("2026-11-02T08:00:00Z");
    expect(slotLabel("2026-11-02T14:00:00Z", now)).toBe("dziś 15:00");
    expect(slotLabel("2026-11-03T08:30:00Z", now)).toBe("jutro 09:30");
    expect(slotLabel("2026-11-05T08:30:00Z", now)).toContain("09:30");
  });

  it("pisze stawkę po polsku i nie zgaduje jej braku", () => {
    expect(rateLabel({ amount: "160.00", currency: "PLN", unit: "hourly" })).toBe("160,00 zł/h netto");
    expect(rateLabel({ amount: "900.50", currency: "EUR", unit: "daily" })).toBe("900,50 EUR/dzień netto");
    expect(rateLabel(null)).toBeNull();
  });

  it("opisuje termin dokumentu względem startu", () => {
    expect(offsetLabel(-1)).toBe("1 dzień roboczy przed startem");
    expect(offsetLabel(-3)).toBe("3 dni robocze przed startem");
    expect(offsetLabel(0)).toBe("w dniu startu");
    expect(offsetLabel(2)).toBe("2 dni robocze po starcie");
    expect(offsetLabel(null)).toBeNull();
  });

  it("nazywa miesiąc i krok konsultanta", () => {
    expect(monthLabel(2026, 10)).toBe("Październik 2026");
    expect(formatDay("2026-11-02")).toBe("02.11.2026");
    expect(formatDay(null)).toBe("—");
    const row = { action: "send_invoice" } as PortalMonth;
    expect(monthActionLabel(row)).toBe("Wyślij fakturę");
    expect(monthActionLabel({ action: null } as PortalMonth)).toBeNull();
  });
});
