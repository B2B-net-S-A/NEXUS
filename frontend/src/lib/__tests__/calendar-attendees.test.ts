import { describe, expect, it } from "vitest";

import { attendeeAddress, attendeeLabel } from "@/lib/calendar-attendees";

describe("attendeeLabel", () => {
  it("zostawia adres zapisany jako tekst", () => {
    expect(attendeeLabel("osoba@example.com")).toBe("osoba@example.com");
  });

  it("dla uczestnika z M365 pokazuje imię i nazwisko, a bez niego adres", () => {
    expect(attendeeLabel({ address: "osoba@example.com", name: "Jan Testowy" })).toBe("Jan Testowy");
    expect(attendeeLabel({ address: "osoba@example.com", name: null })).toBe("osoba@example.com");
    expect(attendeeLabel({ address: "osoba@example.com", name: "  " })).toBe("osoba@example.com");
  });

  it("pusty albo uszkodzony wpis nie daje etykiety zamiast wywracać widok", () => {
    expect(attendeeLabel("   ")).toBeNull();
    expect(attendeeLabel({})).toBeNull();
    expect(attendeeLabel(null)).toBeNull();
    expect(attendeeLabel(undefined)).toBeNull();
  });
});

describe("attendeeAddress", () => {
  it("zwraca adres z obu kształtów", () => {
    expect(attendeeAddress("osoba@example.com")).toBe("osoba@example.com");
    expect(attendeeAddress({ address: "osoba@example.com", name: "Jan Testowy" })).toBe("osoba@example.com");
    expect(attendeeAddress({ name: "Jan Testowy" })).toBeNull();
  });
});
