import { describe, expect, it } from "vitest";

import {
  buildChartModel,
  buildStepRows,
  describeRateChanges,
  entryInEffect,
  liveSchedule,
  rateOn,
  type AmendmentRef,
  type ScheduleEntry,
} from "@/components/contracts/rates/rate-steps";

// Fikcyjny kontrakt o typowym kształcie: aneks z 01.07.2026 zapisany trzy razy
// po stronie kandydata, harmonogram zaczyna się po starcie umowy.
const CLIENT_155: ScheduleEntry[] = [
  { id: 7, rate: 180, effective_from: "2026-04-01", note: "Stawka początkowa", source_order_id: null },
  { id: 8, rate: 170, effective_from: "2026-07-01", note: null, source_order_id: null },
];
const CANDIDATE_155: ScheduleEntry[] = [
  { id: 4, rate: 140, effective_from: "2026-04-01", note: "Stawka początkowa" },
  { id: 5, rate: 130, effective_from: "2026-07-01", note: "Zmiana stawki od lipca" },
  { id: 6, rate: 130, effective_from: "2026-07-01", note: null },
  { id: 17, rate: 130, effective_from: "2026-07-01", note: null },
];
const RATE_AMENDMENT: AmendmentRef = { amendment_type: "rate_change", effective_date: "2026-07-01", withdrawn: false };
const TODAY = "2026-11-20";

function rows155(amendments: AmendmentRef[] | null = [RATE_AMENDMENT]) {
  return buildStepRows({
    client: liveSchedule(CLIENT_155),
    candidate: liveSchedule(CANDIDATE_155),
    fallbackClient: 170,
    fallbackCandidate: 130,
    today: TODAY,
    amendments,
  });
}

describe("liveSchedule — wpisy z tą samą datą", () => {
  it("zostawia wpis dodany jako ostatni, liczy zastąpione i zbiera ich notatki", () => {
    const live = liveSchedule(CANDIDATE_155);
    expect(live.steps.map((s) => [s.date, s.id, s.rate])).toEqual([
      ["2026-04-01", 4, 140],
      ["2026-07-01", 17, 130],
    ]);
    expect(live.superseded).toBe(2);
    expect(live.steps[1].notes).toEqual(["Zmiana stawki od lipca"]);
  });

  it("przy remisie trzyma kolejność z API, nie kolejność id ani stawki", () => {
    const live = liveSchedule([
      { id: 3, rate: 130, effective_from: "2026-07-01", source_order_id: 77 },
      { id: 1, rate: 120, effective_from: "2026-01-01", source_order_id: null },
      { id: 2, rate: 140, effective_from: "2026-07-01", source_order_id: null },
    ]);
    expect(live.steps.map((s) => s.id)).toEqual([1, 2]);
    expect(live.steps[1].sourceOrderId).toBeNull();
    expect(live.superseded).toBe(1);
  });

  it("pusty albo brakujący harmonogram to zero kroków", () => {
    expect(liveSchedule([])).toEqual({ steps: [], superseded: 0 });
    expect(liveSchedule(undefined)).toEqual({ steps: [], superseded: 0 });
  });
});

describe("rateOn", () => {
  const steps = liveSchedule(CLIENT_155).steps;
  it("bierze ostatni krok nie późniejszy niż dzień", () => {
    expect(rateOn(steps, "2026-06-30", 999)).toBe(180);
    expect(rateOn(steps, "2026-07-01", 999)).toBe(170);
  });
  it("przed pierwszym krokiem nie ma stawki, a pusty harmonogram to stawka z kontraktu", () => {
    expect(rateOn(steps, "2026-03-31", 999)).toBeNull();
    expect(rateOn([], "2026-03-31", 999)).toBe(999);
    expect(rateOn([], "2026-03-31", null)).toBeNull();
  });
});

describe("buildStepRows", () => {
  it("daje wiersz na dzień zmiany bez wierszy zastąpionych, ze źródłem i stanem", () => {
    const rows = rows155();
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      date: "2026-04-01",
      client: 180,
      candidate: 140,
      source: "manual",
      note: "Stawka początkowa",
      state: "past",
      clientStepId: 7,
      candidateStepId: 4,
    });
    expect(rows[1]).toMatchObject({
      date: "2026-07-01",
      client: 170,
      candidate: 130,
      source: "amendment",
      note: "Zmiana stawki od lipca",
      state: "current",
      clientChanged: true,
      candidateChanged: true,
      clientStepId: 8,
      candidateStepId: 17,
    });
  });

  it("bez odczytu aneksów nie zgaduje: krok bez zamówienia to „ręcznie / aneks”", () => {
    expect(rows155(null).map((r) => r.source)).toEqual(["manual_or_amendment", "manual_or_amendment"]);
  });

  it("aneks wycofany albo innego rodzaju nie robi z kroku aneksu", () => {
    const rows = rows155([
      { ...RATE_AMENDMENT, withdrawn: true },
      { amendment_type: "extension", effective_date: "2026-07-01" },
    ]);
    expect(rows[1].source).toBe("manual");
  });

  it("krok z zamówienia ma źródło „zamówienie” bez powtarzającej je notatki", () => {
    const rows = buildStepRows({
      client: liveSchedule([
        { id: 103, rate: 30.125, effective_from: "2019-02-18", note: "Stawka sprzed synchronizacji z zamówieniami" },
        { id: 442, rate: 30.125, effective_from: "2026-06-01", note: "Z zamówienia klienta", source_order_id: 803 },
      ]),
      candidate: liveSchedule([{ id: 167, rate: 100, effective_from: "2019-02-18" }]),
      fallbackClient: 30.125,
      fallbackCandidate: 100,
      today: TODAY,
      amendments: [],
    });
    expect(rows.map((r) => [r.date, r.source, r.note])).toEqual([
      ["2019-02-18", "manual", "Stawka sprzed synchronizacji z zamówieniami"],
      ["2026-06-01", "order", null],
    ]);
    // Ta sama stawka z nowego źródła — wiersz zostaje, ale kwoty się nie zmieniły.
    expect(rows[1]).toMatchObject({ clientChanged: false, candidateChanged: false, candidate: 100 });
  });

  it("kandydat bez harmonogramu bierze stawkę z kontraktu, a dzień przed krokami klienta nie ma stawki klienta", () => {
    const rows = buildStepRows({
      client: liveSchedule([{ id: 1, rate: 150, effective_from: "2026-05-01" }]),
      candidate: liveSchedule([{ id: 2, rate: 100, effective_from: "2026-03-01" }]),
      fallbackClient: 150,
      fallbackCandidate: 100,
      today: TODAY,
      amendments: [],
    });
    expect(rows.map((r) => [r.date, r.client, r.candidate, r.clientChanged, r.candidateChanged])).toEqual([
      ["2026-03-01", null, 100, true, true],
      ["2026-05-01", 150, 100, true, false],
    ]);
  });

  it("jeden przyszły krok jest zaplanowany i żaden nie obowiązuje", () => {
    const rows = buildStepRows({
      client: liveSchedule([{ id: 1, rate: 150, effective_from: "2099-01-01", source_order_id: 77 }]),
      candidate: liveSchedule([]),
      fallbackClient: 150,
      fallbackCandidate: null,
      today: TODAY,
      amendments: [],
    });
    expect(rows).toEqual([expect.objectContaining({ state: "planned", source: "order", candidate: null })]);
  });

  it("bez kroków nie ma wierszy", () => {
    expect(
      buildStepRows({
        client: liveSchedule([]),
        candidate: liveSchedule([]),
        fallbackClient: null,
        fallbackCandidate: null,
        today: TODAY,
        amendments: null,
      }),
    ).toEqual([]);
  });
});

describe("buildChartModel", () => {
  it("jeden krok to zdanie, nie wykres", () => {
    const single = rows155().slice(1);
    expect(
      buildChartModel({ rows: single, today: TODAY, contractStart: null, contractEnd: null, orderEnd: null }),
    ).toBeNull();
  });

  it("oś od pierwszego kroku do końca zamówienia, odcinki z obiema stawkami", () => {
    const model = buildChartModel({
      rows: rows155(),
      today: TODAY,
      contractStart: "2025-12-01",
      contractEnd: null,
      orderEnd: "2026-12-31",
    });
    expect(model?.axis).toEqual({
      start: "2026-04-01",
      end: "2026-12-31",
      startLabel: "pierwsza stawka",
      endLabel: "koniec zamówienia",
    });
    expect(model?.segments).toEqual([
      { from: "2026-04-01", to: "2026-07-01", client: 180, candidate: 140 },
      { from: "2026-07-01", to: "2026-12-31", client: 170, candidate: 130 },
    ]);
  });

  it("bez zamówienia w przyszłości oś kończy się dziś, a start umowy ma swój podpis", () => {
    const model = buildChartModel({
      rows: rows155(),
      today: TODAY,
      contractStart: "2026-04-01",
      contractEnd: null,
      orderEnd: "2026-09-30",
    });
    expect(model?.axis).toMatchObject({ start: "2026-04-01", end: TODAY, startLabel: "start umowy", endLabel: "" });
  });

  it("zaplanowany krok dostaje miesiąc zapasu za sobą", () => {
    const rows = buildStepRows({
      client: liveSchedule([
        { id: 1, rate: 150, effective_from: "2026-01-01" },
        { id: 2, rate: 160, effective_from: "2027-01-01" },
      ]),
      candidate: liveSchedule([]),
      fallbackClient: 150,
      fallbackCandidate: 100,
      today: TODAY,
      amendments: [],
    });
    const model = buildChartModel({ rows, today: TODAY, contractStart: null, contractEnd: null, orderEnd: null });
    expect(model?.axis.end).toBe("2027-02-01");
    expect(model?.segments.at(-1)).toEqual({ from: "2027-01-01", to: "2027-02-01", client: 160, candidate: 100 });
  });

  it("zakończona umowa kończy oś na swoim końcu, nie na dziś", () => {
    const model = buildChartModel({
      rows: rows155(),
      today: TODAY,
      contractStart: null,
      contractEnd: "2026-09-30",
      orderEnd: null,
    });
    expect(model?.axis).toMatchObject({ end: "2026-09-30", endLabel: "koniec umowy" });
  });
});

describe("describeRateChanges", () => {
  it("mówi zdaniem, od kiedy i na ile zmieniła się każda stawka", () => {
    expect(describeRateChanges(rows155(), { client: "zł/h", candidate: "zł/h" })).toBe(
      "Stawki od 01.04.2026: klient płaci 180,00 zł/h, od 01.07.2026 170,00 zł/h; " +
        "kandydat dostaje 140,00 zł/h, od 01.07.2026 130,00 zł/h. Kwoty są też w tabeli pod wykresem.",
    );
  });

  it("stawka bez zmian, zaplanowana zmiana i brak stawki", () => {
    const rows = buildStepRows({
      client: liveSchedule([
        { id: 1, rate: 150, effective_from: "2026-01-01" },
        { id: 2, rate: 160, effective_from: "2027-01-01" },
      ]),
      candidate: liveSchedule([]),
      fallbackClient: 150,
      fallbackCandidate: null,
      today: TODAY,
      amendments: [],
    });
    expect(describeRateChanges(rows, { client: "zł/h", candidate: "zł/h" })).toBe(
      "Stawki od 01.01.2026: klient płaci 150,00 zł/h, od 01.01.2027 160,00 zł/h (zaplanowana); " +
        "bez stawki kandydata. Kwoty są też w tabeli pod wykresem.",
    );
    const flat = rows.map((r) => ({ ...r, client: 150 }));
    expect(describeRateChanges(flat, { client: "zł/h", candidate: "zł/h" })).toContain(
      "klient płaci 150,00 zł/h bez zmian",
    );
  });
});

describe("entryInEffect (stawka ramowa)", () => {
  const schedule = [
    { id: 1, rate: 160, effective_from: "2026-01-01", effective_to: "2026-06-30" },
    { id: 2, rate: 165, effective_from: "2026-07-01", effective_to: "2026-12-31" },
    { id: 3, rate: 170, effective_from: "2027-01-01", effective_to: null },
  ];
  it("bierze wpis obowiązujący dziś", () => {
    expect(entryInEffect(schedule, TODAY)?.id).toBe(2);
  });
  it("gdy wszystkie są przyszłe — najwcześniejszy; remis wygrywa wpis dodany później", () => {
    expect(entryInEffect(schedule, "2025-12-31")?.id).toBe(1);
    expect(
      entryInEffect(
        [
          { id: 8, rate: 1, effective_from: "2026-07-01" },
          { id: 9, rate: 2, effective_from: "2026-07-01" },
        ],
        TODAY,
      )?.id,
    ).toBe(9);
  });
  it("pusty harmonogram — nic", () => {
    expect(entryInEffect([], TODAY)).toBeNull();
    expect(entryInEffect(undefined, TODAY)).toBeNull();
  });
});
