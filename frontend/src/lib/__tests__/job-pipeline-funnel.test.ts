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
