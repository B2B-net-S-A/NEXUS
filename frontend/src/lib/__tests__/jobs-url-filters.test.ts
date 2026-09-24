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
  deadlineQueryParams,
  defaultScopeForUser,
  defaultSortForScope,
  encodeJobsListUrl,
  initialDeadlineFromUrl,
  initialDeadlineRangeFromUrl,
  initialSentFromUrl,
  resolveScope,
  scopeOverrideFromUrl,
  scopeQueryFlags,
  sentQueryParams,
  sortOverrideFromUrl,
  initialStatusFromUrl,
  initialTypeFromUrl,
  scopeForStatuses,
  statusesForScope,
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
  ({ role: roles[0], roles }) as Parameters<typeof defaultScopeForUser>[0];

describe("domyślny zakres zależy od ROLI (lista v5: Moje | Otwarte | Wszystkie)", () => {
  it("role prowadzące rekrutacje startują w „Moich”", () => {
    for (const role of [
      "recruiter",
      "sourcer",
      "tac",
      "talent_community_manager",
      "delivery_lead",
    ]) {
      expect(defaultScopeForUser(userOf(role)), role).toBe("mine");
    }
  });

  it("admin, HoR, Finanse i viewer startują w „Otwartych”, nie w całym rejestrze", () => {
    for (const role of ["admin", "head_of_recruitment", "finance", "user"]) {
      expect(defaultScopeForUser(userOf(role)), role).toBe("open");
    }
    expect(defaultScopeForUser(null)).toBe("open");
  });

  it("konto wielorolowe z KTÓRĄKOLWIEK rolą prowadzącą dostaje „Moje”", () => {
    expect(defaultScopeForUser(userOf("admin", "recruiter"))).toBe("mine");
    expect(defaultScopeForUser(userOf("head_of_recruitment", "delivery_lead"))).toBe("mine");
    expect(defaultScopeForUser(userOf("admin", "finance"))).toBe("open");
  });

  it("jawny zakres z adresu ZAWSZE wygrywa z domyślnym roli; stare mine=0 = „Wszystkie”", () => {
    expect(scopeOverrideFromUrl(new URLSearchParams("mine=1"))).toBe("mine");
    expect(scopeOverrideFromUrl(new URLSearchParams("open=1"))).toBe("open");
    // Deep-link pulpitu sprzed listy v5 — nadal cały rejestr.
    expect(scopeOverrideFromUrl(new URLSearchParams("mine=0&status=published"))).toBe("all");
    // Dawny przełącznik „Niezamknięte” obok „Wszystkich” = „Otwarte”.
    expect(scopeOverrideFromUrl(new URLSearchParams("mine=0&open=1"))).toBe("open");
    // „Moje” wygrywa z dawnym „Niezamknięte” (zakres „Moje” jest węższy).
    expect(scopeOverrideFromUrl(new URLSearchParams("mine=1&open=1"))).toBe("mine");
    expect(scopeOverrideFromUrl(new URLSearchParams("status=published"))).toBeNull();
    expect(scopeOverrideFromUrl(new URLSearchParams("mine=tak&open=0"))).toBeNull();

    expect(resolveScope("all", userOf("recruiter"))).toBe("all");
    expect(resolveScope("mine", userOf("admin"))).toBe("mine");
    expect(resolveScope(null, userOf("recruiter"))).toBe("mine");
    expect(resolveScope(null, userOf("admin"))).toBe("open");
  });

  it("zakres → parametry API: „Otwarte” = open_only, „Wszystkie” = bez zawężenia", () => {
    expect(scopeQueryFlags("mine")).toEqual({ mine: true, openOnly: false });
    expect(scopeQueryFlags("open")).toEqual({ mine: false, openOnly: true });
    expect(scopeQueryFlags("all")).toEqual({ mine: false, openOnly: false });
  });

  it("do adresu trafia tylko zakres INNY niż domyślny roli — i przeżywa odczyt", () => {
    const base = { status: [], type: "all", deadline: "any" } as const;
    // rekruter (domyślnie „Moje”)
    expect(
      encodeJobsListUrl({ ...base, scope: "all", defaultScope: "mine", sort: "newest" }),
    ).toBe("mine=0");
    expect(
      encodeJobsListUrl({ ...base, scope: "open", defaultScope: "mine", sort: "newest" }),
    ).toBe("open=1");
    expect(
      encodeJobsListUrl({ ...base, scope: "mine", defaultScope: "mine", sort: "attention" }),
    ).toBe("");
    // admin (domyślnie „Otwarte”)
    expect(
      encodeJobsListUrl({ ...base, scope: "mine", defaultScope: "open", sort: "attention" }),
    ).toBe("mine=1");
    expect(
      encodeJobsListUrl({ ...base, scope: "all", defaultScope: "open", sort: "newest" }),
    ).toBe("mine=0");
    expect(
      encodeJobsListUrl({ ...base, scope: "open", defaultScope: "open", sort: "newest" }),
    ).toBe("");
    for (const scope of ["mine", "open", "all"] as const) {
      const qs = encodeJobsListUrl({ ...base, scope, defaultScope: "mine", sort: "newest" });
      expect(scopeOverrideFromUrl(new URLSearchParams(qs)) ?? "mine", scope).toBe(scope);
    }
  });
});

describe("domyślne sortowanie idzie za zakresem", () => {
  it("„Moje” → „Wymaga uwagi”, „Otwarte”/„Wszystkie” → od najnowszej", () => {
    expect(defaultSortForScope("mine")).toBe("attention");
    expect(defaultSortForScope("open")).toBe("newest");
    expect(defaultSortForScope("all")).toBe("newest");
    expect(sortOverrideFromUrl(new URLSearchParams(""))).toBeNull();
    expect(sortOverrideFromUrl(new URLSearchParams("sort=attention"))).toBe("attention");
  });

  it("domyślne sortowanie zakresu nie trafia do adresu, inne — tak", () => {
    const base = { status: [], type: "all", deadline: "any", defaultScope: "mine" } as const;
    expect(encodeJobsListUrl({ ...base, scope: "mine", sort: "attention" })).toBe("");
    expect(encodeJobsListUrl({ ...base, scope: "mine", sort: "newest" })).toBe("sort=newest");
    expect(encodeJobsListUrl({ ...base, scope: "all", sort: "attention" })).toBe(
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
      scope: "mine",
      defaultScope: "open",
      type: "body_leasing",
      deadline: "next7",
      sort: "deadline",
    });
    const params = new URLSearchParams(qs);
    expect(initialStatusFromUrl(params)).toEqual(["published", "draft"]);
    expect(scopeOverrideFromUrl(params)).toBe("mine");
    expect(initialTypeFromUrl(params)).toBe("body_leasing");
    expect(initialDeadlineFromUrl(params)).toBe("next7");
    expect(sortOverrideFromUrl(params)).toBe("deadline");
  });

  it("wartości domyślne nie zaśmiecają adresu", () => {
    expect(
      encodeJobsListUrl({
        status: [],
        scope: "mine",
        defaultScope: "mine",
        type: "all",
        deadline: "any",
        sort: "attention",
      }),
    ).toBe("");
  });

  it("zdejmuje nieaktualne wartości, zostawia cudze parametry", () => {
    const qs = encodeJobsListUrl(
      { status: [], scope: "all", defaultScope: "mine", type: "tender", deadline: "any", sort: "newest" },
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
  it("zapisuje i odtwarza wszystkie filtry", async () => {
    const mod = await import("@/lib/jobs-url-filters");
    const qs = mod.encodeJobsListUrl({
      status: ["published"],
      scope: "open",
      defaultScope: "mine",
      type: "tender",
      deadline: "range",
      deadlineRange: { from: "2026-10-01", to: "2026-10-31" },
      sort: "oldest",
      q: "  java  ",
      responsibleIds: [4, 9],
      clientIds: [12],
      ccIds: [3],
      deliveryLeadIds: [21, 22],
      sent: "3",
      needsSourcing: true,
      activeInSearch: true,
      noOwnerOnly: true,
      priorityWork: "carry_over",
    });
    const params = new URLSearchParams(qs);
    expect(mod.initialStatusFromUrl(params)).toEqual(["published"]);
    expect(mod.scopeOverrideFromUrl(params)).toBe("open");
    expect(mod.initialTypeFromUrl(params)).toBe("tender");
    expect(mod.initialDeadlineFromUrl(params)).toBe("range");
    expect(mod.initialDeadlineRangeFromUrl(params)).toEqual({
      from: "2026-10-01",
      to: "2026-10-31",
    });
    expect(mod.initialIdsFromUrl(params, "lead")).toEqual([21, 22]);
    expect(mod.initialSentFromUrl(params)).toBe("3");
    expect(mod.sortOverrideFromUrl(params)).toBe("oldest");
    expect(mod.initialSearchFromUrl(params)).toBe("java");
    expect(mod.initialIdsFromUrl(params, "responsible")).toEqual([4, 9]);
    expect(mod.initialIdsFromUrl(params, "client")).toEqual([12]);
    expect(mod.initialIdsFromUrl(params, "cc")).toEqual([3]);
    expect(mod.initialFlagFromUrl(params, "sourcing")).toBe(true);
    expect(mod.initialFlagFromUrl(params, "active_search")).toBe(true);
    expect(mod.initialFlagFromUrl(params, "no_owner")).toBe(true);
    expect(mod.initialPriorityWorkFromUrl(params)).toBe("carry_over");
  });

  it("wartości domyślne nie trafiają do adresu, a obce parametry zostają", async () => {
    const mod = await import("@/lib/jobs-url-filters");
    const qs = mod.encodeJobsListUrl(
      {
        status: [],
        scope: "mine",
        defaultScope: "mine",
        type: "all",
        deadline: "any",
        sort: "attention",
        q: "",
        responsibleIds: [],
        clientIds: [],
        ccIds: [],
        priorityWork: "any",
      },
      new URLSearchParams("q=stare&client=5&lead=3&sent=1&dl_from=2026-01-01&utm=x"),
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

describe("termin: presety → parametry API (lista v5)", () => {
  // Środa 24.09.2026, 23:30 czasu lokalnego — pułapka UTC o północy.
  const now = new Date(2026, 8, 24, 23, 30);

  it("„Po terminie” = termin najpóźniej wczoraj", () => {
    expect(deadlineQueryParams("overdue", {}, now)).toEqual({ deadline_to: "2026-09-23" });
  });

  it("„W tym tygodniu” = od dziś do niedzieli (minione dni to już „po terminie”)", () => {
    expect(deadlineQueryParams("this_week", {}, now)).toEqual({
      deadline_from: "2026-09-24",
      deadline_to: "2026-09-27",
    });
    // W niedzielę tydzień kończy się dziś.
    expect(deadlineQueryParams("this_week", {}, new Date(2026, 8, 27, 12))).toEqual({
      deadline_from: "2026-09-27",
      deadline_to: "2026-09-27",
    });
  });

  it("„Do 14 dni”, 7 i 30 dni liczą od dziś włącznie", () => {
    expect(deadlineQueryParams("next14", {}, now)).toEqual({
      deadline_from: "2026-09-24",
      deadline_to: "2026-10-08",
    });
    expect(deadlineQueryParams("next7", {}, now).deadline_to).toBe("2026-10-01");
  });

  it("z terminem / bez terminu / dowolny", () => {
    expect(deadlineQueryParams("none", {}, now)).toEqual({ has_deadline: false });
    expect(deadlineQueryParams("has", {}, now)).toEqual({ has_deadline: true });
    expect(deadlineQueryParams("any", {}, now)).toEqual({});
  });

  it("„Zakres dat” wysyła tylko poprawne granice, niepoprawne pomija (nie 422)", () => {
    expect(
      deadlineQueryParams("range", { from: "2026-10-01", to: "2026-10-31" }, now),
    ).toEqual({ deadline_from: "2026-10-01", deadline_to: "2026-10-31" });
    expect(deadlineQueryParams("range", { from: "2026-10-01" }, now)).toEqual({
      deadline_from: "2026-10-01",
    });
    expect(deadlineQueryParams("range", { to: "31.10.2026" }, now)).toEqual({});
  });

  it("zakres dat trafia do adresu tylko przy presecie „Zakres dat”", () => {
    const base = {
      status: [],
      scope: "mine",
      defaultScope: "mine",
      type: "all",
      sort: "attention",
      deadlineRange: { from: "2026-10-01", to: "2026-10-31" },
    } as const;
    expect(encodeJobsListUrl({ ...base, deadline: "range" })).toBe(
      "deadline=range&dl_from=2026-10-01&dl_to=2026-10-31",
    );
    expect(encodeJobsListUrl({ ...base, deadline: "overdue" })).toBe("deadline=overdue");
    expect(initialDeadlineRangeFromUrl(new URLSearchParams("dl_from=jutro"))).toEqual({
      from: undefined,
      to: undefined,
    });
  });
});

describe("„Wysłanych do klienta” → min_sent / max_sent", () => {
  it("mapuje wartości filtra na parametry backendu (liczba OSÓB)", () => {
    expect(sentQueryParams("any")).toEqual({});
    expect(sentQueryParams("none")).toEqual({ max_sent: 0 });
    expect(sentQueryParams("1")).toEqual({ min_sent: 1 });
    expect(sentQueryParams("3")).toEqual({ min_sent: 3 });
    expect(sentQueryParams("5")).toEqual({ min_sent: 5 });
  });

  it("nieznana wartość w adresie = dowolnie", () => {
    expect(initialSentFromUrl(new URLSearchParams("sent=100"))).toBe("any");
    expect(initialSentFromUrl(new URLSearchParams("sent=none"))).toBe("none");
  });
});

describe("zakres a status „Zamknięta”", () => {
  it("„Otwarte” + „Zamknięta” = „Wszystkie”; „Moje” i „Wszystkie” bez zmian", () => {
    expect(scopeForStatuses("open", ["closed"])).toBe("all");
    expect(scopeForStatuses("open", ["published"])).toBe("open");
    expect(scopeForStatuses("mine", ["closed"])).toBe("mine");
    expect(scopeForStatuses("all", ["closed"])).toBe("all");
  });

  it("jawne „Otwarte” zdejmuje „Zamknięta”, inne zakresy zostawiają status", () => {
    expect(statusesForScope("open", ["closed", "draft"])).toEqual(["draft"]);
    expect(statusesForScope("mine", ["closed"])).toEqual(["closed"]);
  });
});
