import { describe, expect, it } from "vitest";

import {
  dlLeadSortValue,
  isNameColumn,
  nextColumnSort,
  sortRowsByColumn,
  splitFormerEmployees,
  summarizeFormerEmployees,
  teamPeopleSortValue,
} from "@/lib/insights-people-table";
import type { InsightsDlPortfolioLead } from "@/lib/insights-api";
import type { TeamPeopleRow } from "@/lib/insights-team-api";

function person(overrides: Partial<TeamPeopleRow> & { user_id: number; name: string }): TeamPeopleRow {
  return {
    role: "recruiter",
    is_active: true,
    verifications: 0,
    recommendations: 0,
    interviews: 0,
    placements: 0,
    previous_placements: 0,
    verifications_per_workday: null,
    precision_pct: null,
    ...overrides,
  };
}

function lead(overrides: Partial<InsightsDlPortfolioLead> & { dl_id: number; dl_name: string }): InsightsDlPortfolioLead {
  return {
    is_active: true,
    requests: 0,
    vacancies: 0,
    placements: 0,
    hit_ratio: null,
    fill_rate: null,
    open_requests: 0,
    target_achieved: null,
    clients: [],
    ...overrides,
  };
}

const names = (rows: { name: string }[]) => rows.map((row) => row.name);

describe("nextColumnSort", () => {
  it("kolumna liczbowa zaczyna od malejącej, drugi klik rosnąco, trzeci znów malejąco", () => {
    const first = nextColumnSort(null, "placements", isNameColumn);
    expect(first).toEqual({ key: "placements", dir: "desc" });
    const second = nextColumnSort(first, "placements", isNameColumn);
    expect(second).toEqual({ key: "placements", dir: "asc" });
    expect(nextColumnSort(second, "placements", isNameColumn)).toEqual({
      key: "placements",
      dir: "desc",
    });
  });

  it("kolumna z nazwiskiem zaczyna rosnąco", () => {
    expect(nextColumnSort(null, "name", isNameColumn)).toEqual({ key: "name", dir: "asc" });
  });

  it("zmiana kolumny nie dziedziczy kierunku poprzedniej", () => {
    const asc = { key: "placements" as const, dir: "asc" as const };
    expect(nextColumnSort<"placements" | "interviews">(asc, "interviews", isNameColumn)).toEqual({
      key: "interviews",
      dir: "desc",
    });
  });
});

describe("sortRowsByColumn", () => {
  const rows = [
    person({ user_id: 1, name: "Żaneta Test", precision_pct: 40 }),
    person({ user_id: 2, name: "Anna Test", precision_pct: null }),
    person({ user_id: 3, name: "Łukasz Test", precision_pct: 90 }),
    person({ user_id: 4, name: "Jan Kowalski", precision_pct: 40 }),
  ];
  const byPrecision = (dir: "asc" | "desc") =>
    names(
      sortRowsByColumn(rows, (row) => teamPeopleSortValue(row, "precision_pct"), dir, (row) => row.name),
    );

  it("malejąco: najwyższe u góry, null na końcu", () => {
    expect(byPrecision("desc")).toEqual(["Łukasz Test", "Jan Kowalski", "Żaneta Test", "Anna Test"]);
  });

  it("rosnąco: null nadal na końcu, nie na górze", () => {
    expect(byPrecision("asc")).toEqual(["Jan Kowalski", "Żaneta Test", "Łukasz Test", "Anna Test"]);
  });

  it("remis rozstrzyga nazwisko rosnąco w obu kierunkach", () => {
    // Jan Kowalski i Żaneta Test mają po 40% — kolejność między nimi stała.
    const desc = byPrecision("desc");
    const asc = byPrecision("asc");
    expect(desc.indexOf("Jan Kowalski")).toBeLessThan(desc.indexOf("Żaneta Test"));
    expect(asc.indexOf("Jan Kowalski")).toBeLessThan(asc.indexOf("Żaneta Test"));
  });

  it("nazwiska po polsku: Ł po L, Ż na końcu", () => {
    const sorted = sortRowsByColumn(
      [...rows, person({ user_id: 5, name: "Lena Test" })],
      (row) => teamPeopleSortValue(row, "name"),
      "asc",
      (row) => row.name,
    );
    expect(names(sorted)).toEqual(["Anna Test", "Jan Kowalski", "Lena Test", "Łukasz Test", "Żaneta Test"]);
  });

  it("wiersz bez nazwiska stoi na końcu kolumny nazwisk w obu kierunkach", () => {
    const withBlank = [person({ user_id: 9, name: "" }), ...rows];
    for (const dir of ["asc", "desc"] as const) {
      const sorted = sortRowsByColumn(withBlank, (row) => teamPeopleSortValue(row, "name"), dir, (row) => row.name);
      expect(sorted.at(-1)!.user_id).toBe(9);
    }
  });

  it("nie zmienia tablicy wejściowej", () => {
    const before = names(rows);
    byPrecision("desc");
    expect(names(rows)).toEqual(before);
  });
});

describe("teamPeopleSortValue — „Placementy vs poprzednio”", () => {
  it("sortuje po różnicy placements − previous_placements, nie po samych placementach", () => {
    const rows = [
      person({ user_id: 1, name: "Anna Test", placements: 5, previous_placements: 5 }),
      person({ user_id: 2, name: "Jan Kowalski", placements: 2, previous_placements: 0 }),
      person({ user_id: 3, name: "Ewa Test", placements: 0, previous_placements: 3 }),
    ];
    expect(teamPeopleSortValue(rows[2]!, "placements_delta")).toBe(-3);
    const sorted = sortRowsByColumn(
      rows,
      (row) => teamPeopleSortValue(row, "placements_delta"),
      "desc",
      (row) => row.name,
    );
    expect(names(sorted)).toEqual(["Jan Kowalski", "Anna Test", "Ewa Test"]);
  });

  it("weryf./dzień `null` jest brakiem wartości, nie zerem", () => {
    expect(teamPeopleSortValue(person({ user_id: 1, name: "Anna Test" }), "verifications_per_workday")).toBeNull();
    expect(
      teamPeopleSortValue(person({ user_id: 1, name: "Anna Test", verifications_per_workday: 0 }), "verifications_per_workday"),
    ).toBe(0);
  });
});

describe("dlLeadSortValue", () => {
  it("hit ratio `null` na końcu w obu kierunkach", () => {
    const leads = [
      lead({ dl_id: 1, dl_name: "Anna Test", hit_ratio: null }),
      lead({ dl_id: 2, dl_name: "Jan Kowalski", hit_ratio: 20 }),
      lead({ dl_id: 3, dl_name: "Ewa Test", hit_ratio: 60 }),
    ];
    const order = (dir: "asc" | "desc") =>
      sortRowsByColumn(leads, (row) => dlLeadSortValue(row, "hit_ratio"), dir, (row) => row.dl_name).map(
        (row) => row.dl_id,
      );
    expect(order("desc")).toEqual([3, 2, 1]);
    expect(order("asc")).toEqual([2, 3, 1]);
  });
});

describe("splitFormerEmployees", () => {
  const rows = [
    person({ user_id: 1, name: "Anna Test" }),
    person({ user_id: 2, name: "Jan Kowalski", is_active: false }),
  ];

  it("domyślnie byli schodzą z listy osób", () => {
    const { people, former } = splitFormerEmployees(rows, false);
    expect(people.map((r) => r.user_id)).toEqual([1]);
    expect(former.map((r) => r.user_id)).toEqual([2]);
  });

  it("„Pokaż byłych” = wszyscy na liście, zbiór byłych pusty", () => {
    const { people, former } = splitFormerEmployees(rows, true);
    expect(people.map((r) => r.user_id)).toEqual([1, 2]);
    expect(former).toEqual([]);
  });

  it("wszyscy aktywni → brak byłych", () => {
    expect(splitFormerEmployees([rows[0]!], false).former).toEqual([]);
  });

  it("wszyscy byli → pusta lista osób", () => {
    const allFormer = rows.map((row) => ({ ...row, is_active: false }));
    const { people, former } = splitFormerEmployees(allFormer, false);
    expect(people).toEqual([]);
    expect(former).toHaveLength(2);
  });
});

describe("summarizeFormerEmployees", () => {
  const columns = {
    recommendations: (row: TeamPeopleRow) => row.recommendations,
    placements: (row: TeamPeopleRow) => row.placements,
  };

  it("brak byłych → brak wiersza", () => {
    expect(summarizeFormerEmployees([], (row: TeamPeopleRow) => row.name, columns)).toBeNull();
  });

  it("sumuje kolumny liczbowe i zbiera nazwiska alfabetycznie", () => {
    const summary = summarizeFormerEmployees(
      [
        person({ user_id: 1, name: "Jan Kowalski", recommendations: 3, placements: 1 }),
        person({ user_id: 2, name: "Anna Test", recommendations: 4, placements: 0 }),
      ],
      (row) => row.name,
      columns,
    );
    expect(summary).toEqual({
      count: 2,
      names: ["Anna Test", "Jan Kowalski"],
      sums: { recommendations: 7, placements: 1 },
    });
  });

  it("osoba bez nazwiska nadal się liczy", () => {
    const summary = summarizeFormerEmployees(
      [person({ user_id: 1, name: "", placements: 2 })],
      (row) => row.name,
      columns,
    );
    expect(summary?.count).toBe(1);
    expect(summary?.names).toEqual(["Nieznana osoba"]);
    expect(summary?.sums.placements).toBe(2);
  });
});
