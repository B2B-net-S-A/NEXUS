import { describe, expect, it } from "vitest";

import { m365ReasonLabel, m365StatusView } from "@/lib/api/hr-m365";

describe("hr-m365 labels", () => {
  it("translates error categories and keeps the HTTP code", () => {
    expect(m365ReasonLabel("forbidden (403)")).toBe("Brak uprawnień aplikacji w Exchange (403)");
    expect(m365ReasonLabel("user_custom")).toBe("Osoba ma własną autoodpowiedź");
    expect(m365ReasonLabel("waiting_for_window")).toBe("Czeka na pierwszy dzień urlopu");
    expect(m365ReasonLabel(null)).toBeNull();
    // Nieznany kod zostaje widoczny, zamiast zniknąć.
    expect(m365ReasonLabel("nowy_powod")).toBe("nowy_powod");
  });

  it("tells waiting operations from queued ones", () => {
    expect(m365StatusView({ status: "pending", deferred: true })).toEqual({ label: "Czeka", tone: "neutral" });
    expect(m365StatusView({ status: "pending", deferred: false }).label).toBe("W kolejce");
    expect(m365StatusView({ status: "failed", deferred: false }).tone).toBe("danger");
    expect(m365StatusView({ status: "simulated", deferred: false }).label).toBe("Zasymulowano");
  });
});
