/**
 * M04-B02: profil Championa sprzed 09.2026 ma pusty stack, a wymagania są
 * w kolumnach rekrutacji. Edytor pokazywał „Musi mieć · 0”, a dopisanie jednej
 * pozycji nadpisywało kolumny (zapis synchronizuje stack → kolumny).
 */

import { describe, expect, it } from "vitest";

import type { ChampionValidation } from "@/components/ChampionIntake";
import { EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import {
  championSavePayload,
  seedStackFromJobColumns,
  withoutSeededStackConflict,
} from "@/lib/champion-legacy-stack";

const legacy: ChampionProfile = { ...EMPTY_CHAMPION_PROFILE };
const jobValues = { must: "Python\nPostgreSQL\nDocker", nice: "Kafka" };

describe("seedStackFromJobColumns", () => {
  it("pusty stack dostaje wymagania z kolumn rekrutacji", () => {
    const { profile, seededStack } = seedStackFromJobColumns(legacy, jobValues);
    expect(profile.stack.must.map((i) => i.name)).toEqual([
      "Python",
      "PostgreSQL",
      "Docker",
    ]);
    expect(profile.stack.nice.map((i) => i.name)).toEqual(["Kafka"]);
    expect(seededStack).not.toBeNull();
  });

  it("własny stack profilu zostaje nietknięty", () => {
    const own = { ...legacy, stack: { must: [{ name: "Go" }], nice: [], notes: "" } };
    const { profile, seededStack } = seedStackFromJobColumns(own, jobValues);
    expect(profile).toBe(own);
    expect(seededStack).toBeNull();
  });

  it("puste kolumny = nic do wczytania", () => {
    const { profile, seededStack } = seedStackFromJobColumns(legacy, {
      must: "",
      nice: "",
    });
    expect(profile).toBe(legacy);
    expect(seededStack).toBeNull();
  });
});

describe("championSavePayload", () => {
  it("nietknięty stack z kolumn NIE jedzie do serwera", () => {
    const { profile, seededStack } = seedStackFromJobColumns(legacy, jobValues);
    const payload = championSavePayload(profile, seededStack);
    expect("stack" in payload).toBe(false);
  });

  it("edycja wczytanego stacku wysyła CAŁĄ listę, nie samą nową pozycję", () => {
    const { profile, seededStack } = seedStackFromJobColumns(legacy, jobValues);
    const edited: ChampionProfile = {
      ...profile,
      stack: { ...profile.stack, must: [...profile.stack.must, { name: "Linux" }] },
    };
    const payload = championSavePayload(edited, seededStack) as ChampionProfile;
    expect(payload.stack.must.map((i) => i.name)).toEqual([
      "Python",
      "PostgreSQL",
      "Docker",
      "Linux",
    ]);
  });
});

describe("withoutSeededStackConflict", () => {
  const validation: ChampionValidation = {
    status: "draft",
    blocked_operations: ["search"],
    issues: [
      {
        code: "skill_column_conflict",
        path: "stack.must",
        message: "Profil i pola rekrutacji mają różne wymagania.",
        severity: "error",
        blocked_operations: ["search"],
      },
      {
        code: "missing_client",
        path: "client_id",
        message: "Wybierz klienta.",
        severity: "warning",
        blocked_operations: [],
      },
    ],
  };

  it("pomija konflikt stacku, gdy edytor pokazuje stack wczytany z kolumn", () => {
    const { seededStack } = seedStackFromJobColumns(legacy, jobValues);
    const result = withoutSeededStackConflict(validation, seededStack);
    expect(result?.issues.map((i) => i.code)).toEqual(["missing_client"]);
    expect(result?.blocked_operations).toEqual([]);
  });

  it("bez wczytanego stacku walidacja zostaje bez zmian", () => {
    expect(withoutSeededStackConflict(validation, null)).toBe(validation);
  });
});
