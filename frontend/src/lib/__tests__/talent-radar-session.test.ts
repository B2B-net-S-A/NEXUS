import { describe, it, expect, beforeEach, vi } from "vitest";

import {
  TALENT_RADAR_SESSION_KEY,
  clearTalentRadarSession,
  loadTalentRadarSession,
  saveTalentRadarSession,
  type TalentRadarSessionState,
} from "@/lib/talent-radar-session";

/** Pełny, realistyczny snapshot — z klientem, wynikami i championem. */
const FULL_STATE: TalentRadarSessionState = {
  client: { id: 7, name: "Acme Sp. z o.o." },
  title: "Senior Python Developer",
  text: "Szukamy osoby z Pythonem, FastAPI i Postgresem — min. 5 lat.",
  budgetMax: "180",
  excludeRemoteOnly: true,
  location: "Warszawa",
  championSkills: { must: ["Java"], nice: ["AWS"] },
  championProfile: { role_name: "Senior Python Developer", must: ["python"] },
  championSummary: {
    role_name: "Senior Python Developer",
    must_count: 3,
    nice_count: 2,
    rate_value: 180,
    location: "Warszawa",
    work_mode: "hybrid",
  },
  response: {
    results: [
      {
        candidate_id: 101,
        total: 87,
        semantic: { points: 40, max: 60, reason: null },
        skills: { points: 10, max: 10, reason: null },
        salary: { points: null, max: null, reason: null, status: "not_applicable" },
        location: { points: 5, max: 5, reason: null },
        availability: { points: 5, max: 5, reason: null },
        champion_fit: { points: 0, max: 0, reason: null },
        matching_must: ["python", "fastapi"],
        gap_must: ["postgres"],
        matching_nice: ["docker"],
        gap_nice: [],
        penalties: [],
        fit_confidence: 0.8,
        candidate: {
          id: 101,
          name: "Jan",
          lastname: "Kowalski",
          location: "Warszawa",
          competence_category: "software_development",
          years_it_experience: 7,
          availability_status: "actively_looking",
          champion: false,
          avatar_url: null,
        },
      },
    ],
    meta: {
      pool_size: 1000,
      eligible_size: 800,
      returned: 1,
      degraded: false,
      reason: null,
    },
  },
};

beforeEach(() => {
  sessionStorage.clear();
});

describe("talent-radar-session", () => {
  it("round-trip: save → load zwraca ten sam snapshot", () => {
    saveTalentRadarSession(FULL_STATE);
    expect(loadTalentRadarSession()).toEqual(FULL_STATE);
  });

  it("round-trip pustego formularza (same nulle/defaulty)", () => {
    const empty: TalentRadarSessionState = {
      client: null,
      title: "",
      text: "",
      budgetMax: "",
      excludeRemoteOnly: false,
      location: "",
      championSkills: null,
      championProfile: null,
      championSummary: null,
      response: null,
    };
    saveTalentRadarSession(empty);
    expect(loadTalentRadarSession()).toEqual(empty);
  });

  it("brak zapisu → null", () => {
    expect(loadTalentRadarSession()).toBeNull();
  });

  it("zepsuty JSON → null, bez wyjątku", () => {
    sessionStorage.setItem(TALENT_RADAR_SESSION_KEY, "{nie-json");
    expect(loadTalentRadarSession()).toBeNull();
  });

  // Wersjonowany klucz chroni przed STARYM kluczem, ale nie przed zapisem
  // spod tej samej wersji o obcym kształcie (ręczna edycja, inna zakładka na
  // starym buildzie tuż po deployu). Walidacja musi odrzucić, nie „naprawić".
  it.each([
    ["nie-obiekt", JSON.stringify("tekst")],
    ["client bez id", JSON.stringify({ ...FULL_STATE, client: { name: "X" } })],
    [
      "response.results nie jest tablicą",
      JSON.stringify({
        ...FULL_STATE,
        response: { results: "zle", meta: {} },
      }),
    ],
    [
      "response bez meta",
      JSON.stringify({ ...FULL_STATE, response: { results: [] } }),
    ],
    ["text nie-string", JSON.stringify({ ...FULL_STATE, text: 42 })],
    [
      "excludeRemoteOnly nie-boolean",
      JSON.stringify({ ...FULL_STATE, excludeRemoteOnly: "tak" }),
    ],
  ])("obcy kształt (%s) → null", (_label, raw) => {
    sessionStorage.setItem(TALENT_RADAR_SESSION_KEY, raw);
    expect(loadTalentRadarSession()).toBeNull();
  });

  it("clear usuwa snapshot", () => {
    saveTalentRadarSession(FULL_STATE);
    clearTalentRadarSession();
    expect(sessionStorage.getItem(TALENT_RADAR_SESSION_KEY)).toBeNull();
  });

  it("save jest cichym no-opem, gdy storage rzuca (quota/tryb prywatny)", () => {
    const spy = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new Error("QuotaExceededError");
      });
    try {
      expect(() => saveTalentRadarSession(FULL_STATE)).not.toThrow();
    } finally {
      spy.mockRestore();
    }
  });

  it("load jest cichym null-em, gdy storage rzuca", () => {
    const spy = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new Error("SecurityError");
      });
    try {
      expect(loadTalentRadarSession()).toBeNull();
    } finally {
      spy.mockRestore();
    }
  });
});
