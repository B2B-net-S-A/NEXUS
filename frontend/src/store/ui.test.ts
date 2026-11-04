import { beforeEach, describe, expect, it } from "vitest";

import { useUiStore } from "@/store/ui";

describe("useUiStore — migracja v6", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("stan zapisany w v5 dostaje 50 wierszy na stronę, reszta zostaje", async () => {
    window.localStorage.setItem(
      "nexus-ui",
      JSON.stringify({
        state: {
          density: "compact",
          candidatesView: "tiles",
          jobsView: "list",
          columnPreferences: { "candidates-v2": ["rate"] },
          candidatesPageSize: 20,
        },
        version: 5,
      }),
    );

    await useUiStore.persist.rehydrate();

    const state = useUiStore.getState();
    expect(state.candidatesPageSize).toBe(50);
    // Pozostałe preferencje przechodzą bez zmian, a gęstość (usunięta w v9) znika.
    expect(state).not.toHaveProperty("density");
    expect(state.candidatesView).toBe("tiles");
    expect(state.columnPreferences).toEqual({ "candidates-v2": ["rate"] });
  });

  it("wybór rozmiaru strony w v6 nie jest nadpisywany przy odczycie", async () => {
    window.localStorage.setItem(
      "nexus-ui",
      JSON.stringify({ state: { candidatesPageSize: 100 }, version: 6 }),
    );
    await useUiStore.persist.rehydrate();
    expect(useUiStore.getState().candidatesPageSize).toBe(100);
  });
});

describe("useUiStore — migracja v8 (bez zwijanej kolumny filtrów rekrutacji)", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("stan z v7 traci pole zwijanej kolumny filtrów, reszta zostaje", () => {
    const migrate = useUiStore.persist.getOptions().migrate;
    const migrated = migrate!(
      { candidatesPageSize: 100, jobsView: "tiles", jobsFiltersCollapsed: true },
      7,
    ) as Record<string, unknown>;
    expect(migrated).toMatchObject({ candidatesPageSize: 100 });
    expect(migrated).not.toHaveProperty("jobsFiltersCollapsed");
  });
});

describe("useUiStore — migracja v10 (lista rekrutacji bez widoku kafelków)", () => {
  it("stan z v9 traci wybór „lista / kafelki”, reszta zostaje", () => {
    const migrate = useUiStore.persist.getOptions().migrate;
    const migrated = migrate!(
      { candidatesPageSize: 100, candidatesView: "tiles", jobsView: "tiles" },
      9,
    ) as Record<string, unknown>;
    expect(migrated).toMatchObject({ candidatesPageSize: 100, candidatesView: "tiles" });
    expect(migrated).not.toHaveProperty("jobsView");
  });
});

describe("useUiStore — migracja v11 (Tablica zawsze z pustymi kolumnami)", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("stan z v10 traci przełącznik pustych kolumn, reszta zostaje", () => {
    const migrate = useUiStore.persist.getOptions().migrate;
    const migrated = migrate!(
      { candidatesPageSize: 100, hideEmptyKanbanColumns: true },
      10,
    ) as Record<string, unknown>;
    expect(migrated).toMatchObject({ candidatesPageSize: 100 });
    expect(migrated).not.toHaveProperty("hideEmptyKanbanColumns");
  });

  it("odczyt zapisu z v10 nie zostawia pola w stanie", async () => {
    window.localStorage.setItem(
      "nexus-ui",
      JSON.stringify({ state: { hideEmptyKanbanColumns: true }, version: 10 }),
    );
    await useUiStore.persist.rehydrate();
    expect(useUiStore.getState()).not.toHaveProperty("hideEmptyKanbanColumns");
  });
});
