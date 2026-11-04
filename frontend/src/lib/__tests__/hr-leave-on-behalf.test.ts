import { describe, expect, it } from "vitest";

import { enterablePeople } from "@/lib/api/hr-leave";

describe("wpis za pracownika na B2B/zleceniu (D5, decyzja 19.10.2026)", () => {
  it("okno pomija osoby z can_enter: false, stary kształt listy zostaje", () => {
    const rows = [
      { user_id: 1, name: "A", employment_type: "b2b" as const, department: null, can_enter: false },
      { user_id: 2, name: "B", employment_type: "uop" as const, department: null, can_enter: true },
      { user_id: 3, name: "C", employment_type: "uop" as const, department: null },
    ];
    expect(enterablePeople(rows).map((row) => row.user_id)).toEqual([2, 3]);
    expect(enterablePeople(undefined)).toEqual([]);
  });
});
