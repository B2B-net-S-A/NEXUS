import { describe, expect, it } from "vitest";

import type { TeamRules } from "@/lib/api/requestAllocation";
import {
  changedRuleLabels,
  DEFAULT_TEAM_RULES,
  historyLines,
  ruleValueLabel,
} from "@/lib/allocation-rules";

describe("ruleValueLabel — każde pole i wartości brzegowe", () => {
  it("tryb: znany i nieznany kod", () => {
    expect(ruleValueLabel("mode", "auto")).toBe("Przydziela sam");
    expect(ruleValueLabel("mode", "turbo")).toBe("turbo");
  });
  it("rekrutacje P2", () => {
    expect(ruleValueLabel("include_p2", true)).toBe("P0, P1 i P2");
    expect(ruleValueLabel("include_p2", false)).toBe("P0 i P1");
  });
  it("osób na P1", () => {
    expect(ruleValueLabel("people_per_p1", 2)).toBe("2 os.");
  });
  it("limit: null i undefined = bez limitu, 0 to liczba", () => {
    expect(ruleValueLabel("max_load", null)).toBe("bez limitu");
    expect(ruleValueLabel("max_load", undefined)).toBe("bez limitu");
    expect(ruleValueLabel("max_load", 0)).toBe("0");
    expect(ruleValueLabel("max_load", 6)).toBe("6");
  });
  it("inna kategoria: 0 (także jako napis) i większa różnica", () => {
    expect(ruleValueLabel("overflow", 0)).toBe("przy każdej różnicy");
    expect(ruleValueLabel("overflow", "0")).toBe("przy każdej różnicy");
    expect(ruleValueLabel("overflow", 2)).toBe("różnica ponad 2");
  });
  it("osoby bez kategorii", () => {
    expect(ruleValueLabel("outsiders", true)).toBe("mogą dostać");
    expect(ruleValueLabel("outsiders", false)).toBe("czeka na Head of Recruitment");
  });
  it("kolejność", () => {
    expect(ruleValueLabel("order", "deadline_first")).toBe("najpierw najbliższy termin");
    expect(ruleValueLabel("order", "sent_first")).toBe("najpierw bez wysłanych");
  });
  it("urlopy", () => {
    expect(ruleValueLabel("leave_policy", "ignore")).toBe("przydziela mimo to");
    expect(ruleValueLabel("leave_policy", "wait")).toBe("czeka");
  });
  it("godzina przeglądu", () => {
    expect(ruleValueLabel("review_time", "07:45")).toBe("07:45");
  });
});

describe("changedRuleLabels", () => {
  it("bez zmian: pusta lista", () => {
    expect(changedRuleLabels(DEFAULT_TEAM_RULES, "off", { ...DEFAULT_TEAM_RULES }, "off")).toEqual(
      [],
    );
  });
  it("tryb i kilka pól w kolejności pól", () => {
    const draft: TeamRules = {
      ...DEFAULT_TEAM_RULES,
      max_load: 6,
      outsiders: false,
      leave_policy: "ignore",
    };
    expect(changedRuleLabels(DEFAULT_TEAM_RULES, "off", draft, "shadow")).toEqual([
      "Tryb: Proponuje",
      "Limit P1 na osobę: 6",
      "Osoby bez kategorii: czeka na Head of Recruitment",
      "Bez świeżych urlopów: przydziela mimo to",
    ]);
  });
});

describe("historyLines", () => {
  it("nieznane pole zostaje surową nazwą, znane ma przed → po", () => {
    expect(
      historyLines({
        max_load: [null, 6],
        pole_z_przyszlosci: [1, 2],
        mode: ["off", "auto"],
      }),
    ).toEqual([
      "Limit P1 na osobę: bez limitu → 6",
      "pole_z_przyszlosci",
      "Tryb: Wyłączony → Przydziela sam",
    ]);
  });
  it("pusty wpis", () => {
    expect(historyLines({})).toEqual([]);
  });
});
