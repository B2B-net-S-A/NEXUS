import { describe, expect, it } from "vitest";

import cases from "@/lib/__fixtures__/board-stage-cases.json";
import { foldBoardColumns } from "@/lib/board-stages";
import {
  buildStageFunnel,
  funnelGroupStages,
  funnelRejectedTotal,
  funnelTooltip,
  funnelTotal,
} from "@/lib/job-pipeline-funnel";

const byKey = (input: Parameters<typeof buildStageFunnel>[0]) =>
  Object.fromEntries(buildStageFunnel(input).map((g) => [g.key, g.count]));

describe("buildStageFunnel — osiem kolumn Tablicy (lista v5)", () => {
  it("zwraca osiem kolumn w kolejności Tablicy, z zerami, gdy brak danych", () => {
    const groups = buildStageFunnel(undefined);
    expect(groups.map((g) => g.key)).toEqual([
      "new",
      "screening",
      "verified",
      "cv_qc",
      "cv_sent",
      "client_interview",
      "contract",
      "hired",
    ]);
    expect(groups.map((g) => g.label)).toEqual([
      "Nowi",
      "Screening",
      "Zweryfikowany",
      "QC CV",
      "CV wysłane",
      "Rozmowa u klienta",
      "Umowa",
      "Zatrudniony",
    ]);
    expect(groups.every((g) => g.count === 0)).toBe(true);
  });

  it("każdy etap z fixture'u Tablicy trafia do tej samej kolumny co na Tablicy", () => {
    // `board-stage-cases.json` czyta też `placeStage` i backend
    // (`board_column_for`) — lista nie ma własnej kopii reguły.
    for (const c of cases.cases) {
      const groups = byKey({
        stage_columns: [
          { stage: c.stage, name: c.name, category: c.category as never, count: 1 },
        ],
      });
      const expected = c.column === "closed" ? null : c.column;
      const hit = Object.entries(groups).filter(([, n]) => n === 1).map(([k]) => k);
      expect(hit, c.name).toEqual(expected ? [expected] : []);
      if (!expected) {
        expect(
          funnelRejectedTotal({
            stage_columns: [
              { stage: c.stage, name: c.name, category: c.category as never, count: 1 },
            ],
          }),
          c.name,
        ).toBe(1);
      }
    }
  });

  it("etap QC CV z kodem technicznym `interview` NIE liczy się do „Zweryfikowanych”", () => {
    const groups = byKey({
      stage_columns: [
        { stage: "verified", name: "Zweryfikowany", category: "internal", count: 2 },
        { stage: "interview", name: "QC CV", category: "internal", count: 3 },
        { stage: "new", name: "Wysłać do Cpro", category: "internal", count: 1 },
      ],
    });
    expect(groups.verified).toBe(2);
    expect(groups.cv_qc).toBe(4);
  });

  it("zgadza się ze składaniem kolumn Tablicy (`foldBoardColumns`) na szablonie kanonicznym", () => {
    const columns = [
      { stage: "posting", name: "Ogłoszenia", category: "internal" as const, count: 4 },
      { stage: "new", name: "Nowi", category: "internal" as const, count: 1 },
      { stage: "screening", name: "Screening", category: "internal" as const, count: 2 },
      { stage: "verified", name: "Zweryfikowany", category: "internal" as const, count: 3 },
      { stage: "interview", name: "QC CV", category: "internal" as const, count: 5 },
      { stage: "cv_sent", name: "CV Wysłane", category: "internal" as const, count: 6 },
      { stage: "new", name: "Preparation Meeting", category: "internal" as const, count: 1 },
      { stage: "client_interview", name: "Interview Klient", category: "external" as const, count: 7 },
      { stage: "acceptance", name: "Akceptacja", category: "external" as const, count: 1 },
      { stage: "new", name: "Umowa wysłana", category: "external" as const, count: 2 },
      { stage: "hired", name: "Zatrudniony", category: "terminal" as const, count: 8, terminal_type: "hired" as const },
      { stage: "rejected", name: "Odrzucony", category: "terminal" as const, count: 9, terminal_type: "rejected" as const },
    ];
    const board = foldBoardColumns(columns.map((c) => ({ ...c, items: [] })));
    const boardByKey = Object.fromEntries(
      board.columns.map((f) => [f.key, f.count]),
    );
    const list = byKey({ stage_columns: columns });
    for (const [key, count] of Object.entries(list)) {
      expect(count, key).toBe(boardByKey[key] ?? 0);
    }
    expect(funnelRejectedTotal({ stage_columns: columns })).toBe(
      board.closed.reduce((sum, c) => sum + c.count, 0),
    );
  });

  it("bez `stage_columns` cofa się do legacy rozkładu po kodzie (ta sama reguła)", () => {
    const groups = byKey({
      stage_breakdown: {
        posting: 1,
        new: 2,
        prep_call: 1,
        screening: 3,
        verified: 4,
        interview: 1,
        cv_sent: 5,
        client_interview: 6,
        acceptance: 7,
        onboarding: 1,
        hired: 2,
        rejected: 9,
      },
    });
    expect(groups).toEqual({
      new: 3,
      screening: 4,
      // Bez nazwy etapu QC nie da się odróżnić — kod `interview` → Zweryfikowany.
      verified: 5,
      cv_qc: 0,
      cv_sent: 5,
      client_interview: 6,
      contract: 7,
      hired: 3,
    });
  });

  it("nieznany kod etapu nie wywala listy (placeStage → „Nowi”, jak na Tablicy)", () => {
    expect(() => buildStageFunnel({ some_future_stage: 9 })).not.toThrow();
    expect(byKey({ some_future_stage: 9 }).new).toBe(9);
  });
});

describe("funnelTotal / funnelRejectedTotal", () => {
  it("sumuje osiem kolumn, bez zamkniętych", () => {
    const groups = buildStageFunnel({ new: 1, screening: 2, cv_sent: 4, hired: 6, rejected: 5 });
    expect(funnelTotal(groups)).toBe(13);
  });

  it("zamknięci = odrzuceni + wycofani", () => {
    expect(funnelRejectedTotal({ rejected: 4, withdrawn: 2, new: 9 })).toBe(6);
    expect(funnelRejectedTotal(undefined)).toBe(0);
    expect(funnelRejectedTotal(null)).toBe(0);
  });
});

describe("funnelTooltip", () => {
  it("pomija grupy zerowe", () => {
    expect(funnelTooltip(buildStageFunnel({ new: 2, hired: 1 }))).toBe(
      "Nowi: 2 · Zatrudniony: 1",
    );
  });

  it("brak kandydatów → komunikat zamiast pustego stringa", () => {
    expect(funnelTooltip(buildStageFunnel(undefined))).toBe(
      "Brak kandydatów w tej rekrutacji.",
    );
  });
});

describe("funnelGroupStages — pełne nazwy etapów w tooltipie kolumny", () => {
  it("suma nazw w kolumnie = liczba w komórce", () => {
    const summary = {
      stage_columns: [
        { stage: "interview", name: "Przepuszczony przez DZ", category: "internal" as const, count: 2 },
        { stage: "new", name: "Wysłać do Cpro", category: "internal" as const, count: 1 },
      ],
    };
    const stages = funnelGroupStages(summary);
    expect(stages.cv_qc).toEqual([
      { name: "Przepuszczony przez DZ", count: 2 },
      { name: "Wysłać do Cpro", count: 1 },
    ]);
    expect(byKey(summary).cv_qc).toBe(3);
  });

  it("bez `stage_columns` nazw nie znamy", () => {
    expect(funnelGroupStages({ stage_breakdown: { new: 1 } }).new).toEqual([]);
  });
});
