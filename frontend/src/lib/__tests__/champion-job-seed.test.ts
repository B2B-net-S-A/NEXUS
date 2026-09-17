/**
 * M04-B02 (stack sprzed 09.2026) + PR 5 „proces tworzenia rekrutacji dla
 * Delivery Leada" (sekcja 1 „Podstawowe informacje" startuje z pól
 * rekrutacji, per pole).
 *
 * Profil sprzed 09.2026 ma pusty stack, a wymagania są w kolumnach
 * rekrutacji. Edytor pokazywał „Musi mieć · 0”, a dopisanie jednej pozycji
 * nadpisywało kolumny (zapis synchronizuje stack → kolumny).
 */

import { describe, expect, it } from "vitest";

import type { ChampionValidation } from "@/components/ChampionIntake";
import { EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import {
  championSavePayload,
  seedBasicsFromJob,
  seedChampionFromJob,
  seedStackFromJobColumns,
  withoutSeededStackConflict,
} from "@/lib/champion-job-seed";

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

describe("championSavePayload — stack", () => {
  it("nietknięty stack z kolumn NIE jedzie do serwera", () => {
    const { profile, seededStack } = seedStackFromJobColumns(legacy, jobValues);
    const payload = championSavePayload(profile, { seededStack, seededBasics: null });
    expect("stack" in payload).toBe(false);
  });

  it("edycja wczytanego stacku wysyła CAŁĄ listę, nie samą nową pozycję", () => {
    const { profile, seededStack } = seedStackFromJobColumns(legacy, jobValues);
    const edited: ChampionProfile = {
      ...profile,
      stack: { ...profile.stack, must: [...profile.stack.must, { name: "Linux" }] },
    };
    const payload = championSavePayload(edited, {
      seededStack,
      seededBasics: null,
    }) as ChampionProfile;
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

describe("seedBasicsFromJob", () => {
  it("seeduje każde puste pole osobno z kolumn rekrutacji", () => {
    const { profile, seededBasics } = seedBasicsFromJob(legacy, {
      role_name: "Senior Java Developer",
      rate_value: 150,
      work_mode: "remote",
      onsite_days_per_week: 2,
      candidate_location_pref: "Warszawa",
      deadline: "2026-09-18",
    });
    expect(profile.basics.role_name).toBe("Senior Java Developer");
    expect(profile.basics.rate_value).toBe(150);
    expect(profile.basics.work_mode).toBe("zdalnie");
    expect(profile.basics.onsite_days_per_week).toBe(2);
    expect(profile.basics.candidate_location_pref).toBe("Warszawa");
    expect(profile.basics.deadline).toBe("2026-09-18");
    expect(seededBasics).toEqual({
      role_name: "Senior Java Developer",
      rate_value: 150,
      work_mode: "zdalnie",
      onsite_days_per_week: 2,
      candidate_location_pref: "Warszawa",
      deadline: "2026-09-18",
    });
  });

  it("już wypełnione pole NIE jest nadpisywane, reszta jest seedowana osobno", () => {
    const filled: ChampionProfile = {
      ...legacy,
      basics: { ...legacy.basics, role_name: "Własna nazwa" },
    };
    const { profile, seededBasics } = seedBasicsFromJob(filled, {
      role_name: "Z rekrutacji",
      rate_value: 100,
    });
    expect(profile.basics.role_name).toBe("Własna nazwa");
    expect(profile.basics.rate_value).toBe(100);
    expect(seededBasics).toEqual({ rate_value: 100 });
  });

  it("nazwa roli bez własnej kolumny (backend sprzed PR 1) spada na tytuł rekrutacji", () => {
    const { profile, seededBasics } = seedBasicsFromJob(
      legacy,
      {},
      "Senior Python Developer",
    );
    expect(profile.basics.role_name).toBe("Senior Python Developer");
    expect(seededBasics).toEqual({ role_name: "Senior Python Developer" });
  });

  it("job_values.role_name wygrywa z tytułem rekrutacji, gdy oba są podane", () => {
    const { seededBasics } = seedBasicsFromJob(
      legacy,
      { role_name: "Z kolumny" },
      "Z tytułu",
    );
    expect(seededBasics?.role_name).toBe("Z kolumny");
  });

  it("nieznany enum trybu pracy NIE jest seedowany (select nie ma dla niego opcji)", () => {
    const { profile, seededBasics } = seedBasicsFromJob(legacy, {
      work_mode: "nieznany-enum",
    });
    expect(profile.basics.work_mode).toBeNull();
    expect(seededBasics).toBeNull();
  });

  it("puste/nieobecne kolumny (backend sprzed PR 1 dla deadline) = nic do wczytania", () => {
    const { profile, seededBasics } = seedBasicsFromJob(legacy, {});
    expect(profile).toBe(legacy);
    expect(profile.basics.deadline).toBeNull();
    expect(seededBasics).toBeNull();
  });
});

describe("seedChampionFromJob", () => {
  it("łączy seed stacku (wszystko-albo-nic) i sekcji 1 (per pole) w jednym wywołaniu", () => {
    const { profile, seededStack, seededBasics } = seedChampionFromJob(
      legacy,
      { must: "Python", nice: "", rate_value: 120 },
      "Senior Python Developer",
    );
    expect(profile.stack.must.map((i) => i.name)).toEqual(["Python"]);
    expect(profile.basics.rate_value).toBe(120);
    expect(profile.basics.role_name).toBe("Senior Python Developer");
    expect(seededStack).not.toBeNull();
    expect(seededBasics).toEqual({
      role_name: "Senior Python Developer",
      rate_value: 120,
    });
  });
});

describe("championSavePayload — sekcja 1 (Podstawowe informacje)", () => {
  it("nietknięte pola sekcji 1 NIE jadą do serwera", () => {
    const { profile, seededBasics } = seedBasicsFromJob(legacy, {
      rate_value: 120,
      role_name: "X",
    });
    const payload = championSavePayload(profile, {
      seededStack: null,
      seededBasics,
    }) as ChampionProfile;
    expect("rate_value" in payload.basics).toBe(false);
    expect("role_name" in payload.basics).toBe(false);
  });

  it("edycja JEDNEGO wczytanego pola wysyła TYLKO tę zmianę", () => {
    const { profile, seededBasics } = seedBasicsFromJob(legacy, {
      rate_value: 120,
      role_name: "X",
    });
    const edited: ChampionProfile = {
      ...profile,
      basics: { ...profile.basics, rate_value: 130 },
    };
    const payload = championSavePayload(edited, {
      seededStack: null,
      seededBasics,
    }) as ChampionProfile;
    expect(payload.basics.rate_value).toBe(130);
    expect("role_name" in payload.basics).toBe(false);
  });

  it("wycina jednocześnie nietknięty stack i nietknięte pola sekcji 1", () => {
    const { profile, seededStack, seededBasics } = seedChampionFromJob(legacy, {
      must: "Python",
      nice: "",
      rate_value: 120,
    });
    const payload = championSavePayload(profile, { seededStack, seededBasics });
    expect("stack" in payload).toBe(false);
    expect("rate_value" in (payload as ChampionProfile).basics).toBe(false);
  });
});
