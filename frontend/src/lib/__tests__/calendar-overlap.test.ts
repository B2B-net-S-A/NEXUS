import { describe, expect, it } from "vitest";
import { layoutOverlappingEvents } from "../calendar-overlap";

describe("layoutOverlappingEvents", () => {
  it("wydarzenia o tej samej godzinie dostają osobne pasy zamiast leżeć na sobie", () => {
    const slots = layoutOverlappingEvents([
      { id: 1, start: 56, end: 112 },
      { id: 2, start: 56, end: 112 },
      { id: 3, start: 56, end: 84 },
    ]);
    expect(new Set([1, 2, 3].map((id) => slots.get(id)!.column))).toEqual(
      new Set([0, 1, 2]),
    );
    for (const id of [1, 2, 3]) expect(slots.get(id)!.columns).toBe(3);
  });

  it("wydarzenie bez nakładania zajmuje całą szerokość", () => {
    const slots = layoutOverlappingEvents([
      { id: "a", start: 0, end: 56 },
      { id: "b", start: 56, end: 112 },
    ]);
    expect(slots.get("a")).toEqual({ column: 0, columns: 1 });
    expect(slots.get("b")).toEqual({ column: 0, columns: 1 });
  });

  it("łańcuch nakładań dzieli pasy, a zwolniony pas jest używany ponownie", () => {
    // A 0–100, B 50–150, C 120–200: A i C się nie spotykają, więc C wraca do pasa A.
    const slots = layoutOverlappingEvents([
      { id: "A", start: 0, end: 100 },
      { id: "B", start: 50, end: 150 },
      { id: "C", start: 120, end: 200 },
    ]);
    expect(slots.get("A")).toEqual({ column: 0, columns: 2 });
    expect(slots.get("B")).toEqual({ column: 1, columns: 2 });
    expect(slots.get("C")).toEqual({ column: 0, columns: 2 });
  });
});
