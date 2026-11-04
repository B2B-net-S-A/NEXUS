import { describe, expect, it } from "vitest"

import { DEFAULT_TEAM_RULES, changedRuleLabels, historyLines } from "@/lib/allocation-rules"

describe("changedRuleLabels", () => {
  it("nic nie zmienione — pusta lista", () => {
    expect(changedRuleLabels(DEFAULT_TEAM_RULES, "auto", DEFAULT_TEAM_RULES, "auto")).toEqual([])
  })

  it("tryb i zasady opisane słowami", () => {
    const draft = { ...DEFAULT_TEAM_RULES, include_p2: true, max_load: 6, overflow: 0 }
    expect(changedRuleLabels(DEFAULT_TEAM_RULES, "auto", draft, "shadow")).toEqual([
      "Tryb: Proponuje",
      "Rekrutacje: P0, P1 i P2",
      "Limit P1 na osobę: 6",
      "Inna kategoria: przy każdej różnicy",
    ])
  })
})

describe("historyLines", () => {
  it("przed → po, także tryb i brak limitu", () => {
    expect(
      historyLines({
        mode: ["shadow", "auto"],
        max_load: [null, 6],
        leave_policy: ["wait", "ignore"],
      }),
    ).toEqual([
      "Tryb: Proponuje → Przydziela sam",
      "Limit P1 na osobę: bez limitu → 6",
      "Bez świeżych urlopów: czeka → przydziela mimo to",
    ])
  })

  it("nieznane pole (stary zapis) nie wywraca listy", () => {
    expect(historyLines({ sourcer_threshold: [15, 40] })).toEqual(["sourcer_threshold"])
  })
})
