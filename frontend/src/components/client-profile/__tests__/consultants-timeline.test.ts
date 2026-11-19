import { describe, expect, it } from "vitest";

import { orderWave } from "@/components/client-profile/ClientConsultantsTab";
import { timelineBar, timelineRange } from "@/components/client-profile/ConsultantsTimeline";

describe("„Kończy się DD.MM” — wiele zamówień kończy się tego samego dnia", () => {
  const rows = (dates: (string | null)[]) => dates.map((order_end_date) => ({ order_end_date }));

  it("wskazuje dzień z co najmniej pięcioma końcami w najbliższych 120 dniach", () => {
    const wave = orderWave(
      rows([
        ...Array(28).fill("2026-12-31"),
        "2026-11-30",
        "2026-11-30",
        "2027-06-30",
        null,
      ]),
      "2026-11-19",
    );
    expect(wave).toEqual({ date: "2026-12-31", count: 28 });
  });

  it("cztery końce tego samego dnia to jeszcze nie fala", () => {
    expect(orderWave(rows(Array(4).fill("2026-12-31")), "2026-11-19")).toBeNull();
  });

  it("pomija daty minione i dalsze niż 120 dni; przy remisie wcześniejszy dzień", () => {
    expect(orderWave(rows(Array(6).fill("2026-10-31")), "2026-11-19")).toBeNull();
    expect(orderWave(rows(Array(6).fill("2027-06-30")), "2026-11-19")).toBeNull();
    expect(
      orderWave(rows([...Array(5).fill("2027-01-31"), ...Array(5).fill("2026-12-31")]), "2026-11-19"),
    ).toEqual({ date: "2026-12-31", count: 5 });
  });
});

describe("oś czasu zamówień", () => {
  const range = timelineRange("2026-11-19", 8);

  it("zaczyna się pierwszego dnia bieżącego miesiąca i ma etykiety miesięcy", () => {
    expect(new Date(range.start).toISOString().slice(0, 10)).toBe("2026-11-01");
    expect(new Date(range.end).toISOString().slice(0, 10)).toBe("2027-07-01");
    expect(range.months.map((month) => month.label)).toEqual([
      "lis",
      "gru",
      "sty",
      "lut",
      "mar",
      "kwi",
      "maj",
      "cze",
    ]);
  });

  it("przycina pasek do osi; zamówienie bez końca biegnie do końca osi", () => {
    const decEnd = timelineBar({ order_start_date: "2026-10-01", order_end_date: "2026-12-31" }, range);
    expect(decEnd?.left).toBe(0);
    expect(decEnd?.openEnded).toBe(false);
    // Do końca grudnia to dwa z ośmiu miesięcy osi (lis + gru ≈ 61 z 242 dni).
    expect(decEnd?.width).toBeCloseTo(61 / 242, 2);

    const open = timelineBar({ order_start_date: "2026-11-18", order_end_date: null }, range);
    expect(open?.openEnded).toBe(true);
    expect((open?.left ?? 0) + (open?.width ?? 0)).toBeCloseTo(1, 5);
  });

  it("bez dat albo poza osią — brak paska", () => {
    expect(timelineBar({ order_start_date: null, order_end_date: null }, range)).toBeNull();
    expect(timelineBar({ order_start_date: "2026-01-01", order_end_date: "2026-03-31" }, range)).toBeNull();
  });
});
