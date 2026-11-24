import { describe, expect, it } from "vitest";

import {
  clientsLabel,
  downloadStatusLabel,
  filesLabel,
  newFilesCount,
  newFilesLabel,
  orderPdfEntryTypeLabel,
  orderPdfKey,
  orderPdfMonthLabel,
  orderPdfPeriod,
  orderPdfPeriodInvalid,
  orderPdfStatusLabel,
  zipFallbackName,
} from "@/lib/finance-order-pdfs";

describe("orderPdfMonthLabel", () => {
  it("grudzień i styczeń", () => {
    expect(orderPdfMonthLabel("2026-12")).toBe("Grudzień 2026");
    expect(orderPdfMonthLabel("2027-01")).toBe("Styczeń 2027");
  });
  it("niepoprawny miesiąc wraca bez zmian", () => {
    expect(orderPdfMonthLabel("2026-13")).toBe("2026-13");
    expect(orderPdfMonthLabel("")).toBe("");
  });
});

describe("okres pliku", () => {
  it("flaga z serwera wygrywa nawet przy poprawnych datach", () => {
    const file = { start: "2026-01-01", end: "2026-12-31", period_invalid: true };
    expect(orderPdfPeriodInvalid(file)).toBe(true);
    expect(orderPdfPeriod(file)).toBe(
      "Okres do sprawdzenia: koniec 31.12.2026 przed startem 01.01.2026",
    );
  });

  it("koniec przed startem bez flagi: do sprawdzenia", () => {
    const file = { start: "2027-01-01", end: "2026-12-31" };
    expect(orderPdfPeriodInvalid(file)).toBe(true);
    expect(orderPdfPeriod(file)).toMatch(/^Okres do sprawdzenia: koniec 31\.12\.2026/);
  });

  it("koniec równy startowi (jeden dzień) jest poprawny, także z czasem", () => {
    const file = { start: "2026-12-31T00:00:00", end: "2026-12-31T23:00:00" };
    expect(orderPdfPeriodInvalid(file)).toBe(false);
    expect(orderPdfPeriod(file)).toBe("31.12.2026–31.12.2026");
  });

  it("bez końca: bezterminowo", () => {
    const file = { start: "2026-12-31", end: null };
    expect(orderPdfPeriodInvalid(file)).toBe(false);
    expect(orderPdfPeriod(file)).toBe("31.12.2026–bezterminowo");
  });
});

describe("etykiety", () => {
  it("rodzaj wpisu", () => {
    expect(orderPdfEntryTypeLabel("new")).toBe("Nowe zamówienie");
    expect(orderPdfEntryTypeLabel("extension")).toBe("Przedłużenie");
    expect(orderPdfEntryTypeLabel("amendment")).toBe("Aneks");
  });
  it("status: brak → null, nieznany kod bez zmian, anulowane ma etykietę", () => {
    expect(orderPdfStatusLabel(null)).toBeNull();
    expect(orderPdfStatusLabel("")).toBeNull();
    expect(orderPdfStatusLabel("kod_spoza_slownika")).toBe("kod_spoza_slownika");
    expect(orderPdfStatusLabel("cancelled")).not.toBe("cancelled");
  });
  it("klucz pliku łączy rodzaj i id", () => {
    expect(orderPdfKey({ kind: "order_group" as never, id: 5 })).toBe("order_group:5");
  });
  it("filesLabel: 0, 1, 2, 5, 12, 22, 112", () => {
    expect(filesLabel(0)).toBe("0 plików");
    expect(filesLabel(1)).toBe("1 plik");
    expect(filesLabel(2)).toBe("2 pliki");
    expect(filesLabel(5)).toBe("5 plików");
    expect(filesLabel(12)).toBe("12 plików");
    expect(filesLabel(22)).toBe("22 pliki");
    expect(filesLabel(112)).toBe("112 plików");
  });
  it("clientsLabel", () => {
    expect(clientsLabel(1)).toBe("1 klient");
    expect(clientsLabel(0)).toBe("0 klientów");
  });
  it("newFilesLabel: 0, 1, 3, 12, 13, 24, 25", () => {
    expect(newFilesLabel(0)).toBe("0 nowych");
    expect(newFilesLabel(1)).toBe("1 nowy");
    expect(newFilesLabel(3)).toBe("3 nowe");
    expect(newFilesLabel(12)).toBe("12 nowych");
    expect(newFilesLabel(13)).toBe("13 nowych");
    expect(newFilesLabel(24)).toBe("24 nowe");
    expect(newFilesLabel(25)).toBe("25 nowych");
  });
});

describe("pobrania", () => {
  it("status pobrania: nowy przy null/undefined, data przy pobranym", () => {
    expect(downloadStatusLabel({ downloaded_at: null })).toBe("● Nowy");
    expect(downloadStatusLabel({})).toBe("● Nowy");
    expect(downloadStatusLabel({ downloaded_at: "2026-09-22T10:00:00Z" })).toBe(
      "Pobrane przez Ciebie 22.09.2026",
    );
  });
  it("newFilesCount: pusta lista i mieszana", () => {
    expect(newFilesCount([])).toBe(0);
    expect(
      newFilesCount([{ downloaded_at: null }, {}, { downloaded_at: "2026-09-22T10:00:00Z" }]),
    ).toBe(2);
  });
});

describe("zipFallbackName", () => {
  it("bez klienta", () => {
    expect(zipFallbackName(null, "2026-12")).toBe("Zamowienia_2026-12.zip");
    expect(zipFallbackName("", "2026-12")).toBe("Zamowienia_2026-12.zip");
  });
  it("polskie znaki, ł/Ł i znaki specjalne zamienione, brzegi obcięte", () => {
    expect(zipFallbackName("Łódzka Firma Testowa sp. z o.o.", "2027-01")).toBe(
      "Lodzka_Firma_Testowa_sp._z_o.o_2027-01.zip",
    );
    expect(zipFallbackName("  Żółć & Spółka!  ", "2026-12")).toBe("Zolc_Spolka_2026-12.zip");
  });
  it("nazwa bez liter i cyfr daje „klient”", () => {
    expect(zipFallbackName("&&& ***", "2026-12")).toBe("klient_2026-12.zip");
  });
});
