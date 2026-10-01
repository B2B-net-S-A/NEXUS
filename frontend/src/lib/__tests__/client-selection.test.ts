import { describe, expect, it } from "vitest";

import {
  isClientPickerQueryKey,
  withCurrentClient,
} from "@/lib/client-selection";

describe("withCurrentClient", () => {
  const selectable = [
    { id: 1, name: "Aktywny" },
    { id: 2, name: "Relacyjny" },
  ];

  it("dokłada bieżącego klienta, którego filtr pominął (nieaktywny)", () => {
    expect(withCurrentClient(selectable, "7", "Nieaktywny SA")).toEqual([
      { id: 7, name: "Nieaktywny SA" },
      ...selectable,
    ]);
  });

  it("nie dubluje klienta, który już jest na liście", () => {
    expect(withCurrentClient(selectable, 2, "Relacyjny")).toEqual(selectable);
  });

  it("bez bieżącego klienta zwraca samą listę", () => {
    expect(withCurrentClient(selectable, "", null)).toEqual(selectable);
    expect(withCurrentClient(selectable, null, null)).toEqual(selectable);
  });

  it("bez nazwy pokazuje numer zamiast pustej pozycji", () => {
    expect(withCurrentClient([], 9, "  ")).toEqual([
      { id: 9, name: "Klient #9" },
    ]);
  });
});

describe("isClientPickerQueryKey", () => {
  it("rozpoznaje listy wyboru klienta", () => {
    expect(isClientPickerQueryKey(["clients-lookup-new-job"])).toBe(true);
    expect(
      isClientPickerQueryKey(["clients-lookup-job-edit", "contract-eligible"]),
    ).toBe(true);
    expect(isClientPickerQueryKey(["contract-reassign-clients"])).toBe(true);
  });

  it("nie rusza katalogu klientów ani innych zapytań", () => {
    expect(isClientPickerQueryKey(["clients-directory"])).toBe(false);
    expect(isClientPickerQueryKey([42])).toBe(false);
  });
});
