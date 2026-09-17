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
  encodeJobsListUrl,
  initialDeadlineFromUrl,
  initialMineFromUrl,
  initialSortFromUrl,
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

describe("initialMineFromUrl", () => {
  it("„mine=1” włącza filtr moich rekrutacji", () => {
    expect(initialMineFromUrl(new URLSearchParams("mine=1"))).toBe(true);
  });

  it("„mine=0” go NIE włącza", () => {
    // Pulpit linkuje `mine=0` właśnie po to, żeby pokazać wszystkie —
    // potraktowanie samej obecności parametru jako `true` odwróciłoby sens linku.
    expect(initialMineFromUrl(new URLSearchParams("mine=0"))).toBe(false);
  });

  it("brak parametru = wyłączony", () => {
    expect(initialMineFromUrl(new URLSearchParams("status=published"))).toBe(false);
  });
});

// M03-B01: typ, termin i sortowanie żyły tylko w `useState` — F5 zwracało
// pełną listę. Test sprawdza obie strony: zapis do URL-a i odtworzenie.
describe("typ, termin, sortowanie w URL-u", () => {
  it("odtwarza wszystkie trzy filtry z adresu", () => {
    const params = new URLSearchParams("type=tender&deadline=none&sort=oldest");
    expect(initialTypeFromUrl(params)).toBe("tender");
    expect(initialDeadlineFromUrl(params)).toBe("none");
    expect(initialSortFromUrl(params)).toBe("oldest");
  });

  it("brak albo nieznana wartość = domyślna, nie 422", () => {
    const params = new URLSearchParams("type=sales&deadline=jutro&sort=");
    expect(initialTypeFromUrl(params)).toBe("all");
    expect(initialDeadlineFromUrl(params)).toBe("any");
    expect(initialSortFromUrl(params)).toBe("newest");
  });

  it("zapis → odczyt daje ten sam stan (przeżywa F5)", () => {
    const qs = encodeJobsListUrl({
      status: ["published", "draft"],
      mine: true,
      type: "body_leasing",
      deadline: "next7",
      sort: "deadline",
    });
    const params = new URLSearchParams(qs);
    expect(initialStatusFromUrl(params)).toEqual(["published", "draft"]);
    expect(initialMineFromUrl(params)).toBe(true);
    expect(initialTypeFromUrl(params)).toBe("body_leasing");
    expect(initialDeadlineFromUrl(params)).toBe("next7");
    expect(initialSortFromUrl(params)).toBe("deadline");
  });

  it("wartości domyślne nie zaśmiecają adresu", () => {
    expect(
      encodeJobsListUrl({
        status: [],
        mine: false,
        type: "all",
        deadline: "any",
        sort: "newest",
      }),
    ).toBe("");
  });

  it("zdejmuje nieaktualne wartości, zostawia cudze parametry", () => {
    const qs = encodeJobsListUrl(
      { status: [], mine: false, type: "tender", deadline: "any", sort: "newest" },
      new URLSearchParams("mine=0&status=published&type=body_leasing&foo=bar"),
    );
    const params = new URLSearchParams(qs);
    expect(params.getAll("status")).toEqual([]);
    expect(params.get("mine")).toBeNull();
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
    expect(mod.initialMineFromUrl(params)).toBe(true);
    expect(mod.initialTypeFromUrl(params)).toBe("tender");
    expect(mod.initialDeadlineFromUrl(params)).toBe("next7");
    expect(mod.initialSortFromUrl(params)).toBe("oldest");
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
        mine: false,
        type: "all",
        deadline: "any",
        sort: "newest",
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
