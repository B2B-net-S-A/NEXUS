import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { visibleNavSections } from "@/components/v2/shell/SidebarV2";
import {
  CAPABILITY_PERMISSIONS,
  CAPABILITY_ROLES,
  hasAnyCapability,
  hasCapability,
  type Capability,
} from "@/lib/capabilities";
import { PERMISSION_KEYS, type Permission } from "@/lib/permissions";
import type { UserRole } from "@/store/auth";
import { accessSnapshot } from "@/test/fixtures/access-snapshot";

// Wszystkie role z backendu (backend/app/models/user.py). Macierz MUSI być
// domknięta — `head_of_recruitment` bywał pomijany w listach testowych i to
// właśnie jego brak przepuszczał bramki, których backend mu nie daje (F-19).
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
  "trainee",
];

const mkUser = (role: UserRole) => ({ role });

/**
 * Oczekiwana macierz capability × rola. Pisana ręcznie (a nie wyliczana
 * z rejestru), żeby każda zmiana uprawnień była świadomym diffem w PR,
 * a nie cichym efektem ubocznym.
 *
 * `true` = akcja widoczna i klikalna, `false` = ukryta.
 *
 * Użytkownik to sama rola (`{ role }`), czyli profil bez kompletu uprawnień
 * z serwera: capability z `CAPABILITY_PERMISSIONS` liczy się wtedy z DOMYŚLNYCH
 * uprawnień ról (`lib/permission-catalog.json`). Macierz jest więc stanem
 * startowym ekranu Osoby i role; co administrator przełączy, pilnują testy
 * „capability z uprawnienia” niżej.
 */
const EXPECTED: Record<
  Capability,
  Record<
    Exclude<UserRole, "finance" | "talent_community_manager" | "trainee">,
    boolean
  >
> = {
  // POST /api/candidates → RecruiterPlus (od 2026-09-17 z HoR — parytet z rekruterem)
  "candidate.create": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  // PATCH /api/candidates/{id}, notatki, assign-to-job → CandidateWriteAccess
  "candidate.write": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  "candidate.requirement.verify": {
    admin: true, head_of_recruitment: true, delivery_lead: true,
    tac: true, recruiter: true, sourcer: true, user: false,
  },
  // `/jobs/new` → uprawnienie `recruitment_manage` (domyślnie DL). TAC poza (U4).
  "job.create": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // PATCH /api/jobs/{id} → poziom `full`: `recruitment_manage` albo rola TAC.
  // HoR celowo na false: inline-edycja pól oferty dostałaby 403, więc
  // kontrolka ma być dla niego niewidoczna.
  "job.update": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: true,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // POST /api/clients → uprawnienie `clients_edit` (domyślnie DL)
  "client.create": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // PATCH /api/clients/{id} → uprawnienie `clients_edit`
  "client.update": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // PUT/POST confirm/DELETE /api/clients/{id}/cv-rule → `clients_edit`.
  // TAC na false: reguł CV nie prowadzi — kontrolki mają być niewidoczne.
  "cv_rule.manage": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // PUT /api/clients/{id}/playbook → `clients_edit`. Odczyt karty ma każda
  // rola operacyjna, więc bramka dotyczy wyłącznie „Edytuj kartę" / „Załóż kartę".
  "client_playbook.manage": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // POST /api/contracts → uprawnienie `contracts_orders_edit` (domyślnie DL
  // i Finanse — te drugie w `financeExpected`).
  "contract.create": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // ClientAccess.can_edit_contacts → uprawnienie `clients_edit`
  "contact.create": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // CalendarWriteAccess → CALENDAR_WRITE_ROLES (bez HoR)
  "calendar_event.create": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  // POST /api/invite-links → RecruiterPlus
  "invite_link.create": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  // POST /api/jobs/{id}/hiring-manager-feedback → RecruiterPlus (bez HoR!).
  // HoR czyta werdykty, ale „Zapisz feedback" dostałby 403.
  "hm_feedback.record": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  // CandidateWriteAccess = CANDIDATE_WRITE_ROLES (RecruiterPlus, bez HoR).
  // HoR czyta teczkę, ale nie wgrywa — upload dostałby 403.
  "candidate.document.manage": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  // CandidateProfileFacts{Read,Write}Access = _INTERNAL_OPERATIONAL_ROLES.
  // HoR i sourcer CELOWO na true — polityka produktowa faktów globalnych.
  "candidate.profile_fact.manage": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  // GET /api/dashboard/v2/recruitment-stats → OperationalUser.
  "dashboard.recruitment_stats.view": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  // PATCH /api/clients/{id}/portfolio-scopes/{scope}/placement → AdminUser
  "client.portfolio.manage": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: false,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // ── Nawigacja (middleware ROLE_ROUTES / bramki sidebara) ──
  "nav.candidates": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  "nav.my_people": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  "nav.talents": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  // Radar dla KAŻDEJ zalogowanej roli (decyzja produktowa Artura 19.08 —
  // poszła po zrzucie 403 od Head of Recruitment). Backend lustrzanie na
  // CurrentUser, middleware bez wpisu.
  "nav.talent_radar": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: true,
  },
  "nav.sourcing": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  "nav.clients": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  "nav.my_clients": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  "nav.order_mail": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  "nav.my_relationships": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  "nav.contracts": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // /api/finance/* → uprawnienie `finance_module` — moduł własny finance
  // (finance poza tym dziedziczy tier recruitera, patrz financeExpected).
  "nav.finance": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: false,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // „Telefony na dziś” — wyłącznie praktykant (0374), nawet admin nie.
  "nav.trainee": {
    admin: false,
    head_of_recruitment: false,
    delivery_lead: false,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // Panel „Praktykanci” i reguły listy — admin i Head of Recruitment.
  "nav.trainees": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: false,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
};

/** Praktykant (0374) ma jedną capability: własną listę telefonów. */
function traineeExpected(capability: Capability): boolean {
  return capability === "nav.trainee";
}

/**
 * Reguła dla `finance` (decyzja produktowa Artura 19.08 — pełny dostęp
 * operacyjny): Finance ma tier recruitera, własny moduł oraz jawne moduły
 * business-read kontraktów i klientów. Wyliczana z macierzy, nie ręczna
 * lista — dzięki temu nowa capability przyznana recruiterowi automatycznie obejmuje finance, a
 * odstępstwo od reguły wymaga świadomej zmiany tej funkcji.
 *
 * Od 0409 (decyzja Artura 02.10.2026) Finanse mają domyślnie „Kontrakty
 * i zamówienia: tworzenie i edycja”, więc także `contract.create`.
 */
function financeExpected(capability: Capability): boolean {
  if (
    [
      "nav.finance",
      "nav.clients",
      "nav.my_clients",
      "nav.order_mail",
      "nav.my_relationships",
      "nav.contracts",
      "contract.create",
    ].includes(capability)
  ) {
    return true;
  }
  return EXPECTED[capability].recruiter;
}

function talentCommunityManagerExpected(capability: Capability): boolean {
  return [
    "candidate.create",
    "candidate.write",
    "calendar_event.create",
    "invite_link.create",
    "hm_feedback.record",
    "candidate.document.manage",
    "candidate.profile_fact.manage",
    "candidate.requirement.verify",
    "dashboard.recruitment_stats.view",
    "nav.candidates",
    "nav.my_people",
    "nav.talents",
    "nav.talent_radar",
    "nav.sourcing",
    "nav.clients",
    "nav.my_clients",
    "nav.order_mail",
    "nav.my_relationships",
    "nav.contracts",
  ].includes(capability);
}

const ALL_CAPABILITIES = Object.keys(CAPABILITY_ROLES) as Capability[];

describe("rejestr capability — kompletność", () => {
  it("każda capability z rejestru ma wpis w oczekiwanej macierzy", () => {
    expect(Object.keys(EXPECTED).sort()).toEqual([...ALL_CAPABILITIES].sort());
  });

  it("każda capability wymienia wyłącznie znane role", () => {
    for (const capability of ALL_CAPABILITIES) {
      for (const role of CAPABILITY_ROLES[capability]) {
        expect(ALL_ROLES).toContain(role);
      }
    }
  });

  it("żadna capability nie jest martwa: ma uprawnienie z ekranu albo listę ról", () => {
    for (const capability of ALL_CAPABILITIES) {
      const dead =
        CAPABILITY_PERMISSIONS[capability] === undefined &&
        CAPABILITY_ROLES[capability].length === 0;
      expect(dead, capability).toBe(false);
    }
  });

  it("tabela uprawnień wymienia wyłącznie capability z rejestru i klucze z katalogu", () => {
    for (const [capability, permission] of Object.entries(CAPABILITY_PERMISSIONS)) {
      expect(ALL_CAPABILITIES).toContain(capability);
      expect(PERMISSION_KEYS).toContain(permission);
    }
  });

  it("uprawnienie zastępuje listę ról — obie drogi naraz ma tylko `job.update` (TAC)", () => {
    const both = ALL_CAPABILITIES.filter(
      (capability) =>
        CAPABILITY_PERMISSIONS[capability] !== undefined &&
        CAPABILITY_ROLES[capability].length > 0,
    );
    expect(both).toEqual(["job.update"]);
    expect(CAPABILITY_ROLES["job.update"]).toEqual(["tac"]);
  });

  it("mapa capability → uprawnienie jest tą z planu (02.10.2026)", () => {
    expect(CAPABILITY_PERMISSIONS).toEqual({
      "job.create": "recruitment_manage",
      "job.update": "recruitment_manage",
      "client.create": "clients_edit",
      "client.update": "clients_edit",
      "cv_rule.manage": "clients_edit",
      "client_playbook.manage": "clients_edit",
      "contact.create": "clients_edit",
      "contract.create": "contracts_orders_edit",
      "nav.clients": "delivery_view",
      "nav.my_clients": "delivery_view",
      "nav.order_mail": "delivery_view",
      "nav.my_relationships": "delivery_view",
      "nav.contracts": "delivery_view",
      "nav.finance": "finance_module",
    });
  });
});

describe("hasCapability — pełna macierz rola × capability", () => {
  for (const capability of ALL_CAPABILITIES) {
    for (const role of ALL_ROLES) {
      // Finance = tier recruitera + własny moduł (decyzja 19.08).
      const expected =
        role === "finance"
          ? financeExpected(capability)
          : role === "talent_community_manager"
            ? talentCommunityManagerExpected(capability)
            : role === "trainee"
              ? traineeExpected(capability)
              : EXPECTED[capability][role];
      it(`${role} ${expected ? "MA" : "NIE ma"} ${capability}`, () => {
        expect(hasCapability(mkUser(role), capability)).toBe(expected);
      });
    }
  }
});

describe("hasCapability — przypadki brzegowe", () => {
  it("fail-closed dla braku usera", () => {
    for (const capability of ALL_CAPABILITIES) {
      expect(hasCapability(null, capability)).toBe(false);
      expect(hasCapability(undefined, capability)).toBe(false);
    }
  });

  it("multi-role: druga rola nadaje uprawnienie, którego primary nie ma", () => {
    // Hybryda HoR + DL — HoR sam nie zakłada rekrutacji, DL ma domyślnie
    // „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta”.
    const hybrid = {
      role: "head_of_recruitment" as UserRole,
      roles: ["head_of_recruitment", "delivery_lead"] as UserRole[],
    };
    expect(hasCapability(mkUser("head_of_recruitment"), "job.create")).toBe(
      false,
    );
    expect(hasCapability(hybrid, "job.create")).toBe(true);
  });

  it("brak `roles` (stary cache localStorage) fallbackuje na primary `role`", () => {
    expect(hasCapability({ role: "delivery_lead" }, "job.create")).toBe(true);
    expect(hasCapability({ role: "recruiter" }, "job.create")).toBe(false);
  });

  it("admin ma wszystko — żadna bramka go nie blokuje (poza ekranem praktykanta)", () => {
    for (const capability of ALL_CAPABILITIES) {
      // „Telefony na dziś” to lista TEGO praktykanta — admin zagląda do
      // panelu „Praktykanci”, nie do cudzej listy.
      expect(hasCapability(mkUser("admin"), capability)).toBe(
        capability !== "nav.trainee",
      );
    }
  });

  it("praktykant ma WYŁĄCZNIE „Telefony na dziś” — także bez Talent Radaru", () => {
    for (const capability of ALL_CAPABILITIES) {
      expect(hasCapability(mkUser("trainee"), capability)).toBe(
        capability === "nav.trainee",
      );
    }
  });

  it("rola `user` (read-only viewer) ma WYŁĄCZNIE Talent Radar", () => {
    // Jedyny wyjątek od „viewer nie ma niczego": radar jest dla każdej
    // zalogowanej roli (decyzja produktowa 19.08). Pętla nadal domyka
    // resztę katalogu — nowa capability przyznana viewerowi przypadkiem
    // dalej robi czerwono.
    for (const capability of ALL_CAPABILITIES) {
      const expected = capability === "nav.talent_radar";
      expect(hasCapability(mkUser("user"), capability)).toBe(expected);
    }
  });

  it("rola `finance` = tier recruitera + business-read + własny moduł", () => {
    for (const capability of ALL_CAPABILITIES) {
      expect(hasCapability(mkUser("finance"), capability)).toBe(
        financeExpected(capability),
      );
    }
    expect(hasCapability(mkUser("finance"), "nav.finance")).toBe(true);
    expect(hasCapability(mkUser("finance"), "nav.candidates")).toBe(true);
    expect(hasCapability(mkUser("finance"), "nav.clients")).toBe(true);
    expect(hasCapability(mkUser("finance"), "nav.my_clients")).toBe(true);
    expect(hasCapability(mkUser("finance"), "nav.my_relationships")).toBe(true);
    expect(hasCapability(mkUser("finance"), "nav.contracts")).toBe(true);
  });

  it("Talent Community Manager ma biznes bez Finansów; Delivery czyta, klientów i kontraktów nie zakłada", () => {
    for (const capability of ALL_CAPABILITIES) {
      expect(hasCapability(mkUser("talent_community_manager"), capability)).toBe(
        talentCommunityManagerExpected(capability),
      );
    }
    expect(hasCapability(mkUser("talent_community_manager"), "nav.finance")).toBe(
      false,
    );
    expect(hasCapability(mkUser("talent_community_manager"), "client.create")).toBe(
      false,
    );
    // Zapis w sekcji Delivery TCM ma (zmienia status kontraktu), ale sekcja
    // jest tylko sufitem — bez uprawnienia nie ma akcji.
    expect(
      hasCapability(mkUser("talent_community_manager"), "contract.create"),
    ).toBe(false);
  });

  it("efektywna sekcja zawęża akcje do read i może całkiem ukryć nawigację", () => {
    // Stary wyjątek osoby ograniczający sekcję Delivery: uprawnienia roli
    // zostają, ale trasa odmówi zapisu (bramka sekcji na routerze).
    const deliveryReadOnly = {
      role: "delivery_lead" as UserRole,
      roles: ["delivery_lead"] as UserRole[],
      effective_section_access: {
        sourcing: "write" as const,
        pipeline: "write" as const,
        delivery: "read" as const,
        insights: "read" as const,
        finance: "none" as const,
        system_admin: "none" as const,
      },
    };

    expect(hasCapability(deliveryReadOnly, "nav.clients")).toBe(true);
    expect(hasCapability(deliveryReadOnly, "client.create")).toBe(false);
    expect(hasCapability(deliveryReadOnly, "client.update")).toBe(false);

    const deliveryDenied = {
      ...deliveryReadOnly,
      effective_section_access: {
        ...deliveryReadOnly.effective_section_access,
        delivery: "none" as const,
      },
    };
    expect(hasCapability(deliveryDenied, "nav.clients")).toBe(false);
  });

  it("sama sekcja nie daje akcji — decyduje uprawnienie", () => {
    // Profil sprzed 0409 z wyjątkiem sekcji Delivery: uprawnień rekruter
    // domyślnie nie ma, więc zapis sekcji niczego mu nie otwiera.
    const recruiterWithDeliveryWrite = {
      role: "recruiter" as UserRole,
      roles: ["recruiter"] as UserRole[],
      effective_section_access: {
        sourcing: "write" as const,
        pipeline: "write" as const,
        delivery: "write" as const,
        insights: "read" as const,
        finance: "none" as const,
        system_admin: "none" as const,
      },
    };

    expect(hasCapability(recruiterWithDeliveryWrite, "client.create")).toBe(
      false,
    );
    expect(hasCapability(recruiterWithDeliveryWrite, "nav.clients")).toBe(false);
  });
});

describe("capability z uprawnienia — to, co administrator przełączył, decyduje", () => {
  const CLIENT_EDIT_CAPABILITIES: Capability[] = [
    "client.create",
    "client.update",
    "contact.create",
    "cv_rule.manage",
    "client_playbook.manage",
  ];
  const DELIVERY_NAV: Capability[] = [
    "nav.clients",
    "nav.my_clients",
    "nav.order_mail",
    "nav.my_relationships",
    "nav.contracts",
  ];

  it("rekruter z nadanym „Klienci: dodawanie i edycja” zakłada i edytuje klientów", () => {
    const recruiter = accessSnapshot("recruiter", { grant: ["clients_edit"] });
    for (const capability of [...CLIENT_EDIT_CAPABILITIES, ...DELIVERY_NAV]) {
      expect(hasCapability(recruiter, capability), capability).toBe(true);
    }
    // Jedno uprawnienie nie pociąga drugiego: kontraktów nie zakłada.
    expect(hasCapability(recruiter, "contract.create")).toBe(false);
    expect(hasCapability(recruiter, "job.create")).toBe(false);
    expect(hasCapability(recruiter, "nav.finance")).toBe(false);
  });

  it("Delivery Lead z wyłączonym „Klienci: dodawanie i edycja” nie widzi tych akcji", () => {
    const lead = accessSnapshot("delivery_lead", { revoke: ["clients_edit"] });
    for (const capability of CLIENT_EDIT_CAPABILITIES) {
      expect(hasCapability(lead, capability), capability).toBe(false);
    }
    // Reszta uprawnień roli zostaje.
    expect(hasCapability(lead, "contract.create")).toBe(true);
    expect(hasCapability(lead, "job.create")).toBe(true);
    expect(hasCapability(lead, "nav.clients")).toBe(true);
  });

  it("kontrakty zakłada posiadacz „Kontrakty i zamówienia: tworzenie i edycja”", () => {
    expect(
      hasCapability(
        accessSnapshot("talent_community_manager", {
          grant: ["contracts_orders_edit"],
        }),
        "contract.create",
      ),
    ).toBe(true);
    expect(
      hasCapability(
        accessSnapshot("finance", { revoke: ["contracts_orders_edit"] }),
        "contract.create",
      ),
    ).toBe(false);
    expect(
      hasCapability(
        accessSnapshot("delivery_lead", { revoke: ["contracts_orders_edit"] }),
        "contract.create",
      ),
    ).toBe(false);
  });

  it("rekrutacje: uprawnienie albo rola TAC; wyłączone Delivery Leadowi — znika", () => {
    const recruiter = accessSnapshot("recruiter", { grant: ["recruitment_manage"] });
    expect(hasCapability(recruiter, "job.create")).toBe(true);
    expect(hasCapability(recruiter, "job.update")).toBe(true);

    const lead = accessSnapshot("delivery_lead", { revoke: ["recruitment_manage"] });
    expect(hasCapability(lead, "job.create")).toBe(false);
    expect(hasCapability(lead, "job.update")).toBe(false);

    // TAC ma pełną edycję z tytułu roli (gałąź legacy), ale nie zakłada.
    const tac = accessSnapshot("tac");
    expect(hasCapability(tac, "job.update")).toBe(true);
    expect(hasCapability(tac, "job.create")).toBe(false);
  });

  it("sufit Pipeline zostaje nad uprawnieniem do rekrutacji", () => {
    const readOnlyPipeline = accessSnapshot("recruiter", {
      grant: ["recruitment_manage"],
      sectionCaps: { pipeline: "read" },
    });
    expect(hasCapability(readOnlyPipeline, "job.create")).toBe(false);
    expect(hasCapability(readOnlyPipeline, "job.update")).toBe(false);
  });

  it("sam podgląd Delivery otwiera nawigację, nie akcje", () => {
    const viewer = accessSnapshot("recruiter", { grant: ["delivery_view"] });
    for (const capability of DELIVERY_NAV) {
      expect(hasCapability(viewer, capability), capability).toBe(true);
    }
    for (const capability of [...CLIENT_EDIT_CAPABILITIES, "contract.create"] as Capability[]) {
      expect(hasCapability(viewer, capability), capability).toBe(false);
    }
    const noDelivery = accessSnapshot("talent_community_manager", {
      revoke: ["delivery_view", "contract_status"],
    });
    for (const capability of DELIVERY_NAV) {
      expect(hasCapability(noDelivery, capability), capability).toBe(false);
    }
  });

  it("Moduł Finanse: nadany Head of Recruitment otwiera wejście, wyłączony Finansom — zamyka", () => {
    expect(
      hasCapability(
        accessSnapshot("head_of_recruitment", { grant: ["finance_module"] }),
        "nav.finance",
      ),
    ).toBe(true);
    expect(
      hasCapability(
        accessSnapshot("finance", { revoke: ["finance_module"] }),
        "nav.finance",
      ),
    ).toBe(false);
  });

  it("stary wyjątek ograniczający sekcję Delivery chowa zapis mimo uprawnienia", () => {
    const capped = accessSnapshot("delivery_lead", {
      sectionCaps: { delivery: "read" },
    });
    expect(hasCapability(capped, "client.create")).toBe(false);
    expect(hasCapability(capped, "contract.create")).toBe(false);
    expect(hasCapability(capped, "nav.clients")).toBe(true);
  });

  it("role `user` i `trainee` nie dostają niczego nawet z kompletem z serwera", () => {
    for (const role of ["user", "trainee"] as UserRole[]) {
      const account = accessSnapshot(role);
      for (const capability of Object.keys(CAPABILITY_PERMISSIONS) as Capability[]) {
        expect(hasCapability(account, capability), `${role} ${capability}`).toBe(false);
      }
    }
  });
});

describe("regresja C6: teczka plików \u2260 fakty profilowe (granica po sourcerze)", () => {
  it("sourcer edytuje fakty globalne i wgrywa pliki; viewer nic", () => {
    // Od 2026-09-17 HoR ma parytet z rekruterem, więc granica między
    // CandidateProfileFacts*Access (_INTERNAL_OPERATIONAL_ROLES) a
    // CandidateWriteAccess (CANDIDATE_WRITE_ROLES) przebiega dziś tylko po
    // viewerze `user`. Test pilnuje, że oba wpisy nie zostały zlane w jeden.
    expect(hasCapability(mkUser("sourcer"), "candidate.profile_fact.manage")).toBe(true);
    expect(hasCapability(mkUser("sourcer"), "candidate.document.manage")).toBe(true);
    expect(hasCapability(mkUser("head_of_recruitment"), "candidate.document.manage")).toBe(true);
    expect(hasCapability(mkUser("user"), "candidate.profile_fact.manage")).toBe(false);
    expect(hasCapability(mkUser("user"), "candidate.document.manage")).toBe(false);
  });

  it("radar jest szerszy ni\u017c dost\u0119p do kandydat\u00f3w", () => {
    // Zapobiega powrotowi r\u0119cznej listy r\u00f3l z `app/talent-radar/page.tsx`.
    expect(hasCapability(mkUser("user"), "nav.talent_radar")).toBe(true);
    expect(hasCapability(mkUser("user"), "nav.candidates")).toBe(false);
    expect(
      hasCapability(mkUser("head_of_recruitment"), "nav.talent_radar"),
    ).toBe(true);
  });
});

describe("hasAnyCapability", () => {
  it("zwraca true gdy choć jedna capability przechodzi", () => {
    expect(
      hasAnyCapability(mkUser("recruiter"), "job.create", "candidate.create"),
    ).toBe(true);
  });

  it("zwraca false gdy żadna nie przechodzi", () => {
    expect(
      hasAnyCapability(mkUser("user"), "job.create", "candidate.create"),
    ).toBe(false);
  });

  it("bez argumentów zwraca false (fail-closed)", () => {
    expect(hasAnyCapability(mkUser("admin"))).toBe(false);
  });
});

describe("regresja F-19: Quick Actions nie pokazuje akcji bez capability", () => {
  const QUICK_ACTIONS: Capability[] = [
    "candidate.create",
    "job.create",
    "client.create",
    "contact.create",
    "calendar_event.create",
    "invite_link.create",
  ];

  it("read-only viewer nie widzi ŻADNEJ akcji Quick Actions", () => {
    const visible = QUICK_ACTIONS.filter((c) =>
      hasCapability(mkUser("user"), c),
    );
    expect(visible).toEqual([]);
  });

  it("sourcer widzi tylko kandydata, spotkanie i link aplikacyjny", () => {
    const visible = QUICK_ACTIONS.filter((c) =>
      hasCapability(mkUser("sourcer"), c),
    );
    expect(visible).toEqual([
      "candidate.create",
      "calendar_event.create",
      "invite_link.create",
    ]);
  });

  it("head_of_recruitment nie dostaje akcji tworzenia z sekcji Delivery", () => {
    // Parytet z rekruterem (2026-09-17): kandydat, spotkanie, link — ale
    // nadal bez rekrutacji/klienta/kontraktu/kontaktu (uprawnień z ekranu
    // HoR domyślnie nie ma).
    const visible = QUICK_ACTIONS.filter((c) =>
      hasCapability(mkUser("head_of_recruitment"), c),
    );
    expect(visible).toEqual([
      "candidate.create",
      "calendar_event.create",
      "invite_link.create",
    ]);
  });
});

describe("regresja F-19: żadna akcja tworzenia nie omija rejestru", () => {
  // Komplet capability typu `*.create` — także tych bramkowanych poza Quick
  // Actions (nagłówki list, zakładki profilu klienta, strona szczegółów oferty).
  const CREATE_CAPABILITIES = ALL_CAPABILITIES.filter((c) =>
    c.endsWith(".create"),
  );

  it("każda akcja tworzenia ma wpis w rejestrze", () => {
    expect(CREATE_CAPABILITIES).toEqual([
      "candidate.create",
      "job.create",
      "client.create",
      "contract.create",
      "contact.create",
      "calendar_event.create",
      "invite_link.create",
    ]);
  });

  it("read-only viewer nie tworzy NICZEGO", () => {
    for (const capability of CREATE_CAPABILITIES) {
      expect(hasCapability(mkUser("user"), capability)).toBe(false);
    }
  });

  it("recruiter/sourcer nie tworzą kontraktów, rekrutacji, firm ani kontaktów", () => {
    for (const role of ["recruiter", "sourcer"] as UserRole[]) {
      expect(hasCapability(mkUser(role), "contract.create")).toBe(false);
      expect(hasCapability(mkUser(role), "job.create")).toBe(false);
      expect(hasCapability(mkUser(role), "client.create")).toBe(false);
      expect(hasCapability(mkUser(role), "contact.create")).toBe(false);
    }
  });

  it("kontrakt i firma to dwa uprawnienia, a rekrutacja — trzecie", () => {
    // Do 0409 obie akcje dzieliły jedną listę ról. Teraz różni je domyślny
    // posiadacz: Finanse zakładają kontrakty, klientów nie.
    const differing = ALL_ROLES.filter(
      (role) =>
        hasCapability(mkUser(role), "contract.create") !==
        hasCapability(mkUser(role), "client.create"),
    );
    expect(differing).toEqual(["finance"]);
    expect(hasCapability(mkUser("finance"), "contract.create")).toBe(true);
    expect(hasCapability(mkUser("finance"), "client.create")).toBe(false);
    // TAC nie zakłada rekrutacji (`/jobs/new` wymaga uprawnienia, U4 22.09).
    expect(hasCapability(mkUser("tac"), "job.create")).toBe(false);
    expect(hasCapability(mkUser("delivery_lead"), "job.create")).toBe(true);
    expect(hasCapability(mkUser("tac"), "client.create")).toBe(false);
  });
});

// ───────────────────────────────────────────────────────────────────────────
// KONTRAKT MIĘDZY WARSTWAMI (F-67)
//
// Wiążąca reguła rolowa mieszka w Pythonie. Frontend powtarza ją w pięciu
// miejscach (rejestr capability, middleware, sidebar, in-page `RequireRole`,
// bramki w komponentach), a do tej pory KAŻDA kopia była weryfikowana wyłącznie
// względem literału wpisanego przez tę samą osobę w tym samym PR — nic po
// żadnej ze stron nie czytało drugiej. Jedynym detektorem rozjazdu był
// użytkownik, który się na niego natknął, i to w obie strony: „link widoczny →
// 403 po kliknięciu" (Talent Radar dla HoR, generator B2B dla finance) oraz
// „backend otwarty → UI dalej to chowa" (piąta kopia listy ról, która przeżyła
// #1212 i #1215).
//
// Poniższe testy CZYTAJĄ źródła backendu i porównują literały. Rozjazd przestaje
// być niewidoczny: poszerzenie strażnika w Pythonie bez ruszenia rejestru (albo
// odwrotnie) robi czerwono w CI, w zdaniu wskazującym capability i plik.
//
// Od 0409 część bramek to UPRAWNIENIA z ekranu Osoby i role, nie listy ról.
// Dla nich lustrem nie jest zbiór ról (administrator go przełącza), tylko para:
// capability wymaga uprawnienia P, a wskazana trasa backendu pyta o to samo P.
//
// Świadomie POZA zakresem: `middleware.ts` nie eksportuje `ROLE_ROUTES`, więc
// jego lustro trzeba domknąć osobno — tam też zaczyna się od eksportu tablicy.
// ───────────────────────────────────────────────────────────────────────────

const BACKEND_FILES = {
  deps: "backend/app/api/deps.py",
  permissionAccess: "backend/app/api/permission_access.py",
  clients: "backend/app/api/clients.py",
  contracts: "backend/app/api/contracts.py",
  jobIntake: "backend/app/api/job_request_intake.py",
  candidateAccess: "backend/app/api/candidate_access.py",
  recruitmentAccess: "backend/app/api/recruitment_access.py",
  clientAccess: "backend/app/services/client_access.py",
  permissionCatalog: "backend/app/services/permission_catalog.py",
} as const;

type BackendFile = keyof typeof BACKEND_FILES;
type GuardRef = readonly [BackendFile, string];

// Katalog repo wyprowadzony z `process.cwd()`, nie z `import.meta.url`.
// vitest.config.ts ustawia `environment: "jsdom"`, a pod jsdom `import.meta.url`
// nie jest URL-em o schemacie `file:` — `fileURLToPath` rzuca wtedy
// „The URL must be of scheme file" JESZCZE PRZED zebraniem testów, więc plik
// wygląda na pusty zamiast czerwony. vitest startuje z cwd = `frontend/`.
const REPO_ROOT = resolve(process.cwd(), "..");

/**
 * Surowe przypisania z jednego modułu Pythona. Rozpoznaje trzy kształty, w
 * których repo trzyma zbiory ról:
 *   NAME: tuple[UserRole, ...] = (UserRole.a, …)   — katalogi *_ROLES
 *   NAME: tuple[UserRole, ...] = OTHER_NAME        — alias (np. CANDIDATE_READ_ROLES)
 *   NAME = Annotated[User, Depends(require_roles(UserRole.a, …))]        — deps.py
 *   NAME = Annotated[User, Depends(require_candidate_roles(*OTHER_NAME))] — candidate_access.py
 */
const BACKEND_SOURCES = new Map<BackendFile, string>();

function backendSource(file: BackendFile): string {
  let source = BACKEND_SOURCES.get(file);
  if (source === undefined) {
    source = readFileSync(join(REPO_ROOT, BACKEND_FILES[file]), "utf8");
    BACKEND_SOURCES.set(file, source);
  }
  return source;
}

function readBackendAssignments(file: BackendFile): Map<string, string> {
  const source = backendSource(file);
  const out = new Map<string, string>();
  const patterns = [
    /^([A-Z_][A-Za-z_0-9]*)(?:\s*:\s*tuple\[UserRole,\s*\.\.\.\])?\s*=\s*(\([\s\S]*?\)|[A-Za-z_][A-Za-z_0-9]*)\s*$/gm,
    /^(\w+)\s*=\s*Annotated\[\s*User,\s*Depends\(\s*require_roles\(([\s\S]*?)\)\s*\),?\s*\]/gm,
    /^(\w+)\s*=\s*Annotated\[\s*User,\s*Depends\(\s*require_candidate_roles\(\s*\*?([\s\S]*?)\)\s*\),?\s*\]/gm,
  ];
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) {
      out.set(match[1], match[2]);
    }
  }
  return out;
}

const BACKEND_ASSIGNMENTS = new Map<BackendFile, Map<string, string>>();

function backendAssignments(file: BackendFile): Map<string, string> {
  let assignments = BACKEND_ASSIGNMENTS.get(file);
  if (assignments === undefined) {
    assignments = readBackendAssignments(file);
    BACKEND_ASSIGNMENTS.set(file, assignments);
  }
  return assignments;
}

/** Zbiór ról stojący za nazwanym strażnikiem backendu. Rzuca, gdy symbol
 *  zniknął albo został przemianowany — cichy brak byłby gorszy niż czerwony
 *  test, bo zamieniłby kontrakt w zawsze-zielony no-op. */
function backendRoles(file: BackendFile, symbol: string): UserRole[] {
  const assignments = backendAssignments(file);
  const seen = new Set<string>();
  let name = symbol;
  for (;;) {
    const value = assignments.get(name);
    if (value === undefined) {
      throw new Error(
        `Backend nie ma już symbolu ${name} w ${BACKEND_FILES[file]} ` +
          `(startowałem od ${symbol}). Zaktualizuj CAPABILITY_BACKEND_MIRROR.`,
      );
    }
    const roles = [...value.matchAll(/UserRole\.(\w+)/g)].map((m) => m[1]);
    if (roles.length > 0) return roles as UserRole[];
    // Section-aware aliases pass a second, non-role keyword argument. The
    // mirror still follows the first role tuple; the required access level is
    // verified by the dedicated section tests.
    const alias = value.trim().replace(/^\*/, "").split(",", 1)[0].trim();
    if (!/^[A-Za-z_][A-Za-z_0-9]*$/.test(alias) || seen.has(alias)) {
      throw new Error(
        `Nie umiem rozwinąć ${name} w ${BACKEND_FILES[file]} (wartość: ${value.trim()}).`,
      );
    }
    seen.add(name);
    name = alias;
  }
}

const sortRoles = (roles: readonly UserRole[]) => [...new Set(roles)].sort();

/**
 * Uprawnienie, którego wymaga alias bramki trasy:
 *   NAME = Annotated[User, Depends(require_permission(ProductAction.<klucz>))]
 * (`permission_access.py`, a dla `FinanceModuleUser` — `deps.py`). `null`, gdy
 * alias nie jest bramką jednego uprawnienia (np. strażnik rolowy).
 */
function aliasPermission(alias: string): string | null {
  const pattern = new RegExp(
    `^${alias}\\s*=\\s*Annotated\\[\\s*User,\\s*Depends\\(\\s*` +
      `require_permission\\(\\s*ProductAction\\.(\\w+)\\s*\\)\\s*\\),?\\s*\\]`,
    "m",
  );
  for (const file of ["permissionAccess", "deps"] as const) {
    const match = pattern.exec(backendSource(file));
    if (match) return match[1];
  }
  return null;
}

/**
 * O co pyta `current_user` wskazanego handlera trasy: klucz uprawnienia albo
 * opis strażnika rolowego (wtedy porównanie w teście mówi wprost, czym trasa
 * jest dziś bramkowana). Rzuca, gdy handler zniknął — jak `backendRoles`.
 */
function handlerPermission(file: BackendFile, handler: string): string {
  const params = new RegExp(`async def ${handler}\\(([\\s\\S]*?)\\n\\)`).exec(
    backendSource(file),
  )?.[1];
  if (params === undefined) {
    throw new Error(
      `Backend nie ma już handlera ${handler} w ${BACKEND_FILES[file]}. ` +
        `Zaktualizuj CAPABILITY_BACKEND_MIRROR.`,
    );
  }
  const alias = /\bcurrent_user:\s*([A-Za-z_][A-Za-z_0-9]*)/.exec(params)?.[1];
  if (!alias) {
    throw new Error(
      `Handler ${handler} w ${BACKEND_FILES[file]} nie ma parametru current_user.`,
    );
  }
  return aliasPermission(alias) ?? `strażnik bez uprawnienia: ${alias}`;
}

/** Dowód, że backend pyta o to samo uprawnienie co capability. */
type PermissionEvidence =
  /** Handler trasy, którego `current_user` wymaga tego uprawnienia. */
  | { handler: readonly [BackendFile, string] }
  /** Alias bramki trasy = `require_permission(ProductAction.<klucz>)`. */
  | { alias: string }
  /** Miejsce w źródle, które wiąże regułę z tym uprawnieniem. */
  | { source: readonly [BackendFile, RegExp] };

type PermissionMirror = {
  permission: Permission;
  evidence: readonly PermissionEvidence[];
  /** Role, które mają capability z tytułu roli OBOK uprawnienia. */
  legacyGuards?: readonly GuardRef[];
};

// `ClientAccess` liczy `can_edit_contacts` / `can_edit_knowledge` /
// `can_edit_materials` z jednego faktu: „Klienci: dodawanie i edycja”
// w zakresie konta. Kontakty, karta klienta i reguły CV pytają o te flagi.
const CLIENT_ACCESS_EDIT_EVIDENCE: readonly PermissionEvidence[] = [
  {
    source: [
      "clientAccess",
      /can_edit_clients=has_permission\(\s*user,\s*ProductAction\.clients_edit\s*\)/,
    ],
  },
  { source: ["clientAccess", /can_edit = facts\.can_edit_clients and in_scope/] },
];

// Sekcja Delivery wynika z uprawnień: jej ODCZYT to „Klienci, kontrakty
// i zamówienia: podgląd” (`derive_sections`), a trasy GET stoją za sekcją.
const DELIVERY_VIEW_MIRROR: PermissionMirror = {
  permission: "delivery_view",
  evidence: [
    { alias: "DeliveryViewUser" },
    {
      source: [
        "permissionCatalog",
        /elif DELIVERY_VIEW in held:\s*\n\s*delivery = "read"/,
      ],
    },
  ],
};

/**
 * Capability → bramka backendu, której jest lustrem.
 *
 * `guards` — strażnik ROLOWY: lista ról capability ma być DOKŁADNIE sumą tych
 * zbiorów (nie podzbiorem — podzbiór przepuszcza drugi kierunek awarii:
 * backend otwarty, a UI dalej chowa funkcję).
 * `permission` — UPRAWNIENIE z ekranu Osoby i role: capability wymaga tego
 * samego klucza, o który pyta wskazana trasa backendu (`evidence`).
 * `productDecision` — świadomy brak pojedynczego strażnika; wymuszony wpis
 * sprawia, że nowa capability nie prześlizgnie się bez decyzji.
 */
const CAPABILITY_BACKEND_MIRROR: Record<
  Capability,
  { guards: readonly GuardRef[] } | PermissionMirror | { productDecision: string }
> = {
  "candidate.requirement.verify": { guards: [["candidateAccess", "CandidateWriteAccess"]] },
  "candidate.create": { guards: [["deps", "RecruiterPlus"]] },
  // PATCH /api/candidates/{id}, POST /api/notes, assign-to-job (CandidateWriteAccess).
  "candidate.write": { guards: [["candidateAccess", "CandidateWriteAccess"]] },
  // Najwęższe ogniwo tworzenia: `/jobs/new` woła `POST /api/job-intake/read`
  // i handoff — obie trasy za `RecruitmentManageUser`.
  "job.create": {
    permission: "recruitment_manage",
    evidence: [
      { alias: "RecruitmentManageUser" },
      { handler: ["jobIntake", "read_request"] },
      { handler: ["jobIntake", "read_request_file"] },
    ],
  },
  // `job_edit_level` = full: posiadacz uprawnienia albo — z tytułu roli — TAC.
  "job.update": {
    permission: "recruitment_manage",
    evidence: [{ source: ["recruitmentAccess", /\brecruitment_manage\b/] }],
    legacyGuards: [["recruitmentAccess", "JOB_FULL_EDIT_LEGACY_ROLES"]],
  },
  "client.create": {
    permission: "clients_edit",
    evidence: [{ alias: "ClientsEditUser" }, { handler: ["clients", "create_client"] }],
  },
  "client.update": {
    permission: "clients_edit",
    evidence: [{ alias: "ClientsEditUser" }, { handler: ["clients", "update_client"] }],
  },
  "cv_rule.manage": {
    permission: "clients_edit",
    evidence: CLIENT_ACCESS_EDIT_EVIDENCE,
  },
  "client_playbook.manage": {
    permission: "clients_edit",
    evidence: CLIENT_ACCESS_EDIT_EVIDENCE,
  },
  "contract.create": {
    permission: "contracts_orders_edit",
    evidence: [
      { alias: "ContractsOrdersEditUser" },
      { handler: ["contracts", "create_contract"] },
    ],
  },
  "contact.create": {
    permission: "clients_edit",
    evidence: CLIENT_ACCESS_EDIT_EVIDENCE,
  },
  "calendar_event.create": {
    guards: [["recruitmentAccess", "CALENDAR_WRITE_ROLES"]],
  },
  "invite_link.create": { guards: [["deps", "RecruiterPlus"]] },
  // POST /api/jobs/{id}/hiring-manager-feedback (hiring_manager_feedback.py).
  "hm_feedback.record": { guards: [["deps", "RecruiterPlus"]] },
  "candidate.document.manage": {
    guards: [["candidateAccess", "CandidateWriteAccess"]],
  },
  // Odczyt i zapis faktów mają dziś ten sam zbiór; wpis celuje w ZAPIS, bo to
  // on decyduje o widoczności kontrolki. Gdy backend je rozdzieli, rozdziel
  // też capability — test wtedy nie pomoże, bo porówna zapis z zapisem.
  "candidate.profile_fact.manage": {
    guards: [["candidateAccess", "CandidateProfileFactsWriteAccess"]],
  },
  "client.portfolio.manage": { guards: [["deps", "AdminUser"]] },
  "dashboard.recruitment_stats.view": { guards: [["deps", "OperationalUser"]] },
  "nav.candidates": { guards: [["candidateAccess", "CandidateSearchAccess"]] },
  "nav.my_people": { guards: [["candidateAccess", "CandidateSearchAccess"]] },
  "nav.talents": { guards: [["candidateAccess", "CandidateSearchAccess"]] },
  "nav.talent_radar": {
    productDecision:
      "Oba endpointy radaru stoją na CurrentUser (decyzja 19.08) — nie ma zbioru ról do porównania, bramką jest samo zalogowanie.",
  },
  "nav.sourcing": { guards: [["candidateAccess", "CandidateSearchAccess"]] },
  "nav.clients": DELIVERY_VIEW_MIRROR,
  "nav.my_clients": DELIVERY_VIEW_MIRROR,
  "nav.order_mail": DELIVERY_VIEW_MIRROR,
  "nav.my_relationships": DELIVERY_VIEW_MIRROR,
  "nav.contracts": DELIVERY_VIEW_MIRROR,
  // /api/finance/* → FinanceModuleUser (deps.py) = „Moduł Finanse”.
  "nav.finance": {
    permission: "finance_module",
    evidence: [{ alias: "FinanceModuleUser" }],
  },
  "nav.trainee": {
    productDecision:
      "Trasy praktykanta (/api/trainee/today|items/*) przyjmują tylko rolę trainee — bramka w api/trainee.py, bez aliasu w deps.py.",
  },
  "nav.trainees": {
    productDecision:
      "Panel praktykantów i reguły listy (/api/trainee/overview|programs|quality-sample|rules) — admin i Head of Recruitment, bramka w api/trainee.py.",
  },
};

describe("job.create = strażnik strony `/jobs/new`", () => {
  it("odczyt requestu stoi za RecruitmentManageUser, nie za rolą", () => {
    const source = backendSource("jobIntake");
    const guards = [...source.matchAll(/current_user:\s*(\w+)/g)].map((m) => m[1]);
    expect(guards).toContain("RecruitmentManageUser");
    expect(guards).not.toContain("DeliveryLeadPlus");
  });
});

function evidenceLabel(evidence: PermissionEvidence): string {
  if ("handler" in evidence) {
    return `${BACKEND_FILES[evidence.handler[0]]}::${evidence.handler[1]}`;
  }
  if ("alias" in evidence) return evidence.alias;
  return `${BACKEND_FILES[evidence.source[0]]} ~ ${evidence.source[1].source}`;
}

describe("kontrakt backend ↔ rejestr capability", () => {
  it("każda capability ma zadeklarowane lustro w backendzie", () => {
    // Nowa capability bez wpisu = nowa bramka bez ustalonego źródła prawdy.
    expect(Object.keys(CAPABILITY_BACKEND_MIRROR).sort()).toEqual(
      [...ALL_CAPABILITIES].sort(),
    );
  });

  it("lustro uprawnień obejmuje DOKŁADNIE capability z tabeli uprawnień", () => {
    const mirrored = ALL_CAPABILITIES.filter(
      (capability) => "permission" in CAPABILITY_BACKEND_MIRROR[capability],
    );
    expect([...mirrored].sort()).toEqual(Object.keys(CAPABILITY_PERMISSIONS).sort());
  });

  for (const capability of ALL_CAPABILITIES) {
    const mirror = CAPABILITY_BACKEND_MIRROR[capability];
    if ("guards" in mirror) {
      const label = mirror.guards
        .map(([file, symbol]) => `${file}.${symbol}`)
        .join(" ∪ ");
      it(`${capability} = ${label}`, () => {
        const expected = sortRoles(
          mirror.guards.flatMap(([file, symbol]) => backendRoles(file, symbol)),
        );
        expect(sortRoles(CAPABILITY_ROLES[capability])).toEqual(expected);
        // Strażnik rolowy: żadne uprawnienie z ekranu nie otwiera tej akcji.
        expect(CAPABILITY_PERMISSIONS[capability]).toBeUndefined();
      });
      continue;
    }
    if (!("permission" in mirror)) continue;

    it(`${capability} wymaga uprawnienia ${mirror.permission}`, () => {
      expect(CAPABILITY_PERMISSIONS[capability]).toBe(mirror.permission);
    });

    for (const evidence of mirror.evidence) {
      it(`${capability}: ${evidenceLabel(evidence)} pyta o ${mirror.permission}`, () => {
        if ("handler" in evidence) {
          expect(handlerPermission(...evidence.handler)).toBe(mirror.permission);
        } else if ("alias" in evidence) {
          expect(aliasPermission(evidence.alias)).toBe(mirror.permission);
        } else {
          // Wartość logiczna zamiast `toMatch`: przy porażce vitest wypisałby
          // cały plik Pythona zamiast jednego zdania.
          const [file, pattern] = evidence.source;
          expect(
            pattern.test(backendSource(file)),
            `${BACKEND_FILES[file]} nie zawiera ${pattern}`,
          ).toBe(true);
        }
      });
    }

    const legacy = mirror.legacyGuards ?? [];
    const legacyLabel =
      legacy.map(([file, symbol]) => `${file}.${symbol}`).join(" ∪ ") || "nikt";
    it(`${capability}: z tytułu roli — ${legacyLabel}`, () => {
      const expected = sortRoles(
        legacy.flatMap(([file, symbol]) => backendRoles(file, symbol)),
      );
      expect(sortRoles(CAPABILITY_ROLES[capability])).toEqual(expected);
    });
  }
});

// ───────────────────────────────────────────────────────────────────────────
// KONTRAKT SIDEBAR ↔ REJESTR (F-67, lustro nr 3)
//
// `NAV_SECTIONS` trzyma własne, ręcznie pisane tablice `roles`. Dopóki nikt ich
// nie porównywał z rejestrem, otwarcie powierzchni w backendzie i w rejestrze
// zostawiało sidebar zamknięty — użytkownik nigdy nie widział linku do funkcji,
// którą właśnie mu przyznano (to samo, co po #1212 przeżyło w in-page
// `RequireRole`).
// ───────────────────────────────────────────────────────────────────────────

/**
 * Role z sidebarem. Praktykant (0374) ma własną powłokę bez menu, więc nie
 * widzi ŻADNEJ pozycji — liczony tu robiłby z każdej pozycji „bramkowaną”.
 */
const SIDEBAR_ROLES = ALL_ROLES.filter((role) => role !== "trainee");

/** Role, dla których `visibleNavSections` pokazuje daną pozycję menu. */
function rolesSeeingHref(href: string): UserRole[] {
  return SIDEBAR_ROLES.filter((role) =>
    visibleNavSections(
      { role, roles: [role] },
      // `true`, żeby kolejka telefonów w ogóle pojawiła się w inwentarzu —
      // inaczej flaga wyłączona ukryłaby przed tym testem jej listę ról.
      { contactQueueEnabled: true },
    ).some((section) => section.items.some((item) => item.href === href)),
  );
}

/**
 * Pozycja sidebara → capability, której ma być lustrem: lista ról albo — dla
 * Delivery i Finansów — uprawnienie z ekranu (wtedy przy samej roli liczą się
 * domyślni posiadacze).
 */
const SIDEBAR_HREF_CAPABILITY: Record<string, Capability> = {
  "/candidates": "nav.candidates",
  // Wyszukiwarka i Talent Radar od 21.09.2026 nie stoją w menu (tryby ekranu
  // „Kandydaci”, wejście z ⌘K) — ich role pilnuje `nav-registry.test.ts`.
  // Talenty i Targ zdjęte z menu i palety 21.09.2026.
  "/clients": "nav.clients",
  // Panel klientów, Moje relacje i Zamówienia z maila od 22.09.2026 to tryby
  // ekranów Klienci / Kontrakty (wejście z ⌘K), więc nie mają pozycji menu.
  "/contracts": "nav.contracts",
  "/finance": "nav.finance",
  // Panel „Praktykanci” (0374) — w „Więcej” → Codzienna praca.
  "/trainees": "nav.trainees",
  // `/manager` przekierowuje na `/dashboard` — bez pozycji w menu i palecie
  // (capability `nav.manager` zdjęta 22.09.2026).
};

/**
 * Pozycje bramkowane rolami, które ŚWIADOMIE nie mają wpisu w rejestrze.
 * Lista jest zamknięta: nowa ręczna tablica `roles` w sidebarze robi czerwono,
 * dopóki ktoś nie zdecyduje, czy to capability, czy wyjątek — i nie zapisze tej
 * decyzji tutaj.
 */
const SIDEBAR_ROLE_GATED_WITHOUT_CAPABILITY: readonly string[] = [
  // Kolejka telefonów jest semantyką WYKONAWCZĄ (lustro backendowego
  // `ContactCaller`), nie wejściem nawigacyjnym do modułu — patrz komentarz
  // przy tym wpisie w middleware.ts.
  "/candidates/contact-queue",
  // Zgłoszenia z publicznych aplikacji: backend bramkuje je przez
  // CandidateWriteAccess + membership do oferty, więc sama lista ról nie
  // wystarcza do decyzji o widoczności ekranu.
  "/applications",
  // Kalendarz i Generator CV: lista ról tylko odcina legacy viewera `user`
  // (backend: RecruitmentReadAccess / CandidateWriteAccess); obie pozycje
  // należą do sekcji, a nie do osobnej capability nawigacyjnej.
  "/calendar",
  "/cv-generator",
  // Akademia (0369): tak jak Kalendarz — sekcja Pipeline + RecruiterPlus;
  // lista ról odcina tylko legacy viewera `user`.
  "/academy",
];

describe("kontrakt sidebar ↔ rejestr capability", () => {
  for (const [href, capability] of Object.entries(SIDEBAR_HREF_CAPABILITY)) {
    it(`${href} widoczne dokładnie dla ról z ${capability}`, () => {
      expect(sortRoles(rolesSeeingHref(href))).toEqual(
        sortRoles(
          SIDEBAR_ROLES.filter((role) => hasCapability(mkUser(role), capability)),
        ),
      );
    });
  }

  it("pozycje Delivery i Finansów idą za uprawnieniem, nie za rolą", () => {
    const seesHref = (user: Parameters<typeof visibleNavSections>[0], href: string) =>
      visibleNavSections(user, { contactQueueEnabled: true }).some((section) =>
        section.items.some((item) => item.href === href),
      );

    const viewer = accessSnapshot("recruiter", { grant: ["delivery_view"] });
    expect(seesHref(viewer, "/clients")).toBe(true);
    expect(seesHref(viewer, "/contracts")).toBe(true);
    expect(seesHref(viewer, "/finance")).toBe(false);

    const leadWithoutDelivery = accessSnapshot("delivery_lead", {
      revoke: [
        "delivery_view",
        "clients_edit",
        "contracts_orders_edit",
        "contract_status",
        "amounts_view",
      ],
    });
    expect(seesHref(leadWithoutDelivery, "/clients")).toBe(false);
    expect(seesHref(leadWithoutDelivery, "/contracts")).toBe(false);

    expect(
      seesHref(
        accessSnapshot("head_of_recruitment", { grant: ["finance_module"] }),
        "/finance",
      ),
    ).toBe(true);
    expect(
      seesHref(accessSnapshot("finance", { revoke: ["finance_module"] }), "/finance"),
    ).toBe(false);
  });

  it("żadna NOWA pozycja sidebara nie omija rejestru", () => {
    const gated = new Set<string>();
    for (const role of SIDEBAR_ROLES) {
      for (const section of visibleNavSections(
        { role, roles: [role] },
        { contactQueueEnabled: true },
      )) {
        for (const item of section.items) {
          if (rolesSeeingHref(item.href).length < SIDEBAR_ROLES.length) {
            gated.add(item.href);
          }
        }
      }
    }
    const unaccounted = [...gated]
      .filter((href) => !(href in SIDEBAR_HREF_CAPABILITY))
      .filter((href) => !SIDEBAR_ROLE_GATED_WITHOUT_CAPABILITY.includes(href))
      .sort();
    expect(unaccounted).toEqual([]);
  });
});

describe("praktykant nie widzi menu", () => {
  it("żadna pozycja sidebara nie jest widoczna dla samej roli `trainee`", () => {
    expect(
      visibleNavSections(
        { role: "trainee", roles: ["trainee"] },
        { contactQueueEnabled: true },
      ),
    ).toEqual([]);
  });
});
