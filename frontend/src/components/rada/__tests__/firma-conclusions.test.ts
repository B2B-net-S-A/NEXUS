import { describe, expect, it } from "vitest";

import { firmaConclusions } from "@/components/rada/firma-conclusions";
import type { BoardPeople, ExitItem } from "@/lib/api/supervisory-board";

function exit(reason: string, label: string): ExitItem {
  return {
    ended_on: "2099-03-31",
    client: "Klient A",
    project: null,
    reason,
    reason_label: label,
    lessons: null,
    party: null,
    mode: null,
    tenure_months: 12,
  };
}

function people(over: Partial<BoardPeople> = {}): BoardPeople {
  const items = [
    exit("project_ended", "koniec projektu"),
    exit("project_ended", "koniec projektu"),
    exit("client_budget_cut", "cięcie budżetu klienta"),
    exit("performance_issue", "problem jakościowy"),
    exit("unknown", "powód nie wpisany"),
  ];
  return {
    period: { kind: "quarter", start: "2099-01-01", end: "2099-04-01" },
    window: { from: "2099-01-01", to: "2099-03-31" },
    previous_window: { from: "2098-10-01", to: "2098-12-31" },
    placements: { count: 3, previous: 5, by_client: [{ client: "Klient A", count: 2 }] },
    contractors: { active: 300, previous: 302, clients: 40, by_client: [{ client: "Klient A", count: 180 }] },
    flows: { starts: 3, ends: 5, resignations: 0, previous_starts: 6, previous_ends: 4 },
    exits: {
      count: 5,
      by_reason: [
        { reason: "project_ended", label: "koniec projektu", count: 2 },
        { reason: "client_budget_cut", label: "cięcie budżetu klienta", count: 1 },
        { reason: "performance_issue", label: "problem jakościowy", count: 1 },
        { reason: "unknown", label: "powód nie wpisany", count: 1 },
      ],
      items,
    },
    previous_exits: [],
    ...over,
  };
}

describe("wnioski zakładki Firma", () => {
  it("opisuje placementy, kontraktorów, powody zejść i lejek", () => {
    const lines = firmaConclusions(people(), "Najwięcej osób odpada między etapem „A” a „B” — przechodzi 20%.");
    expect(lines[0]).toBe("3 placementy — o 2 mniej niż w poprzednim okresie (5). Najwięcej u klienta Klient A (2).");
    expect(lines[1]).toContain("Na projektach pracuje 300 kontraktorów");
    expect(lines[1]).toContain("netto -2");
    expect(lines[2]).toContain("5 zejść; najczęstszy powód: koniec projektu (2).");
    expect(lines[2]).toContain("Decyzja klienta (koniec projektu, cięcie budżetu, przejęcie): 3");
    expect(lines[2]).toContain("ryzyko leży w portfelu projektów");
    expect(lines[2]).toContain("1 zejście z powodu problemów jakościowych");
    expect(lines[2]).toContain("Przy 1 zejściu nie wpisano powodu.");
    expect(lines[3]).toContain("nie pokrywają zejść");
    expect(lines[4]).toBe("Lejek: Najwięcej osób odpada między etapem „A” a „B” — przechodzi 20%.");
  });

  it("bez zejść i z placementami pokrywającymi odejścia", () => {
    const lines = firmaConclusions(
      people({ exits: { count: 0, by_reason: [], items: [] }, flows: { starts: 4, ends: 0, resignations: 0, previous_starts: 0, previous_ends: 0 } }),
      null,
    );
    expect(lines).toContain("W okresie nikt nie zakończył kontraktu.");
    expect(lines).toContain("Placementy (3) pokrywają zejścia (0).");
  });
});
