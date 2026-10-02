import { describe, expect, it } from "vitest";

import { visibleNavSections as sidebarVisibleNavSections } from "@/components/v2/shell/SidebarV2";
import {
  CAPABILITY_PERMISSIONS,
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

import { accessSnapshot } from "./fixtures/access-snapshot";

// Rejestr jest wspólnym źródłem sidebara i palety ⌘K. Ten plik pilnuje trzech
// rzeczy, które refaktor mógł po cichu zmienić: zgodności z rejestrem
// capability, DOKŁADNEJ listy pozycji per rola (zamrożonej ze starego, ręcznie
// pisanego `NAV_SECTIONS`) oraz tego, że paleta nie pokazuje więcej niż menu.
//
// `userOf(role)` to sama rola, czyli profil bez kompletu uprawnień z serwera:
// pozycje Delivery i Finansów widzą wtedy DOMYŚLNI posiadacze uprawnień.
// Co się dzieje po przełączeniu uprawnienia, pilnuje blok „menu idzie za
// uprawnieniem”.

const ALL_ROLES: UserRole[] = [
  "admin",
  "finance",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "recruiter",
  "user",
  "trainee",
];

/** Role z menu — praktykant (0374) ma własną powłokę bez nawigacji. */
const MENU_ROLES = ALL_ROLES.filter((role) => role !== "trainee");

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
    for (const role of MENU_ROLES) {
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
      ["Codzienna praca", ["Do przedzwonienia", "Akademia"]],
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

describe("rejestr nawigacji ↔ rejestr capability", () => {
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

    it(`${entry.href}: \`permission\` jest tym samym uprawnieniem co ${capability}`, () => {
      // Capability z uprawnienia nie ma listy ról — wpis menu też nie.
      expect(entry.permission).toBe(CAPABILITY_PERMISSIONS[capability]);
      if (entry.permission) expect(entry.roles).toBeUndefined();
    });

    it(`${entry.href}: widoczne dokładnie dla ról z ${capability}`, () => {
      // Użytkownik to sama rola, więc dla wpisów z uprawnieniem (Delivery,
      // Finanse) liczą się domyślni posiadacze uprawnienia.
      const seeing = ALL_ROLES.filter((role) =>
        visibleNavEntries(userOf(role), { contactQueueEnabled: true }).some(
          (visible) => visible.id === entry.id,
        ),
      );
      expect(sorted(seeing)).toEqual(
        sorted(ALL_ROLES.filter((role) => hasCapability(userOf(role), capability))),
      );
    });
  }

  it("Delivery i Finanse to wpisy z uprawnieniem — żaden nie zostaje przy samej sekcji", () => {
    const gated = NAV_REGISTRY.filter(
      (entry) => entry.section === "delivery" || entry.section === "finance",
    );
    expect(gated.map((entry) => [entry.id, entry.permission])).toEqual([
      ["clients", "delivery_view"],
      ["my-clients", "delivery_view"],
      ["order-mail", "delivery_view"],
      ["my-relationships", "delivery_view"],
      ["contracts", "delivery_view"],
      ["finance", "finance_module"],
    ]);
  });
});

describe("menu idzie za uprawnieniem, nie za rolą", () => {
  const opts = { contactQueueEnabled: false };
  const hrefs = (user: Parameters<typeof visibleNavHrefs>[0]) =>
    visibleNavHrefs(user, opts);
  const paletteIds = (user: Parameters<typeof visibleNavHrefs>[0]) =>
    visiblePaletteEntries(user, opts, (capability) =>
      hasCapability(user, capability),
    ).map((entry) => entry.id);

  it("rekruter z nadanym podglądem Delivery dostaje Klientów i Kontrakty (menu i paleta)", () => {
    const viewer = accessSnapshot("recruiter", { grant: ["delivery_view"] });
    expect(hrefs(viewer)).toEqual(expect.arrayContaining(["/clients", "/contracts"]));
    expect(hrefs(viewer)).not.toContain("/finance");
    expect(paletteIds(viewer)).toEqual(
      expect.arrayContaining([
        "clients",
        "my-clients",
        "order-mail",
        "my-relationships",
        "contracts",
      ]),
    );
    expect(
      visiblePrimaryGroups(viewer, opts).map((group) => group.title),
    ).toEqual(["Praca", "Klienci i umowy", "Firma"]);
  });

  it("Delivery Lead bez podglądu Delivery traci obie pozycje i grupę szyny", () => {
    const lead = accessSnapshot("delivery_lead", {
      revoke: [
        "delivery_view",
        "clients_edit",
        "contracts_orders_edit",
        "contract_status",
        "amounts_view",
      ],
    });
    expect(hrefs(lead)).not.toContain("/clients");
    expect(hrefs(lead)).not.toContain("/contracts");
    expect(paletteIds(lead)).not.toContain("clients");
    expect(
      visiblePrimaryGroups(lead, opts).map((group) => group.title),
    ).toEqual(["Praca", "Firma"]);
  });

  it("„Finanse” widzi posiadacz „Moduł Finanse”, kto by nim nie był", () => {
    const granted = accessSnapshot("head_of_recruitment", { grant: ["finance_module"] });
    expect(hrefs(granted)).toContain("/finance");
    expect(paletteIds(granted)).toContain("finance");

    const revoked = accessSnapshot("finance", { revoke: ["finance_module"] });
    expect(hrefs(revoked)).not.toContain("/finance");
    expect(paletteIds(revoked)).not.toContain("finance");
    // Kontrakty zostają: „Kontrakty i zamówienia” Finanse mają nadal.
    expect(hrefs(revoked)).toContain("/contracts");
  });

  it("stary profil z samą sekcją Delivery (bez uprawnienia) nie pokazuje pozycji", () => {
    // Wyjątek sekcji sprzed 0410 już niczego nie otwiera — dostęp do Delivery
    // wynika z uprawnień. Bez tego menu prowadziłoby do ekranu z samymi 403.
    const legacy = {
      role: "recruiter" as const,
      roles: ["recruiter" as const],
      effective_section_access: {
        sourcing: "write" as const,
        pipeline: "write" as const,
        delivery: "read" as const,
        insights: "read" as const,
        finance: "read" as const,
        system_admin: "none" as const,
      },
    };
    expect(hrefs(legacy)).not.toContain("/clients");
    expect(hrefs(legacy)).not.toContain("/contracts");
    expect(hrefs(legacy)).not.toContain("/finance");
  });

  it("sufit sekcji zostaje: uprawnienie przy sekcji ograniczonej do zera nie pokazuje pozycji", () => {
    const capped = accessSnapshot("delivery_lead", { sectionCaps: { delivery: "none" } });
    expect(hrefs(capped)).not.toContain("/clients");
    expect(hrefs(capped)).not.toContain("/contracts");
  });
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
  // Akademia (0369) — w „Więcej”, ta sama bramka co Kalendarz.
  const PIPELINE = ["/jobs", "/calendar", "/academy"];
  // Panel „Praktykanci” (0374) — tylko admin i Head of Recruitment.
  const PIPELINE_WITH_TRAINEES = [...PIPELINE, "/trainees"];
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
      ...PIPELINE_WITH_TRAINEES,
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
      ...PIPELINE_WITH_TRAINEES,
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
    // Praktykant (0374): jeden ekran, bez menu — nawet bez Pomocy i Ustawień.
    trainee: [],
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
      sorted(["talent_community_manager", "recruiter"]),
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
  it("praktykant nie ma palety — ani jednej pozycji", () => {
    const trainee = userOf("trainee");
    expect(
      visiblePaletteEntries(trainee, { contactQueueEnabled: true }, () => true),
    ).toEqual([]);
  });

  for (const role of MENU_ROLES) {
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
