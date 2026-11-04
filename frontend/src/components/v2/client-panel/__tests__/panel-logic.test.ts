import { afterEach, describe, expect, it, vi } from "vitest";

import {
  MAX_SLOTS,
  evidenceFallback,
  formatRate,
  formatSlotLabel,
  isBusinessDay,
  isValidEmail,
  loadAuthor,
  polishHolidays,
  saveAuthor,
  shortRequirementLabel,
  slotKeyLabel,
  SLOT_HOURS,
  slotWeeks,
  startEvidenceSearch,
  togglePicked,
  warsawLocalToIso,
} from "../panel-logic";

describe("dni robocze", () => {
  it("ruchome święta 2026 i Wigilia są wolne, zwykła środa nie", () => {
    const holidays = polishHolidays(2026);
    expect(holidays.has("2026-04-06")).toBe(true); // Poniedziałek Wielkanocny
    expect(holidays.has("2026-06-04")).toBe(true); // Boże Ciało
    expect(holidays.has("2026-12-24")).toBe(true);
    expect(isBusinessDay("2026-11-11")).toBe(false);
    expect(isBusinessDay("2026-11-07")).toBe(false); // sobota
    expect(isBusinessDay("2026-11-12")).toBe(true);
  });

  it("Wigilia przed 2025 nie jest świętem", () => {
    expect(polishHolidays(2024).has("2024-12-24")).toBe(false);
  });
});

describe("siatka terminów", () => {
  it("zaczyna od dziś, święto jest niewybieralne, koniec po 14 dniach", () => {
    const weeks = slotWeeks("2026-11-02", "08:30"); // poniedziałek
    expect(weeks.map((week) => week.monday)).toEqual(["2026-11-02", "2026-11-09", "2026-11-16"]);
    const first = weeks[0].days;
    expect(first[0]).toMatchObject({ ymd: "2026-11-02", selectable: true });
    expect(first[1]).toMatchObject({ ymd: "2026-11-03", selectable: true });
    const holiday = weeks[1].days.find((day) => day.ymd === "2026-11-11");
    expect(holiday).toMatchObject({ selectable: false, holiday: true, label: "Śr 11.11" });
    expect(weeks[1].label).toBe("9–13 listopada");
    const last = weeks[2].days;
    expect(last[0]).toMatchObject({ ymd: "2026-11-16", selectable: true });
    expect(last[1]).toMatchObject({ ymd: "2026-11-17", selectable: false });
  });

  it("dziś można wybrać tylko godziny, które się jeszcze nie zaczęły", () => {
    const days = slotWeeks("2026-11-04", "15:51")[0].days; // środa
    expect(days[1]).toMatchObject({ ymd: "2026-11-03", selectable: false, hours: [] });
    expect(days[2]).toMatchObject({ ymd: "2026-11-04", selectable: true, hours: ["16:00"] });
    expect(days[3].hours).toEqual(SLOT_HOURS);
  });

  it("o pełnej godzinie ta godzina już się zaczęła", () => {
    expect(slotWeeks("2026-11-04", "15:00")[0].days[2].hours).toEqual(["16:00"]);
  });

  it("po ostatniej godzinie dziś nie ma czego wybrać, ale jutro zostaje", () => {
    const days = slotWeeks("2026-11-04", "16:00")[0].days;
    expect(days[2]).toMatchObject({ selectable: false, hours: [], holiday: false });
    expect(days[3].selectable).toBe(true);
  });

  it("święto dziś nie ma godzin", () => {
    const today = slotWeeks("2026-11-11", "08:30")[0].days[2];
    expect(today).toMatchObject({ selectable: false, holiday: true, hours: [] });
  });

  it("w piątek rano bieżący tydzień zostaje, po ostatniej godzinie znika", () => {
    expect(slotWeeks("2026-11-06", "10:00")[0].monday).toBe("2026-11-02");
    expect(slotWeeks("2026-11-06", "16:30")[0].monday).toBe("2026-11-09");
  });

  it("w niedzielę siatka zaczyna się od poniedziałku", () => {
    expect(slotWeeks("2026-11-08", "10:00")[0].monday).toBe("2026-11-09");
  });

  it("tydzień na przełomie miesięcy ma dwie nazwy miesiąca", () => {
    expect(slotWeeks("2026-11-27", "17:00")[0].label).toBe("30 listopada – 4 grudnia");
  });

  it("wybór: klik zdejmuje, siódmy termin nie wchodzi, lista posortowana", () => {
    const keys = ["14", "10", "11", "12", "13", "15"].map((d) => `2026-11-${d}T10:00`);
    const six = keys.reduce<string[]>((acc, key) => togglePicked(acc, key), []);
    expect(six).toHaveLength(MAX_SLOTS);
    expect(six[0]).toBe("2026-11-10T10:00");
    expect(togglePicked(six, "2026-11-16T10:00")).toEqual(six);
    expect(togglePicked(six, "2026-11-10T10:00")).toHaveLength(MAX_SLOTS - 1);
  });
});

describe("czas Europe/Warsaw", () => {
  it("zimą +01:00, latem +02:00, niezależnie od strefy przeglądarki", () => {
    expect(warsawLocalToIso("2026-11-10T10:00")).toBe("2026-11-10T10:00:00+01:00");
    expect(warsawLocalToIso("2026-07-10T09:00")).toBe("2026-07-10T09:00:00+02:00");
  });

  it("tuż po zmianie czasu przesunięcie jest już nowe", () => {
    expect(warsawLocalToIso("2026-10-25T09:00")).toBe("2026-10-25T09:00:00+01:00");
    expect(warsawLocalToIso("2027-03-28T09:00")).toBe("2027-03-28T09:00:00+02:00");
  });

  it("etykieta terminu pokazuje czas warszawski, także okno klienta", () => {
    expect(slotKeyLabel("2026-11-10T10:00")).toBe("Wt 10.11, 10:00");
    expect(formatSlotLabel("2026-11-10T09:00:00Z")).toBe("Wt 10.11, 10:00");
    expect(formatSlotLabel("2026-11-10T08:00:00Z", "2026-11-10T11:00:00Z")).toBe(
      "Wt 10.11, 09:00–12:00",
    );
    expect(formatSlotLabel("nie-data")).toBe("—");
  });
});

describe("drobne etykiety", () => {
  it("stawka bez wartości nie udaje liczby", () => {
    expect(formatRate({ value: "168.75", unit: "hourly", currency: "PLN" })).toBe("168,75 zł/h");
    expect(formatRate({ value: "1200", unit: "daily", currency: "EUR" })).toMatch(/^1\s?200 EUR\/MD$/);
    expect(formatRate({ value: "brak", unit: "hourly", currency: "PLN" })).toBeNull();
    expect(formatRate(null)).toBeNull();
  });

  it("e-mail: kształt adresu, bez spacji i bez domeny jednoczłonowej", () => {
    expect(isValidEmail(" jan@bank-przykladowy.example ")).toBe(true);
    expect(isValidEmail("jan@bank")).toBe(false);
    expect(isValidEmail("jan kowal@bank.pl")).toBe(false);
    expect(isValidEmail("")).toBe(false);
  });

  it("krótka nazwa kolumny pomija słowa ogólne i liczby", () => {
    expect(shortRequirementLabel("Python, 6+ lat")).toBe("Python");
    expect(shortRequirementLabel("Technika DDD")).toBe("DDD");
    expect(shortRequirementLabel("Implementacja mikrousług")).toBe("Mikrous.");
    expect(shortRequirementLabel("Git lub podobny")).toBe("Git");
  });
});

describe("szukanie dowodu w PDF-ie", () => {
  const item = { kind: "project", quote: "fraza z CV", term: "DDD", where: null, dates: null } as const;

  it("druga próba tylko po zakończonym szukaniu frazy bez trafień", () => {
    const search = startEvidenceSearch(item);
    expect(evidenceFallback(search, { total: 0, pending: true })).toBeNull();
    expect(evidenceFallback(search, { total: 2, pending: false })).toBeNull();
    expect(evidenceFallback(search, { total: 0, pending: false })).toBe("DDD");
  });

  it("słowo bez trafień nie zapętla szukania", () => {
    const search = { ...startEvidenceSearch(item), stage: "term" as const };
    expect(evidenceFallback(search, { total: 0, pending: false })).toBeNull();
    expect(evidenceFallback(null, { total: 0, pending: false })).toBeNull();
  });
});

describe("pamięć autora", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("zapamiętuje imię i e-mail w tej przeglądarce", () => {
    saveAuthor({ name: "Kasia", email: "kasia@example.test" });
    expect(loadAuthor()).toEqual({ name: "Kasia", email: "kasia@example.test" });
  });

  it("zablokowana pamięć przeglądarki nie wywraca formularza", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("zablokowane");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("zablokowane");
    });
    expect(loadAuthor()).toEqual({ name: "", email: "" });
    expect(() => saveAuthor({ name: "Kasia", email: "k@example.test" })).not.toThrow();
  });

  it("uszkodzony zapis daje pusty formularz", () => {
    window.localStorage.setItem("nexus.client-panel.author", "{nie-json");
    expect(loadAuthor()).toEqual({ name: "", email: "" });
  });
});
