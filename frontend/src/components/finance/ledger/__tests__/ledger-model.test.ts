import { describe, expect, it } from "vitest";

import {
  bulkLabel,
  describeResult,
  keepVisible,
  recentMonths,
  stageButtons,
  toggleAll,
} from "@/components/finance/ledger/ledger-model";

describe("stageButtons", () => {
  it("poczekalnia: Odrzuć z powodem i Przyjmij jako główna", () => {
    const buttons = stageButtons("received");
    expect(buttons.map((b) => b.action)).toEqual(["reject", "accept"]);
    expect(buttons[0].needsReason).toBe(true);
    expect(buttons[1].primary).toBe(true);
  });

  it("dokument spoza KSeF nie wraca do poczekalni", () => {
    expect(stageButtons("new", true).map((b) => b.action)).toEqual(["back", "reject", "verify"]);
    expect(stageButtons("new", false).map((b) => b.action)).toEqual(["reject", "verify"]);
  });

  it("dalej o krok naprzód albo wstecz, zaksięgowana bez akcji", () => {
    expect(stageButtons("verified").map((b) => b.action)).toEqual(["back", "ready"]);
    expect(stageButtons("ready").map((b) => b.action)).toEqual(["back"]);
    expect(stageButtons("rejected").map((b) => b.label)).toEqual(["Przywróć"]);
    expect(stageButtons("booked")).toEqual([]);
  });

  it("etykieta zbiorcza z liczbą", () => {
    expect(bulkLabel(stageButtons("new")[2], 3)).toBe("Zweryfikuj zaznaczone (3)");
  });
});

describe("describeResult", () => {
  it("wszystko przeszło", () => {
    expect(describeResult({ changed: 2, refused: [] })).toEqual({
      text: "Zmieniono: 2 faktury.",
      tone: "success",
    });
  });

  it("część odmówiona — powody bez powtórzeń", () => {
    const result = describeResult({
      changed: 1,
      refused: [
        { id: 4, detail: "To Twoja faktura.", status: 403 },
        { id: 5, detail: "To Twoja faktura.", status: 403 },
      ],
    });
    expect(result.tone).toBe("info");
    expect(result.text).toBe("Zmieniono: 1 faktura. Bez zmiany: 2 faktury — To Twoja faktura.");
  });
});

describe("zaznaczanie", () => {
  it("wszystkie widoczne albo nic", () => {
    expect(Array.from(toggleAll(new Set(), [1, 2]))).toEqual([1, 2]);
    expect(Array.from(toggleAll(new Set([1, 2]), [1, 2]))).toEqual([]);
    expect(Array.from(toggleAll(new Set([1]), [1, 2]))).toEqual([1, 2]);
    expect(Array.from(toggleAll(new Set(), []))).toEqual([]);
  });

  it("po odświeżeniu zostają tylko faktury nadal na liście", () => {
    expect(Array.from(keepVisible(new Set([1, 2, 3]), [2, 3, 4]))).toEqual([2, 3]);
  });
});

describe("recentMonths", () => {
  it("12 miesięcy wstecz przez przełom roku", () => {
    const months = recentMonths("2026-02");
    expect(months).toHaveLength(12);
    expect(months.slice(0, 3)).toEqual(["2026-02", "2026-01", "2025-12"]);
    expect(months[11]).toBe("2025-03");
  });
});
