import { describe, expect, it } from "vitest";

import { formatLukiDue, lukiLeft, type PoligonStatus } from "../logic";

const base: PoligonStatus = { open: true, required: false, done_ids: [], done: 15, total: 19 };

describe("poligon z lukami", () => {
  it("termin po polsku z dniem tygodnia", () => {
    expect(formatLukiDue("2026-11-23")).toBe("pn 23.11");
    expect(formatLukiDue("2026-11-21")).toBe("sb 21.11");
  });

  it("licznik luk tylko w kampanii i nigdy poniżej zera", () => {
    expect(lukiLeft(base)).toBe(0);
    expect(lukiLeft({ ...base, luki: { due: "2026-11-23", credited_ids: [] } })).toBe(4);
    expect(lukiLeft({ ...base, done: 19, luki: { due: "2026-11-23", credited_ids: [] } })).toBe(0);
    expect(lukiLeft(null)).toBe(0);
  });
});
