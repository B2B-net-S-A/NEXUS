import { describe, expect, it } from "vitest";

import { formatIsoDatePl } from "@/lib/date-pl";

describe("formatIsoDatePl", () => {
  it("składa DD.MM.RRRR z zerem wiodącym, bez przejścia przez UTC", () => {
    expect(formatIsoDatePl("2026-09-03")).toBe("03.09.2026");
    expect(formatIsoDatePl("2028-02-28")).toBe("28.02.2028");
  });

  it("brak wartości i śmieci dają kreskę", () => {
    expect(formatIsoDatePl(null)).toBe("—");
    expect(formatIsoDatePl(undefined)).toBe("—");
    expect(formatIsoDatePl("")).toBe("—");
    expect(formatIsoDatePl("nie-data")).toBe("—");
  });

  it("wartość z czasem idzie przez lokalną datę", () => {
    expect(formatIsoDatePl("2026-01-05T10:00:00")).toBe("05.01.2026");
  });
});
