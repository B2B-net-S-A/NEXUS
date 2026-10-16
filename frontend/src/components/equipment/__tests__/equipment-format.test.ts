import { describe, expect, it } from "vitest";

import type { EquipmentItem } from "@/lib/api/equipment";

import {
  canIssue,
  dueLabel,
  formatDatePl,
  formatPln,
  issueBlocker,
  issueTotal,
  itemIdentifier,
  itemNumber,
  lineValue,
  phoneDisplay,
  signatureMailHref,
  type IssueDraftLine,
} from "../equipment-format";

function item(overrides: Partial<EquipmentItem> = {}): EquipmentItem {
  return {
    id: 1,
    model: {
      id: 1,
      category: "laptop",
      name: "Dell Vostro 3530",
      manufacturer: null,
      price_pln: "2589.00",
      is_active: true,
    },
    category: "laptop",
    inventory_number: "221",
    serial_number: "TEST0001",
    imei: null,
    iccid: null,
    phone_number: null,
    access_card_number: null,
    status: "na_stanie",
    ownership: "nasz",
    purchase_date: null,
    location: null,
    notes: null,
    holder: null,
    issue_protocol: null,
    ...overrides,
  };
}

function line(entry: EquipmentItem, value = "", accessories = ""): IssueDraftLine {
  return { item: entry, value, accessories };
}

describe("wartości w protokole wydania", () => {
  it("bierze cenę z cennika, a ręczna zmiana dotyczy tylko tej pozycji", () => {
    expect(lineValue(line(item()))).toBe(2589);
    expect(lineValue(line(item(), "2500,50"))).toBe(2500.5);
    expect(lineValue(line(item(), "-5"))).toBeNull();
  });

  it("karta SIM i karta dostępu są bez wartości nawet z ceną w modelu (D6)", () => {
    const sim = item({
      category: "karta_sim",
      model: { ...item().model, category: "karta_sim", price_pln: "50.00" },
    });
    expect(lineValue(line(sim, "99"))).toBeNull();
    expect(issueTotal([line(item()), line(sim, "99")])).toBe(2589);
  });

  it("sumuje w groszach (bez błędu zmiennoprzecinkowego)", () => {
    const cheap = item({ model: { ...item().model, price_pln: "0.10" } });
    const other = item({ id: 2, model: { ...item().model, price_pln: "0.20" } });
    expect(issueTotal([line(cheap), line(other)])).toBe(0.3);
    expect(issueTotal([])).toBe(0);
  });
});

describe("czy pozycję można wydać", () => {
  it("tylko na stanie i bez posiadacza", () => {
    expect(canIssue(item())).toBe(true);
    expect(canIssue(item({ status: "serwis" }))).toBe(false);
    expect(issueBlocker(item({ status: "serwis" }))).toBe("Stan: W serwisie");
    expect(
      issueBlocker(item({ status: "wydany", holder: { kind: "user", id: 3, name: "Anna Przykładowa" } })),
    ).toBe("Wydana: Anna Przykładowa");
  });
});

describe("numery pozycji", () => {
  it("SIM pokazuje numer telefonu, telefon IMEI, karta numer karty", () => {
    expect(itemIdentifier(item({ category: "karta_sim", phone_number: "500000077" }))).toBe(
      "+48 500 000 077",
    );
    expect(itemIdentifier(item({ category: "telefon", imei: "350000000000011" }))).toBe(
      "IMEI 350000000000011",
    );
    expect(itemIdentifier(item({ category: "karta_dostepu", access_card_number: "1611" }))).toBe(
      "1611",
    );
    expect(itemNumber(item({ inventory_number: null, category: "karta_sim" }))).toBe("SIM");
    expect(phoneDisplay("12345")).toBe("12345");
  });
});

describe("teksty", () => {
  it("kwoty i daty po polsku", () => {
    expect(formatPln("3903.73")).toBe("3\u00a0903,73\u00a0zł");
    expect(formatPln(1234567.5)).toBe("1\u00a0234\u00a0567,50\u00a0zł");
    expect(formatPln("0")).toBe("0,00\u00a0zł");
    expect(formatPln(null)).toBe("bez wartości");
    expect(formatDatePl("2026-10-28")).toBe("28.10.2026");
    expect(formatDatePl("2026-10-28T10:00:00+02:00")).toBe("28.10.2026");
    expect(formatDatePl(null)).toBe("—");
  });

  it("termin zadania mówi o opóźnieniu", () => {
    expect(dueLabel("2026-11-02", 0)).toBe("do 02.11.2026");
    expect(dueLabel("2026-11-02", 1)).toBe("po terminie 1 dzień (02.11.2026)");
    expect(dueLabel("2026-11-02", 6)).toBe("po terminie 6 dni (02.11.2026)");
    expect(dueLabel(null, 0)).toBe("bez terminu");
  });

  it("wiadomość z linkiem trafia do poczty recepcji, nie jest wysyłana przez NEXUS", () => {
    const href = signatureMailHref(
      "anna@example.com",
      "PZO/2026/10/014",
      "https://nexus.example.com/protocol/abc",
    );
    expect(href.startsWith("mailto:anna%40example.com?subject=")).toBe(true);
    expect(decodeURIComponent(href)).toContain("https://nexus.example.com/protocol/abc");
    expect(decodeURIComponent(href)).toContain("ważny 14 dni");
  });
});
