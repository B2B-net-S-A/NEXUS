import { beforeEach, describe, expect, it } from "vitest";

import { useUiStore } from "@/store/ui";

describe("useUiStore — migracja v6", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("stan zapisany w v5 dostaje ukryte puste kolumny i 50 wierszy na stronę", async () => {
    window.localStorage.setItem(
      "nexus-ui",
      JSON.stringify({
        state: {
          density: "compact",
          candidatesView: "tiles",
          jobsView: "list",
          columnPreferences: { "candidates-v2": ["rate"] },
          hideEmptyKanbanColumns: false,
        },
        version: 5,
      }),
    );

    await useUiStore.persist.rehydrate();

    const state = useUiStore.getState();
    expect(state.hideEmptyKanbanColumns).toBe(true);
    expect(state.candidatesPageSize).toBe(50);
    // Pozostałe preferencje przechodzą bez zmian.
    expect(state.density).toBe("compact");
    expect(state.candidatesView).toBe("tiles");
    expect(state.columnPreferences).toEqual({ "candidates-v2": ["rate"] });
  });

  it("migrate z v5 ustawia oba pola bez gubienia reszty", () => {
    const migrate = useUiStore.persist.getOptions().migrate;
    expect(migrate).toBeTypeOf("function");
    const migrated = migrate!(
      { density: "cozy", hideEmptyKanbanColumns: false },
      5,
    ) as Record<string, unknown>;
    expect(migrated).toMatchObject({
      density: "cozy",
      hideEmptyKanbanColumns: true,
      candidatesPageSize: 50,
    });
  });

  it("wybór rozmiaru strony w v6 nie jest nadpisywany przy odczycie", async () => {
    window.localStorage.setItem(
      "nexus-ui",
      JSON.stringify({
        state: { candidatesPageSize: 100, hideEmptyKanbanColumns: false },
        version: 6,
      }),
    );
    await useUiStore.persist.rehydrate();
    expect(useUiStore.getState().candidatesPageSize).toBe(100);
    expect(useUiStore.getState().hideEmptyKanbanColumns).toBe(false);
  });
});

describe("useUiStore — migracja v7 (zwijana kolumna filtrów rekrutacji)", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("stan z v6 dostaje `null` = „brak wyboru, domyślne wg szerokości okna”", () => {
    const migrate = useUiStore.persist.getOptions().migrate;
    const migrated = migrate!(
      { candidatesPageSize: 100, jobsView: "tiles" },
      6,
    ) as Record<string, unknown>;
    expect(migrated).toMatchObject({
      candidatesPageSize: 100,
      jobsView: "tiles",
      jobsFiltersCollapsed: null,
    });
  });

  it("świadomy wybór przeżywa odczyt z localStorage", async () => {
    window.localStorage.setItem(
      "nexus-ui",
      JSON.stringify({ state: { jobsFiltersCollapsed: true }, version: 7 }),
    );
    await useUiStore.persist.rehydrate();
    expect(useUiStore.getState().jobsFiltersCollapsed).toBe(true);
  });
});
