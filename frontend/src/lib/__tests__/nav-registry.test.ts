import { describe, expect, it } from "vitest";

import { visibleNavSections as sidebarVisibleNavSections } from "@/components/v2/shell/SidebarV2";
import {
  CAPABILITY_ROLES,
  hasCapability,
  type Capability,
} from "@/lib/capabilities";
import {
  NAV_REGISTRY,
  NAV_SECTION_META,
  resolveNavHref,
  visibleNavEntries,
  visibleNavSections,
  visiblePaletteEntries,
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

  it("na razie każda pozycja jest `primary` — zero zmian wizualnych", () => {
    expect(
      NAV_REGISTRY.filter((entry) => entry.placement !== "primary").map(
        (entry) => entry.id,
      ),
    ).toEqual([]);
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

describe("sidebar — pozycje per rola identyczne jak przed refaktorem", () => {
  // Zamrożone z ręcznie pisanego `NAV_SECTIONS` (stan sprzed rejestru),
  // w kolejności menu, przy WYŁĄCZONEJ fladze kolejki telefonów.
  const SOURCING_OPERATIONAL = [
    "/dashboard",
    "/candidates",
    "/candidates/search",
    "/cv-generator",
    "/contracts/b2b-generator",
    "/talents",
    "/talent-radar",
    "/sourcing/marketplace",
  ];
  const PIPELINE = ["/jobs", "/calendar"];
  const DELIVERY = [
    "/clients",
    "/my-clients",
    "/order-mail",
    "/my-relationships",
    "/contracts",
  ];
  const INSIGHTS = ["/insights", "/cortex"];
  const SYSTEM = ["/help", "/settings"];

  const EXPECTED: Partial<Record<UserRole, string[]>> = {
    recruiter: [
      ...SOURCING_OPERATIONAL,
      "/applications",
      ...PIPELINE,
      ...INSIGHTS,
      ...SYSTEM,
    ],
    delivery_lead: [
      ...SOURCING_OPERATIONAL,
      "/applications",
      ...PIPELINE,
      ...DELIVERY,
      ...INSIGHTS,
      ...SYSTEM,
    ],
    admin: [
      ...SOURCING_OPERATIONAL,
      "/applications",
      ...PIPELINE,
      ...DELIVERY,
      ...INSIGHTS,
      "/finance",
      ...SYSTEM,
    ],
    finance: [
      ...SOURCING_OPERATIONAL,
      "/applications",
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
    user: [
      "/dashboard",
      "/cv-generator",
      "/contracts/b2b-generator",
      "/talent-radar",
      ...PIPELINE,
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
    // Pozycja stoi tuż za Wyszukiwarką, jak w starym menu.
    const recruiter = sidebarHrefs("recruiter", true);
    expect(recruiter.indexOf("/candidates/contact-queue")).toBe(
      recruiter.indexOf("/candidates/search") + 1,
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

  it("Panel managera zostaje w palecie dla ról z nav.manager, ale nie w menu", () => {
    const admin = userOf("admin");
    const palette = visiblePaletteEntries(admin, { contactQueueEnabled: false }, (c) =>
      hasCapability(admin, c),
    );
    expect(palette.some((entry) => entry.href === "/manager")).toBe(true);
    expect(sidebarHrefs("admin", false)).not.toContain("/manager");
    const recruiter = userOf("recruiter");
    const recruiterPalette = visiblePaletteEntries(
      recruiter,
      { contactQueueEnabled: false },
      (c) => hasCapability(recruiter, c),
    );
    expect(recruiterPalette.some((entry) => entry.href === "/manager")).toBe(
      hasCapability(recruiter, "nav.manager"),
    );
  });

  it("Dashboard prowadzi do dashboardu roli, nie do `/`", () => {
    const dashboard = NAV_REGISTRY.find((entry) => entry.id === "dashboard");
    expect(dashboard).toBeDefined();
    const href = resolveNavHref(dashboard!, userOf("recruiter") as never);
    expect(href).not.toBe("/");
    expect(href.startsWith("/dashboard")).toBe(true);
  });
});
