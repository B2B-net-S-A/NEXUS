import { describe, expect, it } from "vitest";

import { tallyLine, verdict } from "../VotesTab";
import type { VoteTally } from "@/lib/api/supervisory-board";

function t(extra: Partial<VoteTally>): VoteTally {
  return {
    members: 3,
    voted: 0,
    for: 0,
    against: 0,
    abstain: 0,
    quorum: 2,
    quorum_met: false,
    tie_broken_by_chair: false,
    passed: false,
    ...extra,
  };
}

describe("uchwały w trybie pisemnym", () => {
  it("w toku pokazuje brak kworum, potem kierunek", () => {
    expect(verdict({ status: "open", result: null, tally: t({ voted: 1 }) }).label).toBe(
      "głosowało 1 z 3 — potrzeba 2",
    );
    expect(verdict({ status: "open", result: null, tally: t({ voted: 2, quorum_met: true, passed: true }) }).label).toBe(
      "na razie większość za",
    );
  });

  it("zamknięta: podjęta, niepodjęta, bez kworum, wycofana", () => {
    const passed = t({ voted: 2, for: 2, quorum_met: true, passed: true });
    expect(verdict({ status: "closed", result: passed, tally: passed }).tone).toBe("passed");
    const failed = t({ voted: 2, for: 1, against: 1, quorum_met: true });
    expect(verdict({ status: "closed", result: failed, tally: failed }).label).toBe("niepodjęta");
    const thin = t({ voted: 1, for: 1 });
    expect(verdict({ status: "closed", result: thin, tally: thin }).label).toBe("niepodjęta — za mało głosów");
    expect(verdict({ status: "withdrawn", result: null, tally: thin }).tone).toBe("withdrawn");
  });

  it("opisuje głosy", () => {
    expect(tallyLine(t({ for: 2, against: 1, abstain: 0 }))).toBe("za 2 · przeciw 1 · wstrzymało się 0");
  });
});
