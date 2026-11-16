import { describe, expect, it } from "vitest";

import {
  dueLabel,
  fieldsLabel,
  issueLink,
  jpkBlockers,
  markersLabel,
  netValid,
  receivedBeforeIssue,
  sentJpkMonth,
  rowGroups,
  supplierGroup,
  taxIdLabel,
} from "@/components/accounting/vat-model";

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

  it("blokady JPK z listy „do sprawdzenia”", () => {
    expect(
      jpkBlockers([
        { kind: "missing_sales", label: "Faktury sprzedaży z KSeF bez dokumentu w księdze", count: 7, items: [] },
        { kind: "outside", label: "Zapisy na kontach VAT spoza rejestru", count: 1, items: [] },
        { kind: "drafts", label: "FVS i FVZ w buforze — rejestr liczy tylko zatwierdzone", count: 2, items: [] },
      ]),
    ).toEqual(["faktury sprzedaży z ksef bez dokumentu w księdze: 7", "fvs i fvz w buforze: 2"]);
  });
});

describe("zakup zagraniczny i znaczniki (K5b-2)", () => {
  it("grupa JPK nowego dostawcy: z UE z numerem VAT = art. 28b", () => {
    expect(supplierGroup("ie", "1234567T")).toBe("imp_28b");
    expect(supplierGroup("IE", "")).toBe("imp_other");
    expect(supplierGroup("US", "123456789")).toBe("imp_other");
    expect(supplierGroup("GB", "GB123456789")).toBe("imp_other");
  });

  it("netto: przecinek, spacje, korekta in minus, bez zera i trzech miejsc", () => {
    expect(["1 234,56", "100", "-15.5", "0.01"].map(netValid)).toEqual([true, true, true, true]);
    expect(["0", "0,00", "10.005", "abc", "", "1e3"].map(netValid)).toEqual([false, false, false, false, false, false]);
  });

  it("wiersz rejestru: import usług i znaczniki", () => {
    expect(rowGroups({ groups: [{ key: "imp_28b", net: 1, vat: 1 }], problem: null })).toBe("import usług UE");
    expect(markersLabel(["GTU_12", "TP"])).toBe("GTU_12, TP");
    expect(markersLabel([])).toBe("bez znaczników");
  });
});

describe("faktura zagraniczna otrzymana później (art. 86 ust. 10b pkt 3)", () => {
  it("miesiąc usługi z wysłanym JPK = korekta tamtego miesiąca, bez terminu 3 miesięcy", () => {
    const sent = ["2026-07", "2026-10"];
    // Usługa w lipcu, faktura w listopadzie (ponad 3 miesiące) — dalej lipiec.
    expect(sentJpkMonth("2026-07-31", sent)).toBe("07.2026");
    expect(sentJpkMonth("2026-10-01", sent)).toBe("10.2026");
    expect(sentJpkMonth("2026-11-03", sent)).toBeNull();
    expect(sentJpkMonth("2026-06-30", sent)).toBeNull();
    expect(sentJpkMonth("", sent)).toBeNull();
    expect(sentJpkMonth("2026-07-31", [])).toBeNull();
  });

  it("otrzymanie przed wystawieniem jest błędem, puste pola nie", () => {
    expect(receivedBeforeIssue("2026-11-03", "2026-11-02")).toBe(true);
    expect(receivedBeforeIssue("2026-11-03", "2026-11-03")).toBe(false);
    expect(receivedBeforeIssue("2026-11-03", "2027-01-15")).toBe(false);
    expect(receivedBeforeIssue("", "2026-11-02")).toBe(false);
    expect(receivedBeforeIssue("2026-11-03", "")).toBe(false);
  });
});
