import { describe, expect, it } from "vitest";

import type { ApprovalRequestRow, ApprovalSettlement } from "@/lib/api/hr-approvals";

import {
  comparisonLabel,
  expiryHint,
  settlementLine,
  settlementNeedsAuthor,
  settlementPill,
} from "../settlement-format";

const settlement = (overrides: Partial<ApprovalSettlement> = {}): ApprovalSettlement => ({
  status: "open",
  status_label: "czeka na fakturę",
  expires_on: "2026-11-19",
  renews_on: null,
  renewal_asked_for: null,
  renewal_confirmed_for: null,
  ended_on: null,
  settled_at: null,
  settled_by_name: null,
  seller_nip: null,
  client_id: null,
  client_name: null,
  tolerance_percent: 10,
  comparison: null,
  documents: [],
  can_add_document: true,
  can_answer_renewal: false,
  can_end: false,
  ...overrides,
});

const row = (s: ApprovalSettlement | null, kind: ApprovalRequestRow["kind"] = "training") =>
  ({ kind, recurrence: "once", settlement: s }) as ApprovalRequestRow;

describe("rozliczenie zgody — słowa", () => {
  it("porównanie: mieści się, ponad próg z procentem, do sprawdzenia", () => {
    const base = { approved: "1000", documented: "1000", limit: "1100", excess: null, percent: null };
    expect(comparisonLabel({ ...base, status: "fits" })).toBe("mieści się");
    expect(comparisonLabel({ ...base, status: "over", percent: 18 })).toBe("+18% vs zgoda");
    expect(comparisonLabel({ ...base, status: "unknown" })).toBe("do sprawdzenia");
  });

  it("otwarta zgoda mówi o terminie i KSeF; wygasła — o nowej zgodzie", () => {
    expect(settlementLine(row(settlement()), settlement())).toMatch(/do 19\.11\.2026.*KSeF/);
    const expired = settlement({ status: "expired", status_label: "wygasła" });
    expect(settlementLine(row(expired), expired)).toMatch(/poproś o nową/);
  });

  it("zgoda „raz” nie wygasa, cykliczna — po 30 dniach bez dokumentu (decyzja 22.10.2026)", () => {
    expect(expiryHint({ recurrence: "once" })).toEqual([
      "Zgoda nie wygasa",
      " — rachunek dołączysz także po wyjeździe czy szkoleniu.",
    ]);
    expect(expiryHint({ recurrence: "monthly" })[0]).toBe("Zgoda wygasa po 30 dniach");
    expect(expiryHint({ recurrence: "yearly" })[1]).toMatch(/jeśli nic nie dołączysz/);
  });

  it("autor ma coś do zrobienia: brak faktury, dopłata do poproszenia, pytanie o odnowienie", () => {
    expect(settlementNeedsAuthor(row(settlement()))).toBe(true);
    expect(settlementPill(row(settlement()))).toBe("dołącz fakturę");
    const documented = settlement({ status: "documented", status_label: "do rozliczenia" });
    expect(settlementNeedsAuthor(row(documented))).toBe(false);
    expect(settlementPill(row(documented))).toBe("do rozliczenia");
    const renewal = settlement({
      status: "active",
      status_label: "w rejestrze",
      renews_on: "2026-11-15",
      renewal_asked_for: "2026-11-15",
      can_answer_renewal: true,
    });
    expect(settlementNeedsAuthor(row(renewal, "subscription"))).toBe(true);
    expect(
      settlementNeedsAuthor(row({ ...renewal, renewal_confirmed_for: "2026-11-15" }, "subscription")),
    ).toBe(false);
    expect(settlementNeedsAuthor(row(null))).toBe(false);
  });
});
