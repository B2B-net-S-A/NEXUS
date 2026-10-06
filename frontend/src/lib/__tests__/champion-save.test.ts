import { describe, expect, it } from "vitest";

import { EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import {
  blockerSection,
  championChangedPayload,
  championConflictFrom,
  changedSectionKeys,
} from "@/lib/champion-save";

const NO_SEED = { seededStack: null, seededBasics: null };

const base: ChampionProfile = {
  ...EMPTY_CHAMPION_PROFILE,
  basics: { ...EMPTY_CHAMPION_PROFILE.basics, role_name: "QA" },
  insights: [],
};

describe("championChangedPayload — tylko zmienione sekcje (audyt 06.10.2026, N2)", () => {
  it("bez zmian: sam odcisk; brak odcisku = pusty ładunek", () => {
    expect(championChangedPayload(base, base, NO_SEED, "h1")).toEqual({
      expected_profile_hash: "h1",
    });
    expect(championChangedPayload(base, base, NO_SEED, null)).toEqual({});
  });

  it("zmiana jednej sekcji wysyła tylko ją; notatki jadą wyłącznie przy ich zmianie", () => {
    const draft = { ...base, project: { ...base.project, about: "Nowy opis." } };
    expect(changedSectionKeys(draft, base)).toEqual(["project"]);
    const payload = championChangedPayload(draft, base, NO_SEED, "h1");
    expect(Object.keys(payload).sort()).toEqual(["expected_profile_hash", "project"]);

    const withNote = {
      ...base,
      insights: [{ id: "new-1", text: "Klient chce B2B.", source: "client" }],
    } as unknown as ChampionProfile;
    expect(Object.keys(championChangedPayload(withNote, base, NO_SEED, null))).toEqual([
      "insights",
    ]);
  });

  it("pole sekcji 1 wczytane z rekrutacji i nietknięte nie jedzie razem z edytowanym", () => {
    const seeded: ChampionProfile = {
      ...base,
      basics: { ...base.basics, rate_value: 120, work_mode: "zdalnie" },
    };
    const draft: ChampionProfile = { ...seeded, basics: { ...seeded.basics, rate_value: 150 } };
    const payload = championChangedPayload(
      draft,
      seeded,
      { seededStack: null, seededBasics: { rate_value: 120, work_mode: "zdalnie" } },
      null,
    ) as { basics: Record<string, unknown> };
    expect(payload.basics.rate_value).toBe(150);
    expect("work_mode" in payload.basics).toBe(false);
  });
});

describe("championConflictFrom", () => {
  const error = (status: number, detail: unknown) => ({ response: { status, data: { detail } } });

  it("rozpoznaje 409 `champion_profile_conflict` z profilem i odciskiem", () => {
    const conflict = championConflictFrom(
      error(409, {
        code: "champion_profile_conflict",
        message: "Ktoś zmienił profil.",
        champion_profile: { basics: { role_name: "Tester" } },
        profile_hash: "h9",
      }),
    );
    expect(conflict).toMatchObject({
      message: "Ktoś zmienił profil.",
      profile_hash: "h9",
      champion_profile: { basics: { role_name: "Tester" } },
    });
  });

  it("inny 409 (odcisk rekrutacji) i inne błędy to nie konflikt profilu", () => {
    expect(championConflictFrom(error(409, { message: "Rekrutacja zmieniła się." }))).toBeNull();
    expect(championConflictFrom(error(422, { code: "champion_profile_conflict" }))).toBeNull();
    expect(championConflictFrom(new Error("x"))).toBeNull();
  });
});

describe("blockerSection — gdzie usunąć brak bramki (N4)", () => {
  it("braki profilu prowadzą do sekcji, braki spoza profilu — nigdzie", () => {
    expect(blockerSection("questions")).toEqual({
      label: "6 · Pytania screeningowe",
      anchor: "champion-section-screening",
    });
    expect(blockerSection("budget")?.anchor).toBe("champion-section-basics");
    expect(blockerSection("hiring_manager")).toBeNull();
    expect(blockerSection("champion:rate_unresolved")).toBeNull();
  });
});
