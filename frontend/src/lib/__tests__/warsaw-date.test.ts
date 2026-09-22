import { describe, expect, it } from "vitest";

import { warsawToday } from "@/lib/warsaw-date";
import { emptyAmendmentForm } from "@/components/ContractAmendmentsTab";

describe("warsawToday", () => {
  it("po północy w Warszawie daje już nowy dzień, choć w UTC jest jeszcze wczoraj", () => {
    // 22:30 UTC 21.09 = 00:30 CEST 22.09.
    expect(warsawToday(new Date("2026-09-21T22:30:00Z"))).toBe("2026-09-22");
  });

  it("zimą (CET, UTC+1) granica doby przesuwa się o godzinę", () => {
    expect(warsawToday(new Date("2026-12-31T22:59:00Z"))).toBe("2026-12-31");
    expect(warsawToday(new Date("2026-12-31T23:00:00Z"))).toBe("2027-01-01");
  });
});

describe("emptyAmendmentForm", () => {
  it("liczy datę wejścia w życie przy otwarciu formularza, nie przy imporcie modułu", () => {
    expect(emptyAmendmentForm("rate_change", "2026-10-01")).toMatchObject({
      amendment_type: "rate_change",
      effective_date: "2026-10-01",
      new_end_date: "",
    });
    expect(emptyAmendmentForm().effective_date).toBe(warsawToday());
  });
});
