import { describe, expect, it } from "vitest";

import { bulkDismissMessage, dismissBulkRequestBody } from "@/lib/proposal-dismiss";

describe("dismissBulkRequestBody — „Pomiń zaznaczone”", () => {
  it("jeden powód dla wszystkich, pusty opis nie jedzie wcale", () => {
    expect(dismissBulkRequestBody([3, 4], { reason: "too_expensive", note: "  " })).toEqual({
      candidate_ids: [3, 4],
      reason: "too_expensive",
    });
    expect(dismissBulkRequestBody([5], { reason: "other", note: " klient nie chce " })).toEqual({
      candidate_ids: [5],
      reason: "other",
      note: "klient nie chce",
    });
  });
});

describe("bulkDismissMessage — komunikat po „Pomiń zaznaczone”", () => {
  it.each([
    [1, 0, "Pominięto 1 osobę. Wrócą tylko z nową wersją CV."],
    [3, 0, "Pominięto 3 osoby. Wrócą tylko z nową wersją CV."],
    [5, 0, "Pominięto 5 osób. Wrócą tylko z nową wersją CV."],
    [2, 1, "Pominięto 2 osoby · 1 bez zmian. Wrócą tylko z nową wersją CV."],
    [0, 2, "Nikogo nie pominięto · 2 bez zmian."],
  ])("%i pominiętych, %i bez zmian → %s", (dismissed, skipped, text) => {
    expect(bulkDismissMessage(dismissed, skipped)).toBe(text);
  });
});
