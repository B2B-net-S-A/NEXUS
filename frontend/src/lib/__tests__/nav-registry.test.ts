import { describe, expect, it } from "vitest";

import { visibleNavSections as sidebarVisibleNavSections } from "@/components/v2/shell/SidebarV2";
import {
  CAPABILITY_ROLES,
  hasCapability,
  type Capability,
} from "@/lib/capabilities";
import {
  NAV_MORE_GROUPS,
  NAV_PRIMARY_GROUPS,
  NAV_PRIMARY_ORDER,
  NAV_REGISTRY,
  NAV_SECTION_META,
  resolveNavHref,
  visibleMoreGroups,
  visibleNavEntries,
  visibleNavHrefs,
  visibleNavSections,
  visiblePaletteEntries,
  visiblePrimaryGroups,
  visiblePrimaryNav,
} from "@/lib/nav-registry";
import type { UserRole } from "@/store/auth";

// Rejestr jest wspólnym źródłem sidebara i palety ⌘K. Ten plik pilnuje trzech
// rzeczy, które refaktor mógł po cichu zmienić: zgodności z rejestrem
// capability, DOKŁADNEJ listy pozycji per rola (zamrożonej ze starego, ręcznie
// pisanego `NAV_SECTIONS`) oraz tego, że paleta nie pokazuje więcej niż menu.

const ALL_ROLES: UserRole[] = [
  "admin",
  "finance",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "tac",
  "recruiter",
  "sourcer",
  "user",
];

const sorted = (roles: readonly UserRole[]) => [...roles].sort();

function userOf(role: UserRole) {
  return { role, roles: [role] };
}

function sidebarHrefs(role: UserRole, contactQueueEnabled = false): string[] {
  return visibleNavSections(userOf(role), { contactQueueEnabled }).flatMap(
    (section) => section.items.map((item) => item.href),
  );
}

describe("rejestr nawigacji — spójność wpisów", () => {
  it("id i href są unikalne, a każda sekcja istnieje", () => {
    const ids = NAV_REGISTRY.map((entry) => entry.id);
    const hrefs = NAV_REGISTRY.map((entry) => entry.href);
    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(hrefs).size).toBe(hrefs.length);
    const sectionKeys = new Set(NAV_SECTION_META.map((meta) => meta.key));
    for (const entry of NAV_REGISTRY) {
      expect(sectionKeys.has(entry.section)).toBe(true);
    }
  });

  it("każda pozycja „Więcej” ma grupę z rejestru grup, a `primary` jej nie ma", () => {
    const groupKeys = new Set(NAV_MORE_GROUPS.map((group) => group.key));
    for (const entry of NAV_REGISTRY) {
      if (entry.placement === "more") {
        expect(entry.moreGroup, entry.id).toBeDefined();
        expect(groupKeys.has(entry.moreGroup!)).toBe(true);
      } else {
        expect(entry.moreGroup, entry.id).toBeUndefined();
      }
    }
  });

  it("grupy szyny wymieniają DOKŁADNIE pozycje szyny, każdą raz (bez tylko-paletowych)", () => {
    const railIds = NAV_REGISTRY.filter(
      (entry) => entry.placement === "primary" && entry.inSidebar !== false,
    ).map((entry) => entry.id);
    const grouped = NAV_PRIMARY_GROUPS.flatMap((group) => group.ids);
    expect([...grouped].sort()).toEqual([...railIds].sort());
    expect(new Set(grouped).size).toBe(grouped.length);
    expect(NAV_PRIMARY_ORDER).toEqual(grouped);
  });

  it("grupy szyny: Praca · Klienci i umowy · Firma, w tej kolejności", () => {
    expect(
      NAV_PRIMARY_GROUPS.map((group) => [group.title, [...group.ids]]),
    ).toEqual([
      ["Praca", ["dashboard", "jobs", "candidates", "calendar"]],
      ["Klienci i umowy", ["clients", "contracts", "finance"]],
      ["Firma", ["insights"]],
    ]);
  });
});

describe("szyna i „Więcej” (rekrutacja v3)", () => {
  const opts = { contactQueueEnabled: true };
  const primaryHrefs = (role: UserRole) =>
    visiblePrimaryNav(userOf(role), opts).map((entry) => entry.href);

  const groupsOf = (role: UserRole) =>
    visiblePrimaryGroups(userOf(role), opts).map((group) => [
      group.title,
      group.items.map((item) => item.href),
    ]);

  it("rekruter ma na szynie „Praca” + „Firma” (samo Insights), bez pustej grupy klientów", () => {
    expect(groupsOf("recruiter")).toEqual([
      ["Praca", ["/dashboard", "/jobs", "/candidates", "/calendar"]],
      ["Firma", ["/insights"]],
    ]);
    expect(primaryHrefs("recruiter")).toEqual([
      "/dashboard",
      "/jobs",
      "/candidates",
      "/calendar",
      "/insights",
    ]);
  });

  it("Delivery Lead: klienci i umowy bez Finansów; finance i admin: wszystkie trzy grupy", () => {
    expect(groupsOf("delivery_lead")).toEqual([
      ["Praca", ["/dashboard", "/jobs", "/candidates", "/calendar"]],
      ["Klienci i umowy", ["/clients", "/contracts"]],
      ["Firma", ["/insights"]],
    ]);
    const full = [
      ["Praca", ["/dashboard", "/jobs", "/candidates", "/calendar"]],
      ["Klienci i umowy", ["/clients", "/contracts", "/finance"]],
      ["Firma", ["/insights"]],
    ];
    expect(groupsOf("finance")).toEqual(full);
    expect(groupsOf("admin")).toEqual(full);
    for (const role of ALL_ROLES) {
      for (const group of visiblePrimaryGroups(userOf(role), opts)) {
        expect(group.items.length).toBeGreaterThan(0);
      }
    }
  });

  it("Panel klientów, Moje relacje i Zamówienia z maila są trybami, nie pozycjami menu", () => {
    for (const role of ALL_ROLES) {
      const hrefs = visibleNavHrefs(userOf(role), opts);
      for (const legacy of ["/my-clients", "/my-relationships", "/order-mail"]) {
        expect(hrefs).not.toContain(legacy);
      }
      expect(
        hrefs.some((href) => href.startsWith("/clients?") || href.startsWith("/contracts?")),
      ).toBe(false);
    }
  });

  it("Wyszukiwarka i Talent Radar zniknęły z menu (tryby ekranu Kandydaci)", () => {
    for (const role of ALL_ROLES) {
      const hrefs = visibleNavHrefs(userOf(role), opts);
      expect(hrefs).not.toContain("/talent-radar");
      expect(hrefs.some((href) => href.startsWith("/candidates?mode="))).toBe(false);
      expect(hrefs).not.toContain("/candidates/search");
    }
  });

  it("persony Delivery / Finanse / admin zachowują swój rdzeń na szynie", () => {
    expect(primaryHrefs("delivery_lead")).toEqual(
      expect.arrayContaining(["/clients", "/contracts", "/insights"]),
    );
    expect(primaryHrefs("finance")).toEqual(
      expect.arrayContaining(["/clients", "/contracts", "/finance"]),
    );
    expect(primaryHrefs("admin")).toEqual([
      "/dashboard",
      "/jobs",
      "/candidates",
      "/calendar",
      "/clients",
      "/contracts",
      "/finance",
      "/insights",
    ]);
    // Bramka jest ta sama co dotąd — szyna niczego nie odsłania.
    expect(primaryHrefs("recruiter")).not.toContain("/clients");
    expect(primaryHrefs("delivery_lead")).not.toContain("/finance");
  });

  it("„Więcej” grupuje resztę; puste grupy odpadają", () => {
    const groups = visibleMoreGroups(userOf("recruiter"), opts);
    expect(groups.map((group) => [group.title, group.items.map((i) => i.label)])).toEqual([
      ["Codzienna praca", ["Do przedzwonienia"]],
      ["Dokumenty", ["Generator CV", "Generator Umów B2B"]],
      ["System", ["Pomoc", "Ustawienia"]],
    ]);
    const admin = visibleMoreGroups(userOf("admin"), opts);
    // „Baza i źródła” opustoszała: Talenty i Targ ukryte (21.09), Panel
    // klientów i Moje relacje to od 22.09 tryby ekranu Klienci.
    expect(
      admin.find((group) => group.key === "sources"),
    ).toBeUndefined();
    for (const role of ALL_ROLES) {
      for (const group of visibleMoreGroups(userOf(role), opts)) {
        expect(group.items.length).toBeGreaterThan(0);
      }
    }
  });

  it("szyna + „Więcej” = DOKŁADNIE to, co menu pokazywało przed podziałem", () => {
    for (const role of ALL_ROLES) {
      for (const contactQueueEnabled of [true, false]) {
        const union = visibleNavHrefs(userOf(role), { contactQueueEnabled });
        expect(new Set(union).size).toBe(union.length);
        expect([...union].sort()).toEqual(
          [...sidebarHrefs(role, contactQueueEnabled)].sort(),
        );
      }
    }
  });
});

describe("rejestr nawigacji ↔ CAPABILITY_ROLES", () => {
  const withCapability = NAV_REGISTRY.filter((entry) => entry.capability);

  it("są wpisy z capability (test nie przechodzi na pustym zbiorze)", () => {
    expect(withCapability.length).toBeGreaterThan(5);
  });

  for (const entry of withCapability) {
    const capability = entry.capability as Capability;

    it(`${entry.href}: jawne \`roles\` są lustrem ${capability}`, () => {
      if (!entry.roles) return;
      expect(sorted(entry.roles)).toEqual(sorted(CAPABILITY_ROLES[capability]));
    });

    it(`${entry.href}: widoczne dokładnie dla ról z ${capability}`, () => {
      // Obejmuje też wpisy BEZ `roles` (bramkowane samą sekcją, np. Delivery
      // i Finanse) — tam lustrem jest domyślna polityka sekcji.
      const seeing = ALL_ROLES.filter((role) =>
        visibleNavEntries(userOf(role), { contactQueueEnabled: true }).some(
          (visible) => visible.id === entry.id,
        ),
      );
      expect(sorted(seeing)).toEqual(sorted(CAPABILITY_ROLES[capability]));
    });
  }
});

describe("menu (szyna + „Więcej”, sekcjami) — pozycje per rola identyczne jak przed refaktorem", () => {
  // Zamrożone z ręcznie pisanego `NAV_SECTIONS` (stan sprzed rejestru),
  // w kolejności menu, przy WYŁĄCZONEJ fladze kolejki telefonów.
  // Bez Wyszukiwarki i Talent Radaru — od 21.09.2026 to tryby ekranu
  // „Kandydaci”, dostępne z palety ⌘K, nie z menu.
  const SOURCING_OPERATIONAL = [
    "/dashboard",
    "/candidates",
    "/cv-generator",
    "/contracts/b2b-generator",
    // „/talents" i „/sourcing/marketplace" zdjęte z menu 21.09.2026.
  ];
  const PIPELINE = ["/jobs", "/calendar"];
  const DELIVERY = ["/clients", "/contracts"];
  const INSIGHTS = ["/insights"];
  const SYSTEM = ["/help", "/settings"];

  const EXPECTED: Partial<Record<UserRole, string[]>> = {
    recruiter: [
      ...SOURCING_OPERATIONAL,
      ...PIPELINE,
      ...INSIGHTS,
      ...SYSTEM,
    ],
    delivery_lead: [
      ...SOURCING_OPERATIONAL,
      ...PIPELINE,
      ...DELIVERY,
      ...INSIGHTS,
      ...SYSTEM,
    ],
    admin: [
      ...SOURCING_OPERATIONAL,
      ...PIPELINE,
      ...DELIVERY,
      ...INSIGHTS,
      "/finance",
      ...SYSTEM,
    ],
    finance: [
      ...SOURCING_OPERATIONAL,
      ...PIPELINE,
      ...DELIVERY,
      ...INSIGHTS,
      "/finance",
      ...SYSTEM,
    ],
    // HoR nie rozpatruje zgłoszeń (UAT A-B02) i nie ma sekcji Delivery.
    head_of_recruitment: [
      ...SOURCING_OPERATIONAL,
      ...PIPELINE,
      ...INSIGHTS,
      ...SYSTEM,
    ],
    // Legacy viewer (0 kont): Kalendarz i Generator CV zdjęte 22.09.2026 —
    // backend (RecruitmentReadAccess / CandidateWriteAccess) i tak go odcina.
    user: [
      "/dashboard",
      "/contracts/b2b-generator",
      "/jobs",
      "/insights",
      ...SYSTEM,
    ],
  };

  for (const [role, expected] of Object.entries(EXPECTED) as Array<
    [UserRole, string[]]
  >) {
    it(`${role}`, () => {
      expect(sidebarHrefs(role)).toEqual(expected);
    });
  }

  it("flaga kolejki telefonów dokłada pozycję tylko rolom dzwoniącym", () => {
    const withQueue = (role: UserRole) =>
      sidebarHrefs(role, true).includes("/candidates/contact-queue");
    expect(ALL_ROLES.filter(withQueue).sort()).toEqual(
      sorted(["talent_community_manager", "tac", "recruiter", "sourcer"]),
    );
    // Pozycja stoi tuż za „Kandydaci” (Wyszukiwarka zeszła z menu).
    const recruiter = sidebarHrefs("recruiter", true);
    expect(recruiter.indexOf("/candidates/contact-queue")).toBe(
      recruiter.indexOf("/candidates") + 1,
    );
    for (const role of ALL_ROLES) {
      expect(sidebarHrefs(role, false)).not.toContain(
        "/candidates/contact-queue",
      );
    }
  });

  it("tytuły i kolejność sekcji bez zmian", () => {
    expect(
      visibleNavSections(userOf("admin"), { contactQueueEnabled: false }).map(
        (section) => section.title,
      ),
    ).toEqual(["Sourcing", "Pipeline", "Delivery", "Insights", "Finanse", "System"]);
  });

  it("SidebarV2 re-eksportuje TĘ SAMĄ funkcję (jedno źródło, nie kopia)", () => {
    expect(sidebarVisibleNavSections).toBe(visibleNavSections);
  });
});

describe("paleta ⌘K ⊆ sidebar", () => {
  for (const role of ALL_ROLES) {
    for (const contactQueueEnabled of [true, false]) {
      it(`${role} (kolejka: ${contactQueueEnabled})`, () => {
        const user = userOf(role);
        const sidebar = new Set(sidebarHrefs(role, contactQueueEnabled));
        const palette = visiblePaletteEntries(
          user,
          { contactQueueEnabled },
          (capability) => hasCapability(user, capability),
        );
        expect(palette.length).toBeGreaterThan(0);
        for (const entry of palette) {
          // Jedyny wyjątek: pozycje tylko-paletowe (`inSidebar: false`).
          if (entry.inSidebar === false) continue;
          expect(sidebar.has(entry.href)).toBe(true);
        }
        // Przy domyślnej polityce ról capability niczego nie ukrywa, więc
        // paleta pokazuje KAŻDĄ pozycję menu oznaczoną `inPalette`.
        expect(
          palette.filter((entry) => entry.inSidebar !== false).map((entry) => entry.href),
        ).toEqual(
          [...sidebar].filter((href) =>
            NAV_REGISTRY.some((entry) => entry.href === href && entry.inPalette),
          ),
        );
      });
    }
  }

  it("Panel managera nie wraca do palety — `/manager` przekierowuje na pulpit", () => {
    const admin = userOf("admin");
    const palette = visiblePaletteEntries(admin, { contactQueueEnabled: false }, (c) =>
      hasCapability(admin, c),
    );
    expect(palette.some((entry) => entry.href === "/manager")).toBe(false);
    expect(NAV_REGISTRY.some((entry) => entry.href === "/manager")).toBe(false);
  });

  const paletteHref = (role: UserRole, id: string) => {
    const user = userOf(role);
    const entry = visiblePaletteEntries(user, { contactQueueEnabled: false }, (c) =>
      hasCapability(user, c),
    ).find((candidate) => candidate.id === id);
    return entry ? resolveNavHref(entry, user as never) : undefined;
  };

  it("Wyszukiwarka i Talent Radar zostają w palecie jako tryby ekranu Kandydaci", () => {
    expect(paletteHref("recruiter", "candidate-search")).toBe("/candidates?mode=search");
    expect(paletteHref("recruiter", "talent-radar")).toBe("/candidates?mode=request");
    const radar = NAV_REGISTRY.find((entry) => entry.id === "talent-radar")!;
    expect(radar.label).toBe("Szukaj z treści requestu (Talent Radar)");
    expect(radar.paletteKeywords).toEqual(
      expect.arrayContaining(["talent radar", "radar"]),
    );
    const search = NAV_REGISTRY.find((entry) => entry.id === "candidate-search")!;
    expect(search.label).toBe("Wyszukiwarka kandydatów");
    expect(search.paletteKeywords).toContain("wyszukiwarka");
  });

  it("bez `nav.candidates` Talent Radar prowadzi na samodzielną stronę /talent-radar", () => {
    // Radar jest dla KAŻDEJ roli (19.08), a /candidates tylko dla `nav.candidates`.
    expect(hasCapability(userOf("user"), "nav.candidates")).toBe(false);
    expect(paletteHref("user", "talent-radar")).toBe("/talent-radar");
    expect(paletteHref("user", "candidate-search")).toBeUndefined();
    // Odebrana sekcja Sourcing też odcina /candidates — adres wraca do radaru.
    const noSourcing = {
      role: "recruiter" as const,
      roles: ["recruiter" as const],
      effective_section_access: {
        sourcing: "none" as const,
        pipeline: "write" as const,
        delivery: "none" as const,
        insights: "read" as const,
        finance: "none" as const,
        system_admin: "none" as const,
      },
    };
    const radar = NAV_REGISTRY.find((entry) => entry.id === "talent-radar")!;
    expect(resolveNavHref(radar, noSourcing as never)).toBe("/talent-radar");
  });

  it("Dashboard prowadzi do dashboardu roli, nie do `/`", () => {
    const dashboard = NAV_REGISTRY.find((entry) => entry.id === "dashboard");
    expect(dashboard).toBeDefined();
    const href = resolveNavHref(dashboard!, userOf("recruiter") as never);
    expect(href).not.toBe("/");
    expect(href.startsWith("/dashboard")).toBe(true);
  });
});

describe("Talenty i Targ zdjęte z nawigacji (21.09.2026)", () => {
  const opts = { contactQueueEnabled: true };
  it("nie ma ich w menu ani w palecie dla żadnej roli, strony dalej istnieją", () => {
    for (const role of ALL_ROLES) {
      const user = userOf(role);
      const hrefs = [
        ...visibleNavHrefs(user, opts),
        ...visiblePaletteEntries(user, opts, () => true).map((e) => e.href),
      ];
      expect(hrefs).not.toContain("/talents");
      expect(hrefs).not.toContain("/sourcing/marketplace");
    }
  });
});
