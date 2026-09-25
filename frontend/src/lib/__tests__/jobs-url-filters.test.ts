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
} from "@/lib/jobs-url-filters";
import { initialStagesFromUrl } from "@/lib/request-stage";

describe("stan requestu w adresie (pasek filtrów, 25.09.2026)", () => {
  it("czyta pigułki `stage` (powtarzalne, bez duplikatów)", () => {
    expect(
      initialStagesFromUrl(new URLSearchParams("stage=searching&stage=client_silent&stage=searching")),
    ).toEqual(["searching", "client_silent"]);
  });

  it("stare `rs` / `ws` mapują się na pigułki, a wartości bez pigułki odpadają", () => {
    expect(
      initialStagesFromUrl(
        new URLSearchParams("rs=champion&rs=filled&ws=to_review&ws=finished&ws=searching"),
      ),
    ).toEqual(["champion", "to_review", "searching"]);
  });

  it("nieznana wartość to brak zawężenia, nie 422", () => {
    expect(initialStagesFromUrl(new URLSearchParams("stage=cokolwiek&stage=closed"))).toEqual([]);
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
    const base = { status: [], deadline: "any" } as const;
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
    const base = { status: [], deadline: "any", defaultScope: "mine" } as const;
    expect(encodeJobsListUrl({ ...base, scope: "mine", sort: "attention" })).toBe("");
    expect(encodeJobsListUrl({ ...base, scope: "mine", sort: "newest" })).toBe("sort=newest");
    expect(encodeJobsListUrl({ ...base, scope: "all", sort: "attention" })).toBe(
      "mine=0&sort=attention",
    );
  });
});

// M03-B01: termin i sortowanie żyły tylko w `useState` — F5 zwracało
// pełną listę. Test sprawdza obie strony: zapis do URL-a i odtworzenie.
describe("termin, sortowanie w URL-u", () => {
  it("odtwarza filtry z adresu", () => {
    const params = new URLSearchParams("deadline=none&sort=oldest");
    expect(initialDeadlineFromUrl(params)).toBe("none");
    expect(sortOverrideFromUrl(params)).toBe("oldest");
  });

  it("brak albo nieznana wartość = domyślna, nie 422", () => {
    const params = new URLSearchParams("deadline=jutro&sort=");
    expect(initialDeadlineFromUrl(params)).toBe("any");
    // Brak wyboru = sortowanie idzie za zakresem.
    expect(sortOverrideFromUrl(params)).toBeNull();
  });

  it("zapis → odczyt daje ten sam stan (przeżywa F5)", () => {
    const qs = encodeJobsListUrl({
      scope: "mine",
      defaultScope: "open",
      deadline: "next7",
      sort: "deadline",
    });
    const params = new URLSearchParams(qs);
    expect(scopeOverrideFromUrl(params)).toBe("mine");
    expect(initialDeadlineFromUrl(params)).toBe("next7");
    expect(sortOverrideFromUrl(params)).toBe("deadline");
  });

  it("wartości domyślne nie zaśmiecają adresu", () => {
    expect(
      encodeJobsListUrl({
        scope: "mine",
        defaultScope: "mine",
        deadline: "any",
        sort: "attention",
      }),
    ).toBe("");
  });

  it("zdejmuje nieaktualne wartości, zostawia cudze parametry", () => {
    const qs = encodeJobsListUrl(
      { scope: "all", defaultScope: "mine", deadline: "any", sort: "newest" },
      new URLSearchParams(
        "mine=0&status=published&type=body_leasing&responsible=4&sourcing=1" +
          "&active_search=1&no_owner=1&priority=assigned&rs=filled&ws=finished&foo=bar",
      ),
    );
    const params = new URLSearchParams(qs);
    expect(params.getAll("status")).toEqual([]);
    // Jawne „Wszystkie" ZOSTAJE w adresie (inaczej F5 wracałoby do „Moich").
    expect(params.get("mine")).toBe("0");
    // Kolumna filtrów sprzed 25.09.2026: stare klucze znikają z adresu.
    for (const key of [
      "type",
      "responsible",
      "sourcing",
      "active_search",
      "no_owner",
      "priority",
      "rs",
      "ws",
    ]) {
      expect(params.get(key), key).toBeNull();
    }
    expect(params.get("foo")).toBe("bar");
  });
});

describe("pozostałe filtry listy w URL-u (audyt 17.09.2026)", () => {
  it("zapisuje i odtwarza wszystkie filtry", async () => {
    const mod = await import("@/lib/jobs-url-filters");
    const qs = mod.encodeJobsListUrl({
      scope: "open",
      defaultScope: "mine",
      deadline: "range",
      deadlineRange: { from: "2026-10-01", to: "2026-10-31" },
      sort: "oldest",
      q: "  java  ",
      stages: ["searching", "client_silent"],
      clientIds: [12],
      ccIds: [3],
      deliveryLeadIds: [21, 22],
      workedBy: [4, 9],
      nobodyWorking: true,
      sent: "3",
    });
    const params = new URLSearchParams(qs);
    expect(mod.scopeOverrideFromUrl(params)).toBe("open");
    expect(mod.initialDeadlineFromUrl(params)).toBe("range");
    expect(mod.initialDeadlineRangeFromUrl(params)).toEqual({
      from: "2026-10-01",
      to: "2026-10-31",
    });
    expect(initialStagesFromUrl(params)).toEqual(["searching", "client_silent"]);
    expect(mod.initialIdsFromUrl(params, "lead")).toEqual([21, 22]);
    expect(mod.initialSentFromUrl(params)).toBe("3");
    expect(mod.sortOverrideFromUrl(params)).toBe("oldest");
    expect(mod.initialSearchFromUrl(params)).toBe("java");
    expect(mod.initialIdsFromUrl(params, "who")).toEqual([4, 9]);
    expect(mod.initialIdsFromUrl(params, "client")).toEqual([12]);
    expect(mod.initialIdsFromUrl(params, "cc")).toEqual([3]);
    expect(mod.initialFlagFromUrl(params, "nobody")).toBe(true);
  });

  it("wartości domyślne nie trafiają do adresu, a obce parametry zostają", async () => {
    const mod = await import("@/lib/jobs-url-filters");
    const qs = mod.encodeJobsListUrl(
      {
        scope: "mine",
        defaultScope: "mine",
        deadline: "any",
        sort: "attention",
        q: "",
        stages: [],
        clientIds: [],
        ccIds: [],
        workedBy: [],
        nobodyWorking: false,
      },
      new URLSearchParams(
        "q=stare&client=5&lead=3&sent=1&dl_from=2026-01-01&stage=searching&who=2&nobody=1&utm=x",
      ),
    );
    expect(qs).toBe("utm=x");
  });

  it("śmieci w identyfikatorach i przełączniku to brak zawężenia", async () => {
    const mod = await import("@/lib/jobs-url-filters");
    const params = new URLSearchParams("client=abc&client=-2&client=7&client=7&nobody=tak");
    expect(mod.initialIdsFromUrl(params, "client")).toEqual([7]);
    expect(mod.initialFlagFromUrl(params, "nobody")).toBe(false);
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
