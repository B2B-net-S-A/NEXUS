import { describe, expect, it } from "vitest";

import type { OrderMailProposalRow } from "@/lib/api/orderMail";
import { applyButtonLabel, effectiveOverlapChoices, previousRateNote } from "@/lib/order-mail-overlap";

function row(over: Partial<OrderMailProposalRow> = {}): OrderMailProposalRow {
  return {
    row_index: 0, row_name: "Jan Kowalski", action: "future", candidate_id: 1, contract_id: 2,
    target_order_id: null, title: "10/2031", start_date: "2031-12-01", end_date: "2032-05-01",
    rate_client: "138.00", rate_unit: "hour", md_total: null, reasons: [],
    ...over,
  };
}

describe("previousRateNote", () => {
  it("shows the previous order and the change when the renewal changes the rate", () => {
    expect(previousRateNote(row({ previous_order_id: 70, previous_rate_client: "120", previous_rate_unit: "hour" }), "PLN"))
      .toEqual({ text: "było 120 zł/h (#70)", change: "+15%" });
    expect(previousRateNote(row({ rate_client: "108", previous_order_id: 70, previous_rate_client: "120", previous_rate_unit: "hour" }))?.change)
      .toBe("−10%");
  });

  it("stays silent for the same rate, a first order and incomparable units", () => {
    expect(previousRateNote(row({ previous_order_id: 70, previous_rate_client: "138", previous_rate_unit: "hour" }))).toBeNull();
    expect(previousRateNote(row())).toBeNull();
    expect(previousRateNote(row({ previous_order_id: 70, previous_rate_client: "24000", previous_rate_unit: "month" }))).toBeNull();
  });

  it("compares MD with hours (MD = 8 h)", () => {
    expect(previousRateNote(row({ previous_order_id: 70, previous_rate_client: "1104", previous_rate_unit: "day" }))).toBeNull();
  });
});

describe("overlap choices", () => {
  const overlap = row({
    action: "overlap", target_order_id: 70, overlap_options: ["trim_previous", "start_after"],
    overlap_trim_end: "2031-11-30", overlap_start_after: "2032-01-01", previous_end_date: "2031-12-31",
  });

  it("defaults to the first option and drops a choice the new plan no longer offers", () => {
    expect(effectiveOverlapChoices([overlap], {})).toEqual({ 0: "trim_previous" });
    expect(effectiveOverlapChoices([overlap], { 0: "start_after" })).toEqual({ 0: "start_after" });
    const trimOnly = { ...overlap, overlap_options: ["trim_previous" as const] };
    expect(effectiveOverlapChoices([trimOnly], { 0: "start_after" })).toEqual({ 0: "trim_previous" });
  });

  it("ignores overlap rows without options (decided in the order window)", () => {
    expect(effectiveOverlapChoices([{ ...overlap, overlap_options: [] }], {})).toEqual({});
    expect(applyButtonLabel([{ ...overlap, overlap_options: [] }], {})).toBe("Zastosuj");
  });

  it("names what happens to the previous order on the button", () => {
    expect(applyButtonLabel([overlap], { 0: "trim_previous" })).toBe("Zastosuj: skróć #70 i zapisz 10/2031");
    expect(applyButtonLabel([overlap], { 0: "start_after" })).toBe("Zastosuj: zapisz 10/2031 od 01.01.2032");
    expect(applyButtonLabel([row()], {})).toBe("Zastosuj");
  });
});
