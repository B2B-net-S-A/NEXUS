import { readFileSync } from "node:fs";
import { join } from "node:path";

import { QueryClient, type QueryKey } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ default: {} }));

import { BOARD_TASKS_QUERY_KEY } from "@/lib/api/boardTasks";
import { REQUEST_BOARD_QUERY_KEY } from "@/lib/api/requestAllocation";
import { invalidateJobTeam } from "@/lib/job-team-cache";

/** Zapytania tak, jak trzymają je ekrany (klucze z parametrami). */
const KEYS = {
  jobAsString: ["job", "5"],
  jobAsNumber: ["job", 5],
  otherJobAsString: ["job", "6"],
  otherJobAsNumber: ["job", 6],
  list: ["jobs-v2", "", 1, 0, "attention", 1],
  quickCounts: ["jobs-quick-counts", "2026-10-01"],
  board: [...REQUEST_BOARD_QUERY_KEY],
  boardTasks: [...BOARD_TASKS_QUERY_KEY],
  // Te zapytania nie zależą od obsady ani priorytetu.
  readiness: ["job-readiness", 5],
  categoryPeople: ["competence-category-recruiters", 3],
  candidates: ["candidates"],
} satisfies Record<string, QueryKey>;

function seededClient(): QueryClient {
  const qc = new QueryClient();
  for (const key of Object.values(KEYS)) qc.setQueryData(key, {});
  return qc;
}

function invalidated(qc: QueryClient): string[] {
  return Object.entries(KEYS)
    .filter(([, key]) => qc.getQueryState(key)?.isInvalidated)
    .map(([name]) => name)
    .sort();
}

describe("invalidateJobTeam", () => {
  it("odświeża rekrutację pod oboma kształtami klucza, listę, liczniki, pulpit i „Czeka na Ciebie”", () => {
    const qc = seededClient();

    invalidateJobTeam(qc, 5);

    expect(invalidated(qc)).toEqual(
      ["board", "boardTasks", "jobAsNumber", "jobAsString", "list", "quickCounts"].sort(),
    );
  });

  it("bez rekrutacji (decyzja zbiorcza) odświeża każdą wczytaną rekrutację", () => {
    const qc = seededClient();

    invalidateJobTeam(qc);

    expect(invalidated(qc)).toEqual(
      [
        "board",
        "boardTasks",
        "jobAsNumber",
        "jobAsString",
        "list",
        "otherJobAsNumber",
        "otherJobAsString",
        "quickCounts",
      ].sort(),
    );
  });

  it("klucze listy i liczników są tymi, pod którymi trzyma je ekran rekrutacji", () => {
    // Lista ma klucze w pliku ekranu — import całego ekranu do testu biblioteki
    // byłby ciężki, więc pilnujemy samych nazw.
    const screen = readFileSync(
      join(process.cwd(), "src/components/v2/pages/JobsListV2.tsx"),
      "utf8",
    );
    expect(screen).toMatch(/export function jobsListQueryKey[\s\S]{0,200}?"jobs-v2"/);
    expect(screen).toMatch(
      /export function jobsQuickCountsQueryKey[\s\S]{0,200}?"jobs-quick-counts"/,
    );
    expect(REQUEST_BOARD_QUERY_KEY).toEqual(["request-board"]);
    expect(BOARD_TASKS_QUERY_KEY).toEqual(["board-tasks"]);
  });
});
