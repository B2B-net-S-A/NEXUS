import { describe, expect, it } from "vitest";

import {
  buildStageFunnel,
  funnelRejectedTotal,
  funnelTooltip,
  funnelTotal,
} from "@/lib/job-pipeline-funnel";

describe("buildStageFunnel", () => {
  it("zwraca sześć grup z zerami, gdy brak danych", () => {
    const groups = buildStageFunnel(undefined);
    expect(groups).toHaveLength(6);
    expect(groups.map((g) => g.count)).toEqual([0, 0, 0, 0, 0, 0]);
    expect(groups.map((g) => g.key)).toEqual([
      "new",
      "screening",
      "verified",
      "with_client",
      "contract",
      "hired",
    ]);
  });

  it("grupuje `prep_call` razem z `new` — rozmowa przed screeningiem", () => {
    const groups = buildStageFunnel({ new: 3, prep_call: 2 });
    const nowi = groups.find((g) => g.key === "new");
    expect(nowi?.count).toBe(5);
  });

  it("grupuje cv_sent/client_interview pod „u klienta”, a interview (wewnętrzny) pod „zweryfikowani”", () => {
    const groups = buildStageFunnel({
      cv_sent: 1,
      interview: 2,
      client_interview: 3,
    });
    // `interview` to etap WEWNĘTRZNY (StageCategory.internal) — kandydat nie
    // był jeszcze u klienta; liczenie go do „u klienta" zawyżało tę grupę.
    expect(groups.find((g) => g.key === "with_client")?.count).toBe(4);
    expect(groups.find((g) => g.key === "verified")?.count).toBe(2);
  });

  it("grupuje acceptance/negotiation/onboarding pod „umowa”", () => {
    const groups = buildStageFunnel({
      acceptance: 1,
      negotiation: 1,
      onboarding: 1,
    });
    const umowa = groups.find((g) => g.key === "contract");
    expect(umowa?.count).toBe(3);
  });

  it("liczy screening i hired 1:1, bez grupowania", () => {
    const groups = buildStageFunnel({ screening: 4, hired: 2 });
    expect(groups.find((g) => g.key === "screening")?.count).toBe(4);
    expect(groups.find((g) => g.key === "hired")?.count).toBe(2);
  });

  it("pomija rejected/withdrawn — to stany terminalne, poza sześcioma grupami", () => {
    const groups = buildStageFunnel({ rejected: 5, withdrawn: 3, new: 1 });
    expect(funnelTotal(groups)).toBe(1);
  });

  it("nieznany klucz etapu jest po cichu pomijany (nie wywala listy)", () => {
    expect(() => buildStageFunnel({ some_future_stage: 9 })).not.toThrow();
    expect(funnelTotal(buildStageFunnel({ some_future_stage: 9 }))).toBe(0);
  });
});

describe("funnelTotal", () => {
  it("sumuje wszystkie sześć grup", () => {
    const groups = buildStageFunnel({
      new: 1,
      screening: 2,
      verified: 3,
      cv_sent: 4,
      acceptance: 5,
      hired: 6,
    });
    expect(funnelTotal(groups)).toBe(21);
  });
});

describe("funnelRejectedTotal", () => {
  it("sumuje WYŁĄCZNIE rejected + withdrawn", () => {
    expect(funnelRejectedTotal({ rejected: 4, withdrawn: 2, new: 9 })).toBe(6);
  });

  it("brak danych → 0", () => {
    expect(funnelRejectedTotal(undefined)).toBe(0);
    expect(funnelRejectedTotal(null)).toBe(0);
  });
});

describe("funnelTooltip", () => {
  it("pomija grupy zerowe", () => {
    const groups = buildStageFunnel({ new: 2, hired: 1 });
    expect(funnelTooltip(groups)).toBe("Nowi: 2 · Zatrudnieni: 1");
  });

  it("brak kandydatów → komunikat zamiast pustego stringa", () => {
    expect(funnelTooltip(buildStageFunnel(undefined))).toBe(
      "Brak kandydatów w tej rekrutacji.",
    );
  });
});

/**
 * UAT B33 — lista i szczegóły liczą z JEDNEJ definicji.
 *
 * Kolumny szablonu z wiersza listy (`stage_columns`) są grupowane tą samą
 * funkcją co szyny szczegółów (`groupKanbanColumns`). Własny etap szablonu
 * stojący ZA screeningiem („Przepuszczony przez DZ") niesie `stage: "new"`,
 * więc po samym `stage_breakdown` lista liczyła go do „Nowi", a szczegóły —
 * po pozycji — do „Zweryfikowani" (4/1/1/2 vs 3/1/2/2).
 */
describe("buildStageFunnel — stage_columns (UAT B33)", () => {
  const columns = [
    { stage: "new", category: "internal" as const, count: 3, stage_def_id: 1, name: "Nowy", order: 0 },
    { stage: "screening", category: "internal" as const, count: 1, stage_def_id: 2, name: "Screening", order: 1 },
    // Własny etap bez legacy enuma — backend degraduje `stage` do "new".
    { stage: "new", category: "internal" as const, count: 1, stage_def_id: 3, name: "Przepuszczony przez DZ", order: 2 },
    { stage: "verified", category: "internal" as const, count: 1, stage_def_id: 4, name: "Zweryfikowany", order: 3 },
    { stage: "cv_sent", category: "internal" as const, count: 2, stage_def_id: 5, name: "CV Wysłane", order: 4 },
    { stage: "new", category: "terminal" as const, count: 2, stage_def_id: 6, name: "Zatrudniony", order: 5, terminal_type: "hired" as const },
    { stage: "new", category: "terminal" as const, count: 4, stage_def_id: 7, name: "Odrzucony", order: 6, terminal_type: "rejected" as const },
  ];
  // Legacy rozkład tej samej rekrutacji (po enumie): własny etap = "new".
  const breakdown = { new: 4, screening: 1, verified: 1, cv_sent: 2, hired: 2, rejected: 4 };

  it("liczy własny etap za screeningiem do „Zweryfikowani”, tak jak szczegóły", () => {
    const groups = buildStageFunnel({ stage_columns: columns, stage_breakdown: breakdown });
    const byKey = Object.fromEntries(groups.map((g) => [g.key, g.count]));
    expect(byKey).toEqual({
      new: 3,
      screening: 1,
      verified: 2,
      with_client: 2,
      contract: 0,
      hired: 2,
    });
  });

  it("daje te same liczby co grupowanie szyn szczegółów", async () => {
    const { groupKanbanColumns } = await import("@/lib/pipeline-flow");
    const detail = Object.fromEntries(
      groupKanbanColumns(columns.map((c) => ({ ...c, items: [] }))).map((g) => [g.key, g.count]),
    );
    const list = Object.fromEntries(
      buildStageFunnel({ stage_columns: columns }).map((g) => [g.key, g.count]),
    );
    expect(list.new).toBe(detail.intake);
    expect(list.screening).toBe(detail.screening);
    expect(list.verified).toBe(detail.verification);
    expect(list.with_client).toBe(detail.client);
    expect(list.contract + list.hired).toBe(detail.contract);
    expect(funnelRejectedTotal({ stage_columns: columns })).toBe(detail.closed);
  });

  it("bez `stage_columns` cofa się do legacy rozkładu (starsze odpowiedzi)", () => {
    const groups = buildStageFunnel({ stage_breakdown: breakdown });
    expect(groups.find((g) => g.key === "new")?.count).toBe(4);
    expect(funnelRejectedTotal({ stage_breakdown: breakdown })).toBe(4);
  });
});
