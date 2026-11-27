import { describe, expect, it } from "vitest";

import {
  buildTiles,
  calendarDays,
  exceptionBounds,
  exceptionError,
  nextCadence,
  repairBrief,
  type SecurityFinding,
  type SecurityRoutine,
  type SecurityTiles,
} from "./security-model";

const TILES: SecurityTiles = {
  ci: { new: 0, conclusion: "success", run_started_at: "2026-11-23T05:31:00Z", run_url: null, configured: true },
  waiting: { total: 2, by_severity: { high: 1, medium: 1 } },
  traffic: { blocked: 317, events: 41, configured: true },
  logins: { ok: 58, denied: 0 },
};

const moment = () => "23.11.2026, 06:31";

describe("buildTiles", () => {
  it("pokazuje cztery kafelki jak na makiecie", () => {
    const tiles = buildTiles(TILES, moment);
    expect(tiles.map((t) => [t.key, t.value, t.tone])).toEqual([
      ["ci", "0 nowych", "success"],
      ["waiting", "2", "danger"],
      ["traffic", "317 blokad", "warning"],
      ["logins", "58 / 0", "success"],
    ]);
    expect(tiles[1].sub).toBe("wysoka 1 · średnia 1");
  });

  it("czerwony bieg CI i brak CrowdSec nie udają zieleni", () => {
    const tiles = buildTiles(
      {
        ...TILES,
        ci: { ...TILES.ci, conclusion: "failure" },
        traffic: { blocked: 0, events: 0, configured: false },
      },
      moment,
    );
    expect(tiles[0]).toMatchObject({ value: "czerwony", tone: "danger" });
    expect(tiles[2]).toMatchObject({ value: "—", tone: "neutral" });
  });

  it("CI bez pierwszego odczytu jest neutralne", () => {
    const tiles = buildTiles({ ...TILES, ci: { ...TILES.ci, configured: false } }, moment);
    expect(tiles[0]).toMatchObject({ value: "—", tone: "neutral" });
  });
});

describe("wyjątek", () => {
  const today = "2026-11-27";

  it("wymaga powodu i daty po dzisiaj, najwyżej rok", () => {
    expect(exceptionError("krótki", "2026-12-05", today)).toMatch(/powód/);
    expect(exceptionError("Czekamy na okno 05.12", "", today)).toMatch(/datę/);
    expect(exceptionError("Czekamy na okno 05.12", today, today)).toMatch(/po dzisiejszym/);
    expect(exceptionError("Czekamy na okno 05.12", "2027-11-28", today)).toMatch(/rok/);
    expect(exceptionError("Czekamy na okno 05.12", "2026-12-05", today)).toBeNull();
  });

  it("granice pola daty", () => {
    expect(exceptionBounds(today)).toEqual({ min: "2026-11-28", max: "2027-11-27" });
  });
});

describe("repairBrief", () => {
  it("ma tytuł, gdzie, dowód, kroki i metę", () => {
    const finding: SecurityFinding = {
      id: 7,
      source: "ci",
      scanner: "zizmor",
      severity: "high",
      title: "Wstrzyknięcie w run:",
      location: ".github/workflows/deploy.yml:42",
      evidence: "reguła template-injection",
      impact: null,
      steps: ["Przenieś wartość do env", "Dodaj test"],
      status: "open",
      stored_status: "open",
      exception_expired: false,
      owner_user_id: null,
      exception_reason: null,
      exception_until: null,
      closed_note: null,
      closed_at: null,
      first_seen_at: "2026-11-27T05:30:00Z",
      last_seen_at: "2026-11-27T05:30:00Z",
    };
    const brief = repairBrief(finding);
    expect(brief).toContain("id 7");
    expect(brief).toContain("Gdzie: .github/workflows/deploy.yml:42");
    expect(brief).toContain("2. Dodaj test");
    expect(brief).toContain("Meta:");
    expect(brief).not.toContain("Wpływ:");
  });
});

describe("kalendarz rutyn", () => {
  const routine = (over: Partial<SecurityRoutine>): SecurityRoutine => ({
    id: 1,
    key: "ci_weekly",
    title: "Skan CI",
    cadence: "week",
    owner_label: "CI",
    automatic: true,
    last_done_on: "2026-11-23",
    next_due_on: "2026-11-30",
    last_note: null,
    state: "ok",
    ...over,
  });

  it("rytm miesięczny i kwartalny trzyma dzień albo koniec miesiąca", () => {
    expect(nextCadence("2026-11-23", "week")).toBe("2026-11-30");
    expect(nextCadence("2027-01-31", "month")).toBe("2027-02-28");
    expect(nextCadence("2026-11-30", "quarter")).toBe("2027-02-28");
  });

  it("miesiąc od poniedziałku, tygodniowa rutyna co tydzień, wykonanie z ✓", () => {
    const days = calendarDays([routine({})], "2026-12-01", "2026-11-27", "month");
    expect(days[0].iso).toBe("2026-11-30");
    expect(days.length % 7).toBe(0);
    const chips = days.filter((d) => d.chips.length).map((d) => [d.iso, d.chips[0].kind]);
    expect(chips).toEqual([
      ["2026-11-30", "due"],
      ["2026-12-07", "planned"],
      ["2026-12-14", "planned"],
      ["2026-12-21", "planned"],
      ["2026-12-28", "planned"],
    ]);
    const november = calendarDays([routine({})], "2026-11-27", "2026-11-27", "month");
    expect(november.find((d) => d.iso === "2026-11-23")?.chips[0].kind).toBe("done");
  });

  it("termin w przeszłości jest po terminie", () => {
    const days = calendarDays(
      [routine({ id: 2, cadence: "quarter", next_due_on: "2026-11-20", last_done_on: null })],
      "2026-11-27",
      "2026-11-27",
      "week",
    );
    expect(days).toHaveLength(7);
    expect(days[0].iso).toBe("2026-11-23");
    const all = calendarDays(
      [routine({ id: 2, cadence: "quarter", next_due_on: "2026-11-20", last_done_on: null })],
      "2026-11-01",
      "2026-11-27",
      "month",
    );
    expect(all.find((d) => d.iso === "2026-11-20")?.chips[0].kind).toBe("overdue");
  });
});
