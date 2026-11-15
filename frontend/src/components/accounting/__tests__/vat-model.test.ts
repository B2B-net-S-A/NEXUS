import { describe, expect, it } from "vitest";

import { dueLabel, fieldsLabel, issueLink, rowGroups, taxIdLabel } from "@/components/accounting/vat-model";

describe("rejestry VAT — etykiety (K5a)", () => {
  it("pola JPK grupy", () => {
    expect(fieldsLabel({ net_field: "K_19", vat_field: "K_20", also: null })).toBe("K_19 / K_20");
    expect(fieldsLabel({ net_field: "K_11", vat_field: null, also: "K_12" })).toBe("K_11 (w tym K_12)");
  });

  it("grupy wiersza i wiersz bez podziału", () => {
    expect(rowGroups({ groups: [{ key: "23", net: 1, vat: 1 }, { key: "zw", net: 1, vat: 0 }], problem: null })).toBe("23%, zw");
    expect(rowGroups({ groups: [], problem: "stawka spoza słownika JPK: oo" })).toBe("do sprawdzenia");
  });

  it("saldo: do zapłaty albo nadwyżka", () => {
    expect(dueLabel(12_345)).toEqual({ label: "Do zapłaty", value: "123,45 zł" });
    expect(dueLabel(-232_300)).toEqual({ label: "Nadwyżka naliczonego", value: "2 323,00 zł" });
  });

  it("NIP i VAT UE", () => {
    expect(taxIdLabel({ tax_id: "5250000000", country: "PL" })).toBe("5250000000");
    expect(taxIdLabel({ tax_id: "FI12345678", country: "FI" })).toBe("FI12345678");
    expect(taxIdLabel({ tax_id: null, country: null })).toBe("bez NIP");
  });

  it("gdzie naprawić pozycję listy", () => {
    expect(issueLink("drafts", 2026, 3)).toEqual({ href: "/accounting/documents?year=2026&month=3&status=draft", label: "Bufor" });
    expect(issueLink("missing_sales", 2026, 3).href).toBe("/accounting/sources?year=2026&month=3");
    expect(issueLink("outside", 2026, 3).label).toBe("Dokumenty");
  });
});
