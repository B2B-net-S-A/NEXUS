/**
 * Deep-linki do listy ofert były atrapą.
 *
 * Pulpit prowadzi na `/jobs?mine=0&status=published`, a `JobsListV2` startował
 * z pustymi filtrami i te parametry ignorował. Użytkownik dostawał WSZYSTKIE
 * oferty (z Draftami włącznie) i nie miał żadnego sygnału, że kliknięty filtr
 * nie zadziałał — lista wyglądała poprawnie, tylko pokazywała co innego.
 *
 * Test importuje PRAWDZIWE funkcje, których używa komponent. Wcześniejsza
 * wersja odtwarzała je inline i przez to sprawdzała własną kopię.
 */

import { describe, expect, it } from "vitest";

import {
  defaultSortForScope,
  encodeJobsListUrl,
  initialDeadlineFromUrl,
  defaultMineForUser,
  mineOverrideFromUrl,
  resolveMine,
  sortOverrideFromUrl,
  initialStatusFromUrl,
  initialTypeFromUrl,
} from "@/lib/jobs-url-filters";

describe("initialStatusFromUrl", () => {
  it("czyta pojedynczy status z deep-linka pulpitu", () => {
    expect(
      initialStatusFromUrl(new URLSearchParams("mine=0&status=published")),
    ).toEqual(["published"]);
  });

  it("czyta wielokrotny status (API łączy je przez OR)", () => {
    expect(
      initialStatusFromUrl(new URLSearchParams("status=published&status=draft")),
    ).toEqual(["published", "draft"]);
  });

  it("odrzuca wartości spoza kontraktu zamiast wysyłać je do API", () => {
    // Ręcznie podrasowany URL ma dać pusty filtr, nie 422 z backendu.
    expect(
      initialStatusFromUrl(
        new URLSearchParams("status=archived&status=published&status="),
      ),
    ).toEqual(["published"]);
  });

  it("brak parametru = brak filtra", () => {
    expect(initialStatusFromUrl(new URLSearchParams(""))).toEqual([]);
    expect(initialStatusFromUrl(new URLSearchParams("mine=1"))).toEqual([]);
  });
});

const userOf = (...roles: string[]) =>
  ({ role: roles[0], roles }) as Parameters<typeof defaultMineForUser>[0];

describe("domyślny zakres zależy od ROLI (rekrutacja v3)", () => {
  it("role prowadzące rekrutacje startują w „Moich”", () => {
    for (const role of [
      "recruiter",
      "sourcer",
      "tac",
      "talent_community_manager",
      "delivery_lead",
    ]) {
      expect(defaultMineForUser(userOf(role)), role).toBe(true);
    }
  });

  it("admin, HoR, Finanse i viewer startują we „Wszystkich”", () => {
    for (const role of ["admin", "head_of_recruitment", "finance", "user"]) {
      expect(defaultMineForUser(userOf(role)), role).toBe(false);
    }
    expect(defaultMineForUser(null)).toBe(false);
  });

  it("konto wielorolowe z KTÓRĄKOLWIEK rolą prowadzącą dostaje „Moje”", () => {
    expect(defaultMineForUser(userOf("admin", "recruiter"))).toBe(true);
    expect(defaultMineForUser(userOf("head_of_recruitment", "delivery_lead"))).toBe(true);
    expect(defaultMineForUser(userOf("admin", "finance"))).toBe(false);
  });

  it("jawne mine=0/1 z adresu ZAWSZE wygrywa z domyślnym roli", () => {
    expect(mineOverrideFromUrl(new URLSearchParams("mine=1"))).toBe(true);
    expect(mineOverrideFromUrl(new URLSearchParams("mine=0"))).toBe(false);
    expect(mineOverrideFromUrl(new URLSearchParams("status=published"))).toBeNull();
    expect(mineOverrideFromUrl(new URLSearchParams("mine=tak"))).toBeNull();

    expect(resolveMine(false, userOf("recruiter"))).toBe(false);
    expect(resolveMine(true, userOf("admin"))).toBe(true);
    expect(resolveMine(null, userOf("recruiter"))).toBe(true);
    expect(resolveMine(null, userOf("admin"))).toBe(false);
  });

  it("do adresu trafia tylko zakres INNY niż domyślny roli — i przeżywa odczyt", () => {
    const base = { status: [], type: "all", deadline: "any" } as const;
    // rekruter: „Wszystkie" jawnie, „Moje" czysto
    expect(
      encodeJobsListUrl({ ...base, mine: false, defaultMine: true, sort: "newest" }),
    ).toBe("mine=0");
    expect(
      encodeJobsListUrl({ ...base, mine: true, defaultMine: true, sort: "attention" }),
    ).toBe("");
    // admin: odwrotnie
    expect(
      encodeJobsListUrl({ ...base, mine: true, defaultMine: false, sort: "attention" }),
    ).toBe("mine=1");
    expect(
      encodeJobsListUrl({ ...base, mine: false, defaultMine: false, sort: "newest" }),
    ).toBe("");
    expect(mineOverrideFromUrl(new URLSearchParams("mine=1"))).toBe(true);
  });
});

describe("domyślne sortowanie idzie za zakresem", () => {
  it("„Moje” → „Wymaga uwagi”, „Wszystkie” → od najnowszej", () => {
    expect(defaultSortForScope(true)).toBe("attention");
    expect(defaultSortForScope(false)).toBe("newest");
    expect(sortOverrideFromUrl(new URLSearchParams(""))).toBeNull();
    expect(sortOverrideFromUrl(new URLSearchParams("sort=attention"))).toBe("attention");
  });

  it("domyślne sortowanie zakresu nie trafia do adresu, inne — tak", () => {
    const base = { status: [], type: "all", deadline: "any", defaultMine: true } as const;
    expect(encodeJobsListUrl({ ...base, mine: true, sort: "attention" })).toBe("");
    expect(encodeJobsListUrl({ ...base, mine: true, sort: "newest" })).toBe("sort=newest");
    expect(encodeJobsListUrl({ ...base, mine: false, sort: "attention" })).toBe(
      "mine=0&sort=attention",
    );
  });
});

// M03-B01: typ, termin i sortowanie żyły tylko w `useState` — F5 zwracało
// pełną listę. Test sprawdza obie strony: zapis do URL-a i odtworzenie.
describe("typ, termin, sortowanie w URL-u", () => {
  it("odtwarza wszystkie trzy filtry z adresu", () => {
    const params = new URLSearchParams("type=tender&deadline=none&sort=oldest");
    expect(initialTypeFromUrl(params)).toBe("tender");
    expect(initialDeadlineFromUrl(params)).toBe("none");
    expect(sortOverrideFromUrl(params)).toBe("oldest");
  });

  it("brak albo nieznana wartość = domyślna, nie 422", () => {
    const params = new URLSearchParams("type=sales&deadline=jutro&sort=");
    expect(initialTypeFromUrl(params)).toBe("all");
    expect(initialDeadlineFromUrl(params)).toBe("any");
    // Brak wyboru = sortowanie idzie za zakresem.
    expect(sortOverrideFromUrl(params)).toBeNull();
  });

  it("zapis → odczyt daje ten sam stan (przeżywa F5)", () => {
    const qs = encodeJobsListUrl({
      status: ["published", "draft"],
      mine: true,
      defaultMine: false,
      type: "body_leasing",
      deadline: "next7",
      sort: "deadline",
    });
    const params = new URLSearchParams(qs);
    expect(initialStatusFromUrl(params)).toEqual(["published", "draft"]);
    expect(mineOverrideFromUrl(params)).toBe(true);
    expect(initialTypeFromUrl(params)).toBe("body_leasing");
    expect(initialDeadlineFromUrl(params)).toBe("next7");
    expect(sortOverrideFromUrl(params)).toBe("deadline");
  });

  it("wartości domyślne nie zaśmiecają adresu", () => {
    expect(
      encodeJobsListUrl({
        status: [],
        mine: true,
        defaultMine: true,
        type: "all",
        deadline: "any",
        sort: "attention",
      }),
    ).toBe("");
  });

  it("zdejmuje nieaktualne wartości, zostawia cudze parametry", () => {
    const qs = encodeJobsListUrl(
      { status: [], mine: false, defaultMine: true, type: "tender", deadline: "any", sort: "newest" },
      new URLSearchParams("mine=0&status=published&type=body_leasing&foo=bar"),
    );
    const params = new URLSearchParams(qs);
    expect(params.getAll("status")).toEqual([]);
    // Jawne „Wszystkie" ZOSTAJE w adresie (inaczej F5 wracałoby do „Moich").
    expect(params.get("mine")).toBe("0");
    expect(params.get("type")).toBe("tender");
    expect(params.get("foo")).toBe("bar");
  });
});

describe("pozostałe filtry listy w URL-u (audyt 17.09.2026)", () => {
  it("zapisuje i odtwarza wszystkie 14 filtrów", async () => {
    const mod = await import("@/lib/jobs-url-filters");
    const qs = mod.encodeJobsListUrl({
      status: ["published"],
      mine: true,
      defaultMine: false,
      type: "tender",
      deadline: "next7",
      sort: "oldest",
      q: "  java  ",
      responsibleIds: [4, 9],
      clientIds: [12],
      ccIds: [3],
      needsSourcing: true,
      activeInSearch: true,
      openOnly: true,
      noOwnerOnly: true,
      priorityWork: "carry_over",
    });
    const params = new URLSearchParams(qs);
    expect(mod.initialStatusFromUrl(params)).toEqual(["published"]);
    expect(mod.mineOverrideFromUrl(params)).toBe(true);
    expect(mod.initialTypeFromUrl(params)).toBe("tender");
    expect(mod.initialDeadlineFromUrl(params)).toBe("next7");
    expect(mod.sortOverrideFromUrl(params)).toBe("oldest");
    expect(mod.initialSearchFromUrl(params)).toBe("java");
    expect(mod.initialIdsFromUrl(params, "responsible")).toEqual([4, 9]);
    expect(mod.initialIdsFromUrl(params, "client")).toEqual([12]);
    expect(mod.initialIdsFromUrl(params, "cc")).toEqual([3]);
    expect(mod.initialFlagFromUrl(params, "sourcing")).toBe(true);
    expect(mod.initialFlagFromUrl(params, "active_search")).toBe(true);
    expect(mod.initialFlagFromUrl(params, "open")).toBe(true);
    expect(mod.initialFlagFromUrl(params, "no_owner")).toBe(true);
    expect(mod.initialPriorityWorkFromUrl(params)).toBe("carry_over");
  });

  it("wartości domyślne nie trafiają do adresu, a obce parametry zostają", async () => {
    const mod = await import("@/lib/jobs-url-filters");
    const qs = mod.encodeJobsListUrl(
      {
        status: [],
        mine: true,
        defaultMine: true,
        type: "all",
        deadline: "any",
        sort: "attention",
        q: "",
        responsibleIds: [],
        clientIds: [],
        ccIds: [],
        priorityWork: "any",
      },
      new URLSearchParams("q=stare&client=5&utm=x"),
    );
    expect(qs).toBe("utm=x");
  });

  it("śmieci w identyfikatorach i priorytecie to brak zawężenia", async () => {
    const mod = await import("@/lib/jobs-url-filters");
    const params = new URLSearchParams(
      "client=abc&client=-2&client=7&client=7&priority=hack",
    );
    expect(mod.initialIdsFromUrl(params, "client")).toEqual([7]);
    expect(mod.initialPriorityWorkFromUrl(params)).toBe("any");
  });
});
