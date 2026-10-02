import { describe, it, expect } from "vitest"

import { hasCapability } from "@/lib/capabilities"
import { accessSnapshot } from "@/lib/__tests__/fixtures/access-snapshot"

import {
  canEditOrderLineAmounts,
  canManageCandidateFinance,
  canManageContractStatus,
  canManageMultiConsultantOrders,
  canManageOrderLifecycle,
  canRecoverContractTermination,
  canViewCandidateFinance,
  canViewClientFinance,
  isClientInAssignedScope,
  hasSection,
  hasRole,
  hasMinRole,
  isTraineeOnly,
  onboardingPersona,
  postLoginDestination,
  requiresOnboarding,
  ROLE_LABELS,
  ROLE_RANK,
  shouldRouteToOnboarding,
  UserRole,
} from "./auth"

// Komplet ról z backendu (backend/app/models/user.py). `head_of_recruitment`
// był tu wcześniej pominięty — czyli jedyna rola, której hierarchia rang
// NIE odwzorowuje poprawnie, nie była w ogóle przemiatana testami (audyt F-19).
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
]

const mkUser = (role: UserRole) => ({ role })

// Bramki z uprawnień (0410). `mkUser(role)` to profil bez kompletu z serwera —
// liczy się z DOMYŚLNYCH uprawnień ról, czyli ze stanu startowego ekranu Osoby
// i role. `accessSnapshot(...)` to profil po `GET /api/auth/me`: z nadanym
// (`grant`) albo wyłączonym (`revoke`) uprawnieniem i portfelem Delivery Leada.

describe("canManageContractStatus — „Zakończenie współpracy, zmiana statusu kontraktu”", () => {
  it("domyślnie: admin, Delivery Lead i TCM", () => {
    const allowed = ALL_ROLES.filter((role) => canManageContractStatus(mkUser(role)))
    expect(allowed.sort()).toEqual(
      ["admin", "delivery_lead", "talent_community_manager"].sort(),
    )
    expect(canManageContractStatus(null)).toBe(false)
  })

  it("nadane rekruterowi — działa; wyłączone TCM i Delivery Leadowi — znika", () => {
    expect(
      canManageContractStatus(accessSnapshot("recruiter", { grant: ["contract_status"] })),
    ).toBe(true)
    expect(
      canManageContractStatus(
        accessSnapshot("talent_community_manager", { revoke: ["contract_status"] }),
      ),
    ).toBe(false)
    expect(
      canManageContractStatus(
        accessSnapshot("delivery_lead", { revoke: ["contract_status"] }),
      ),
    ).toBe(false)
  })

  it("Finanse zakładają kontrakty, ale statusu nie zmieniają", () => {
    expect(canManageContractStatus(accessSnapshot("finance"))).toBe(false)
  })

  it("sam odczyt Delivery już nie wystarcza TCM — status jest uprawnieniem z zapisem", () => {
    // Do 0410 TCM zmieniał status przy odczycie Delivery (wyjątek w bramce
    // sekcji). Teraz trasa wymaga zapisu, który wynika z uprawnienia; stary
    // wyjątek osoby ograniczający sekcję chowa kontrolkę.
    expect(
      canManageContractStatus(
        accessSnapshot("talent_community_manager", { sectionCaps: { delivery: "read" } }),
      ),
    ).toBe(false)
    expect(canManageContractStatus(accessSnapshot("talent_community_manager"))).toBe(true)
  })
})

describe("canManageOrderLifecycle — „Kontrakty i zamówienia: tworzenie i edycja”", () => {
  it("domyślnie: admin, Delivery Lead i Finanse", () => {
    const allowed = ALL_ROLES.filter((role) => canManageOrderLifecycle(mkUser(role)))
    expect(allowed.sort()).toEqual(["admin", "delivery_lead", "finance"].sort())
  })

  it("TCM z nadanym uprawnieniem kończy i przedłuża zamówienia; DL z wyłączonym — nie", () => {
    expect(
      canManageOrderLifecycle(
        accessSnapshot("talent_community_manager", { grant: ["contracts_orders_edit"] }),
      ),
    ).toBe(true)
    expect(
      canManageOrderLifecycle(
        accessSnapshot("delivery_lead", { revoke: ["contracts_orders_edit"] }),
      ),
    ).toBe(false)
  })

  it("sufit sekcji Delivery zostaje (stary wyjątek osoby, U8)", () => {
    expect(
      canManageOrderLifecycle(
        accessSnapshot("delivery_lead", { sectionCaps: { delivery: "read" } }),
      ),
    ).toBe(false)
  })
})

describe("canRecoverContractTermination — zostaje przy roli", () => {
  it("admin, Finanse i TCM z odczytem Delivery; Delivery Lead nie — także z kompletem uprawnień", () => {
    const allowed = ALL_ROLES.filter((role) => canRecoverContractTermination(mkUser(role)))
    expect(allowed.sort()).toEqual(["admin", "finance", "talent_community_manager"].sort())
    expect(canRecoverContractTermination(accessSnapshot("delivery_lead"))).toBe(false)
    // Uprawnienie do statusu nie jest tytułem do cofnięcia zakończenia.
    expect(
      canRecoverContractTermination(
        accessSnapshot("recruiter", { grant: ["contract_status", "contracts_orders_edit"] }),
      ),
    ).toBe(false)
    expect(
      canRecoverContractTermination(
        accessSnapshot("talent_community_manager", { sectionCaps: { delivery: "none" } }),
      ),
    ).toBe(false)
  })
})

describe("onboarding persona", () => {
  it("czyta pełną unię ról i preferuje Delivery Lead", () => {
    expect(
      onboardingPersona({
        role: "tac",
        roles: ["tac", "recruiter"],
      }),
    ).toBe("recruiter")
    expect(
      onboardingPersona({
        role: "recruiter",
        roles: ["recruiter", "delivery_lead"],
      }),
    ).toBe("delivery_lead")
  })

  it("Admin jest zwolniony, a secondary recruiter nadal wymaga onboardingu", () => {
    expect(
      requiresOnboarding({
        role: "admin",
        roles: ["admin", "delivery_lead"],
        profile_completed: false,
      }),
    ).toBe(false)
    expect(
      requiresOnboarding({
        role: "tac",
        roles: ["tac", "recruiter"],
        profile_completed: false,
      }),
    ).toBe(true)
  })

  it("wymuszona zmiana hasła ma pierwszeństwo przed onboardingiem", () => {
    const blockedByBoth = {
      role: "recruiter" as const,
      roles: ["recruiter" as const],
      profile_completed: false,
      force_password_change: true,
    }

    expect(requiresOnboarding(blockedByBoth)).toBe(true)
    expect(shouldRouteToOnboarding(blockedByBoth)).toBe(false)
    expect(postLoginDestination(blockedByBoth, "/jobs")).toBe(
      "/profile?force_password_change=1",
    )

    expect(
      postLoginDestination(
        { ...blockedByBoth, force_password_change: false },
        "/jobs",
      ),
    ).toBe("/onboarding")
    expect(
      postLoginDestination(
        {
          ...blockedByBoth,
          profile_completed: true,
          force_password_change: false,
        },
        "/jobs",
      ),
    ).toBe("/jobs")
  })
})

describe("hasRole", () => {
  it("returns false for null/undefined user", () => {
    expect(hasRole(null, "admin")).toBe(false)
    expect(hasRole(undefined, "admin")).toBe(false)
  })

  it("matches single role exactly", () => {
    expect(hasRole(mkUser("admin"), "admin")).toBe(true)
    expect(hasRole(mkUser("admin"), "delivery_lead")).toBe(false)
  })

  it("matches any role from multi-arg list", () => {
    const user = mkUser("tac")
    expect(hasRole(user, "admin", "delivery_lead", "tac")).toBe(true)
    expect(hasRole(user, "admin", "delivery_lead")).toBe(false)
  })

  it("is not hierarchical — higher role does NOT match lower", () => {
    // admin != recruiter even though admin rangowo wyższy
    expect(hasRole(mkUser("admin"), "recruiter")).toBe(false)
  })
})

describe("isClientInAssignedScope — uprawnienie mówi CO, zakres U KOGO", () => {
  it("konto z rolą Delivery Leada działa u klientów z przypisania", () => {
    const lead = accessSnapshot("delivery_lead", { assignedClientIds: [17] })
    expect(isClientInAssignedScope(lead, 17)).toBe(true)
    expect(isClientInAssignedScope(lead, 18)).toBe(false)
    // Rola dodatkowa też wiąże — hybryda HoR + DL nie wychodzi poza portfel.
    const hybrid = accessSnapshot("head_of_recruitment", {
      roles: ["delivery_lead"],
      assignedClientIds: [17],
    })
    expect(isClientInAssignedScope(hybrid, 18)).toBe(false)
  })

  it("pozostałych posiadaczy granica nie dotyczy, także admina z rolą DL", () => {
    expect(isClientInAssignedScope(accessSnapshot("finance"), 99)).toBe(true)
    expect(isClientInAssignedScope(accessSnapshot("recruiter"), 99)).toBe(true)
    expect(
      isClientInAssignedScope(accessSnapshot("admin", { roles: ["delivery_lead"] }), 99),
    ).toBe(true)
  })

  it("fail-closed: Delivery Lead bez listy z serwera nie ma żadnego klienta", () => {
    expect(isClientInAssignedScope({ role: "delivery_lead" }, 17)).toBe(false)
    expect(isClientInAssignedScope(null, 17)).toBe(false)
  })
})

describe("canManageCandidateFinance — „Stawki i kwoty: zmiana” (kwoty kontraktu)", () => {
  it("domyślnie: admin i Finanse (U6, 22.09)", () => {
    const allowed = ALL_ROLES.filter((role) => canManageCandidateFinance(mkUser(role)))
    expect(allowed.sort()).toEqual(["admin", "finance"].sort())
    expect(canManageCandidateFinance(accessSnapshot("finance"))).toBe(true)
    expect(canManageCandidateFinance(accessSnapshot("delivery_lead"))).toBe(false)
  })

  it("idzie za uprawnieniem, nie za rolą ani capability Finansów", () => {
    expect(
      canManageCandidateFinance(accessSnapshot("recruiter", { grant: ["amounts_edit"] })),
    ).toBe(true)
    expect(
      canManageCandidateFinance(accessSnapshot("finance", { revoke: ["amounts_edit"] })),
    ).toBe(false)
    // „Moduł Finanse” i zmiana kwot to dwa osobne przełączniki.
    expect(
      canManageCandidateFinance(accessSnapshot("finance", { revoke: ["finance_module"] })),
    ).toBe(true)
    // Samo `manage_finance` (capability modułu) nie daje zmiany kwot kontraktu.
    expect(
      canManageCandidateFinance({
        ...accessSnapshot("delivery_lead"),
        capabilities: ["manage_finance"],
      }),
    ).toBe(false)
  })

  it("Delivery Lead z nadaną zmianą kwot: tylko klienci z przypisania", () => {
    const lead = accessSnapshot("delivery_lead", {
      grant: ["amounts_edit"],
      assignedClientIds: [17],
    })
    expect(canManageCandidateFinance(lead, 17)).toBe(true)
    expect(canManageCandidateFinance(lead, 18)).toBe(false)
    // Bez klienta (lista, formularz przed wyborem) wystarcza niepusty portfel.
    expect(canManageCandidateFinance(lead)).toBe(true)
    expect(
      canManageCandidateFinance(accessSnapshot("delivery_lead", { grant: ["amounts_edit"] })),
    ).toBe(false)
  })

  it("brak użytkownika = brak; profil sprzed 0410 liczy się z domyślnych uprawnień roli", () => {
    expect(canManageCandidateFinance(null)).toBe(false)
    expect(canManageCandidateFinance(undefined)).toBe(false)
    expect(canManageCandidateFinance({ role: "admin" })).toBe(true)
    expect(canManageCandidateFinance({ role: "recruiter" })).toBe(false)
  })
})

describe("canViewCandidateFinance — „Stawki i kwoty: podgląd”", () => {
  it("pozwala Adminowi, Finance i DL z autorytatywnym zakresem klientów", () => {
    expect(canViewCandidateFinance({ role: "admin" })).toBe(true)
    expect(
      canViewCandidateFinance({
        role: "finance",
        capabilities: ["view_finance"],
      })
    ).toBe(true)
    expect(
      canViewCandidateFinance({
        role: "talent_community_manager",
        roles: ["talent_community_manager", "delivery_lead"],
        data_scope: {
          kind: "delivery_clients",
          user_id: 1,
          allowed_client_ids: [17],
          finance_client_ids: [17],
          allowed_tac_user_ids: [],
          allowed_operator_user_ids: [],
        },
      })
    ).toBe(true)
  })

  it("nie myli globalnego zakresu operacyjnego DL z portfelem finansowym", () => {
    const deliveryLead = {
      role: "delivery_lead" as const,
      data_scope: {
        kind: "delivery_clients" as const,
        user_id: 1,
        allowed_client_ids: [17, 18],
        finance_client_ids: [17],
        allowed_tac_user_ids: [],
        allowed_operator_user_ids: [],
      },
    }

    expect(canViewCandidateFinance(deliveryLead)).toBe(true)
    expect(canViewClientFinance(deliveryLead, 17)).toBe(true)
    expect(canViewClientFinance(deliveryLead, 18)).toBe(false)
  })

  it("nie zamienia prawa odczytu w prawo edycji", () => {
    const viewer = accessSnapshot("finance", { revoke: ["amounts_edit"] })

    expect(canViewCandidateFinance(viewer)).toBe(true)
    expect(canManageCandidateFinance(viewer)).toBe(false)
  })

  it("rekruter z nadanym podglądem kwot widzi stawki u wszystkich klientów", () => {
    const recruiter = accessSnapshot("recruiter", { grant: ["amounts_view"] })
    expect(canViewCandidateFinance(recruiter)).toBe(true)
    expect(canViewClientFinance(recruiter, 17)).toBe(true)
    expect(canViewClientFinance(recruiter, 999)).toBe(true)
    // …ale zmiany kwot to nie daje.
    expect(canManageCandidateFinance(recruiter)).toBe(false)
  })

  it("Delivery Lead z wyłączonym podglądem kwot nie widzi stawek nawet u swoich klientów", () => {
    const lead = accessSnapshot("delivery_lead", {
      revoke: ["amounts_view"],
      assignedClientIds: [17],
    })
    expect(canViewCandidateFinance(lead)).toBe(false)
    expect(canViewClientFinance(lead, 17)).toBe(false)
  })

  it("„Moduł Finanse” (capability view_finance) daje kwoty każdego klienta, także Delivery Leadowi", () => {
    const lead = accessSnapshot("delivery_lead", {
      grant: ["finance_module"],
      assignedClientIds: [17],
    })
    expect(lead.capabilities).toContain("view_finance")
    expect(canViewCandidateFinance(lead)).toBe(true)
    expect(canViewClientFinance(lead, 18)).toBe(true)
    // Starsze pole `analytics_capabilities` niesie to samo.
    expect(
      canViewClientFinance(
        {
          ...accessSnapshot("delivery_lead", {
            revoke: ["amounts_view"],
            assignedClientIds: [17],
          }),
          capabilities: undefined,
          analytics_capabilities: ["view_finance"],
        },
        18,
      ),
    ).toBe(true)
  })

  it("Finanse bez „Moduł Finanse” nadal widzą kwoty — podgląd kwot to osobne uprawnienie", () => {
    const finance = accessSnapshot("finance", { revoke: ["finance_module"] })
    expect(finance.capabilities).toEqual([])
    expect(canViewCandidateFinance(finance)).toBe(true)
    expect(canViewClientFinance(finance, 17)).toBe(true)
  })

  it("fail-closed: brak użytkownika, DL bez portfela i zwykły TCM", () => {
    expect(canViewCandidateFinance(null)).toBe(false)
    expect(canViewCandidateFinance(undefined)).toBe(false)
    expect(canViewCandidateFinance({ role: "delivery_lead" })).toBe(false)
    expect(canViewCandidateFinance(accessSnapshot("delivery_lead"))).toBe(false)
    expect(canViewClientFinance({ role: "delivery_lead" }, 17)).toBe(false)
    expect(
      canViewCandidateFinance({
        role: "talent_community_manager",
        data_scope: {
          kind: "recruitment_org",
          user_id: 1,
          allowed_client_ids: [],
          allowed_tac_user_ids: [],
          allowed_operator_user_ids: [],
        },
      })
    ).toBe(false)
    expect(canViewClientFinance(accessSnapshot("talent_community_manager"), 17)).toBe(false)
  })

  it("profil Finansów sprzed 0410 (bez capabilities) liczy się z domyślnych uprawnień roli", () => {
    // Do 0410 taki profil był zamknięty (brak `view_finance`). Teraz podgląd
    // kwot jest uprawnieniem, a stary profil czyta domyślne uprawnienia ról
    // do chwili, gdy `AppShellV2` dociągnie świeże `/api/auth/me`.
    expect(canViewCandidateFinance({ role: "finance" })).toBe(true)
    expect(canViewClientFinance({ role: "finance" }, 17)).toBe(true)
  })
})

describe("hasSection — DynaReporter", () => {
  it("Finance widzi odczytowe sekcje biznesowe nawet bez allowed_sections", () => {
    const businessSections = [
      "body-leasing",
      "sales",
      "delivery-lead",
      "placements",
      "clients-mrr",
      "competitions",
      "przetargi",
      "board",
      "sales-mgmt",
    ] as const

    for (const section of businessSections) {
      expect(hasSection({ role: "finance", allowed_sections: [] }, section)).toBe(
        true
      )
    }
  })

  it("Finance dostaje MINDY wyłącznie po jawnym przypisaniu", () => {
    expect(hasSection({ role: "finance", allowed_sections: [] }, "mindy")).toBe(
      false
    )
    expect(
      hasSection(
        { role: "finance", allowed_sections: ["mindy"] },
        "mindy"
      )
    ).toBe(true)
  })

  it("Finance nie dostaje sekcji admin nawet z wpisem w allowed_sections", () => {
    expect(
      hasSection(
        { role: "finance", allowed_sections: ["admin"] },
        "admin"
      )
    ).toBe(false)
  })

  it("Admin zachowuje override, a pozostałe role nadal używają allowlisty", () => {
    expect(hasSection({ role: "admin" }, "admin")).toBe(true)
    expect(hasSection({ role: "recruiter" }, "sales")).toBe(false)
    expect(
      hasSection(
        { role: "recruiter", allowed_sections: ["sales"] },
        "sales"
      )
    ).toBe(true)
  })
})

describe("hasMinRole", () => {
  it("returns false for null user", () => {
    expect(hasMinRole(null, "user")).toBe(false)
  })

  it("admin spełnia każde wymaganie minRole", () => {
    for (const minRole of ALL_ROLES) {
      expect(hasMinRole(mkUser("admin"), minRole)).toBe(true)
    }
  })

  it("user spełnia tylko operacyjne minRole=user", () => {
    const user = mkUser("user")
    // Finance i praktykant stoją poniżej viewera (rangi pomocnicze).
    for (const minRole of ALL_ROLES.filter((role) => role !== "finance" && role !== "trainee")) {
      expect(hasMinRole(user, minRole)).toBe(minRole === "user")
    }
  })

  it("praktykant nie przechodzi nawet legacy minRole=user", () => {
    expect(hasMinRole(mkUser("trainee"), "user")).toBe(false)
  })

  it("finance nie przechodzi nawet legacy minRole=user", () => {
    expect(hasMinRole(mkUser("finance"), "user")).toBe(false)
  })

  it("recruiter i sourcer są na tej samej randze", () => {
    expect(hasMinRole(mkUser("recruiter"), "sourcer")).toBe(true)
    expect(hasMinRole(mkUser("sourcer"), "recruiter")).toBe(true)
  })

  it("tac spełnia >= recruiter ale nie >= delivery_lead", () => {
    const user = mkUser("tac")
    expect(hasMinRole(user, "recruiter")).toBe(true)
    expect(hasMinRole(user, "tac")).toBe(true)
    expect(hasMinRole(user, "delivery_lead")).toBe(false)
    expect(hasMinRole(user, "admin")).toBe(false)
  })

  it("delivery_lead spełnia wszystko poza admin", () => {
    const user = mkUser("delivery_lead")
    expect(hasMinRole(user, "admin")).toBe(false)
    expect(hasMinRole(user, "delivery_lead")).toBe(true)
    expect(hasMinRole(user, "tac")).toBe(true)
    expect(hasMinRole(user, "recruiter")).toBe(true)
    expect(hasMinRole(user, "sourcer")).toBe(true)
    expect(hasMinRole(user, "user")).toBe(true)
  })
})

describe("RBAC gates: head_of_recruitment nie dziedziczy uprawnień DL/TAC", () => {
  const hor = mkUser("head_of_recruitment")
  const dl = mkUser("delivery_lead")
  const tac = mkUser("tac")
  const admin = mkUser("admin")

  // Bug u źródła: ROLE_RANK.head_of_recruitment (4.5) > delivery_lead (4) i
  // > tac (3), więc hasMinRole przepuszczał HoR przez bramki DL/TAC, których
  // backend mu NIE daje. Dokumentujemy złe zachowanie, żeby regresja była
  // widoczna, i dlatego bramki UI używają hasRole (exact), nie hasMinRole.
  it("hasMinRole BŁĘDNIE przepuszczał HoR przez bramki DL/TAC", () => {
    expect(hasMinRole(hor, "delivery_lead")).toBe(true)
    expect(hasMinRole(hor, "tac")).toBe(true)
  })

  // Dlatego bramki akcji NIE liczą rang, tylko czytają rejestr capability
  // (`lib/capabilities.ts`) — pełna macierz w `lib/__tests__/capabilities.test.ts`.
  it("HoR ma parytet z rekruterem (RecruiterPlus), ale nie bramki TAC/Delivery", () => {
    // Decyzja Artura 2026-09-17: HoR przechodzi RecruiterPlus (kandydat,
    // kalendarz, link aplikacyjny) — dalej NIE zakłada rekrutacji ani klientów.
    expect(hasCapability(hor, "candidate.create")).toBe(true)
    expect(hasCapability(hor, "calendar_event.create")).toBe(true)
    expect(hasCapability(hor, "invite_link.create")).toBe(true)
    expect(hasCapability(hor, "job.create")).toBe(false)
    expect(hasCapability(hor, "client.create")).toBe(false)
    // Delivery pozostaje zamknięte także dla zapisów kontaktów klienta.
    expect(hasCapability(hor, "contact.create")).toBe(false)
  })

  it("ranga HoR nadal jest wyższa od DL — dlatego capability, nie ranga", () => {
    expect(ROLE_RANK.head_of_recruitment).toBeGreaterThan(ROLE_RANK.delivery_lead)
    expect(hasCapability(hor, "job.create")).toBe(false)
    expect(hasCapability(dl, "job.create")).toBe(true)
  })

  it("bramka pin/reassign (admin+delivery_lead) wyklucza HoR i TAC", () => {
    expect(hasRole(hor, "admin", "delivery_lead")).toBe(false)
    expect(hasRole(tac, "admin", "delivery_lead")).toBe(false)
    expect(hasRole(dl, "admin", "delivery_lead")).toBe(true)
    expect(hasRole(admin, "admin", "delivery_lead")).toBe(true)
  })

  it("bramka Nowy klient dopuszcza tylko Admina i Delivery Leada", () => {
    expect(hasCapability(hor, "client.create")).toBe(false)
    expect(hasCapability(tac, "client.create")).toBe(false)
    expect(hasCapability(dl, "client.create")).toBe(true)
    expect(hasCapability(admin, "client.create")).toBe(true)
  })
})

describe("ROLE_RANK invariants", () => {
  it("admin jest najwyższy", () => {
    const maxRank = Math.max(...ALL_ROLES.map((r) => ROLE_RANK[r]))
    expect(ROLE_RANK.admin).toBe(maxRank)
  })

  it("finance jest celowo poniżej legacy user (fail-closed dla rank gates)", () => {
    const minRank = Math.min(...ALL_ROLES.map((r) => ROLE_RANK[r]))
    expect(ROLE_RANK.finance).toBe(minRank)
    expect(ROLE_RANK.finance).toBeLessThan(ROLE_RANK.user)
  })

  it("hierarchia: admin > delivery_lead > tac > recruiter = sourcer > user", () => {
    expect(ROLE_RANK.admin).toBeGreaterThan(ROLE_RANK.delivery_lead)
    expect(ROLE_RANK.delivery_lead).toBeGreaterThan(ROLE_RANK.tac)
    expect(ROLE_RANK.tac).toBeGreaterThan(ROLE_RANK.recruiter)
    expect(ROLE_RANK.recruiter).toBe(ROLE_RANK.sourcer)
    expect(ROLE_RANK.sourcer).toBeGreaterThan(ROLE_RANK.user)
  })

  it("praktykant jest najniżej z ról operacyjnych (poniżej sourcera i viewera)", () => {
    expect(ROLE_RANK.trainee).toBeLessThan(ROLE_RANK.sourcer)
    expect(ROLE_RANK.trainee).toBeLessThan(ROLE_RANK.user)
    expect(ROLE_RANK.trainee).toBeGreaterThan(ROLE_RANK.finance)
    expect(ROLE_LABELS.trainee).toBe("Praktykant")
  })
})

describe("praktykant (0374) — jeden ekran", () => {
  const trainee = {
    role: "trainee" as const,
    roles: ["trainee" as const],
    profile_completed: true,
    force_password_change: false,
  }

  it("po logowaniu zawsze trafia na „Telefony na dziś”, także z ?next=", () => {
    expect(postLoginDestination(trainee, "/jobs")).toBe("/trainee")
    expect(postLoginDestination(trainee)).toBe("/trainee")
  })

  it("wymuszona zmiana hasła nadal ma pierwszeństwo", () => {
    expect(postLoginDestination({ ...trainee, force_password_change: true }, "/jobs")).toBe(
      "/profile?force_password_change=1",
    )
  })

  it("isTraineeOnly: tylko rola `trainee` bez żadnej innej", () => {
    expect(isTraineeOnly(trainee)).toBe(true)
    expect(isTraineeOnly({ role: "trainee" })).toBe(true)
    expect(isTraineeOnly({ role: "admin", roles: ["admin", "trainee"] })).toBe(false)
    expect(isTraineeOnly({ role: "recruiter" })).toBe(false)
    expect(isTraineeOnly(null)).toBe(false)
  })
})

describe("canManageMultiConsultantOrders", () => {
  // „Kontrakty i zamówienia: tworzenie i edycja” u klienta z zakresu konta
  // razem z podglądem jego kwot (lustro `ClientContractsEditUser`
  // + `can_write_order_amounts`). Świadomie SZERSZE niż
  // `canManageCandidateFinance`: obsadę zamówienia prowadzi delivery, więc
  // wymóg zmiany kwot czynił zakładkę bezużyteczną dla osób, które ją
  // faktycznie obsługują.
  it("przepuszcza admina i delivery leada", () => {
    expect(canManageMultiConsultantOrders({ role: "admin", roles: [] }, 17)).toBe(true)
    expect(
      canManageMultiConsultantOrders({
        role: "delivery_lead",
        roles: [],
        data_scope: {
          kind: "delivery_clients",
          user_id: 1,
          allowed_client_ids: [17, 18],
          finance_client_ids: [17],
          allowed_tac_user_ids: [],
          allowed_operator_user_ids: [],
        },
      }, 17)
    ).toBe(true)
    expect(
      canManageMultiConsultantOrders({
        role: "delivery_lead",
        roles: [],
        data_scope: {
          kind: "delivery_clients",
          user_id: 1,
          allowed_client_ids: [17, 18],
          finance_client_ids: [17],
          allowed_tac_user_ids: [],
          allowed_operator_user_ids: [],
        },
      }, 18)
    ).toBe(false)
  })

  it("Finanse prowadzą zamówienia u każdego klienta (decyzja Artura 02.10.2026)", () => {
    expect(canManageMultiConsultantOrders({ role: "finance", roles: [] }, 17)).toBe(true)
    expect(canManageMultiConsultantOrders(accessSnapshot("finance"), 999)).toBe(true)
  })

  it("nie przepuszcza pozostałych ról", () => {
    // Head of Recruitment nie ma podglądu Delivery; TCM czyta i zmienia status,
    // ale zamówień nie prowadzi.
    for (const role of [
      "head_of_recruitment",
      "talent_community_manager",
      "tac",
      "recruiter",
      "sourcer",
      "user",
      "trainee",
    ] as UserRole[]) {
      expect(canManageMultiConsultantOrders({ role, roles: [] }, 17)).toBe(false)
    }
    expect(canManageMultiConsultantOrders(null, 17)).toBe(false)
  })

  it("nadane uprawnienie bez podglądu kwot nie wystarcza — formularze niosą stawki", () => {
    // TCM z „Kontrakty i zamówienia” (bez „Stawki i kwoty: podgląd”): backend
    // odmówiłby stawek i PDF-u z nazwą brakującego uprawnienia.
    const tcm = accessSnapshot("talent_community_manager", {
      grant: ["contracts_orders_edit"],
    })
    expect(canManageMultiConsultantOrders(tcm, 17)).toBe(false)
    expect(canEditOrderLineAmounts(tcm, 17)).toBe(false)
    const withAmounts = accessSnapshot("talent_community_manager", {
      grant: ["contracts_orders_edit", "amounts_view"],
    })
    expect(canManageMultiConsultantOrders(withAmounts, 17)).toBe(true)
    expect(canEditOrderLineAmounts(withAmounts, 17)).toBe(true)
  })

  it("Delivery Lead z wyłączonym uprawnieniem nie prowadzi zamówień nawet u swoich klientów", () => {
    const lead = accessSnapshot("delivery_lead", {
      revoke: ["contracts_orders_edit"],
      assignedClientIds: [17],
    })
    expect(canManageMultiConsultantOrders(lead, 17)).toBe(false)
    expect(canEditOrderLineAmounts(lead, 17)).toBe(false)
  })

  it("Delivery Lead z „Moduł Finanse” widzi kwoty wszędzie, ale zamówienia prowadzi tylko u swoich klientów", () => {
    const lead = accessSnapshot("delivery_lead", {
      grant: ["finance_module"],
      assignedClientIds: [17],
    })
    expect(canViewClientFinance(lead, 18)).toBe(true)
    expect(canManageMultiConsultantOrders(lead, 17)).toBe(true)
    expect(canManageMultiConsultantOrders(lead, 18)).toBe(false)
  })

  it("czyta też role dodatkowe, nie tylko primary", () => {
    expect(
      canManageMultiConsultantOrders({
        role: "tac",
        roles: ["delivery_lead"],
        data_scope: {
          kind: "delivery_clients",
          user_id: 1,
          allowed_client_ids: [17],
          finance_client_ids: [17],
          allowed_tac_user_ids: [],
          allowed_operator_user_ids: [],
        },
      }, 17)
    ).toBe(true)
  })
})

describe("canEditOrderLineAmounts — kwoty linii zamówienia", () => {
  // Lustro `can_write_order_amounts`: „Stawki i kwoty: zmiana” w zakresie konta
  // ALBO prowadzenie zamówień z podglądem kwot klienta.
  it("domyślnie: admin, Finanse i Delivery Lead u klienta z przypisania", () => {
    expect(canEditOrderLineAmounts(accessSnapshot("admin"), 17)).toBe(true)
    expect(canEditOrderLineAmounts(accessSnapshot("finance"), 17)).toBe(true)
    const lead = accessSnapshot("delivery_lead", { assignedClientIds: [17] })
    expect(canEditOrderLineAmounts(lead, 17)).toBe(true)
    expect(canEditOrderLineAmounts(lead, 18)).toBe(false)
    for (const role of [
      "head_of_recruitment",
      "talent_community_manager",
      "tac",
      "recruiter",
      "sourcer",
      "user",
      "trainee",
    ] as UserRole[]) {
      expect(canEditOrderLineAmounts(accessSnapshot(role), 17)).toBe(false)
    }
    expect(canEditOrderLineAmounts(null, 17)).toBe(false)
  })

  it("sama zmiana kwot (bez prowadzenia zamówień) daje wyłącznie tryb „Edytuj stawki”", () => {
    // `amountsOnly` w zakładce zamówień = canEditOrderLineAmounts && !canManage:
    // backend wpuszcza taką osobę na PATCH linii tylko z polami kwot.
    const amountsOnly = accessSnapshot("recruiter", { grant: ["amounts_edit"] })
    expect(canEditOrderLineAmounts(amountsOnly, 17)).toBe(true)
    expect(canManageMultiConsultantOrders(amountsOnly, 17)).toBe(false)

    const financeWithoutOrders = accessSnapshot("finance", {
      revoke: ["contracts_orders_edit"],
    })
    expect(canEditOrderLineAmounts(financeWithoutOrders, 17)).toBe(true)
    expect(canManageMultiConsultantOrders(financeWithoutOrders, 17)).toBe(false)
  })

  it("Finanse bez zmiany kwot nadal zmieniają kwoty zamówień, bo je prowadzą i widzą", () => {
    const finance = accessSnapshot("finance", { revoke: ["amounts_edit"] })
    expect(canEditOrderLineAmounts(finance, 17)).toBe(true)
    expect(canManageCandidateFinance(finance)).toBe(false)
  })

  it("Delivery Lead z nadaną zmianą kwot zostaje w swoim portfelu", () => {
    const lead = accessSnapshot("delivery_lead", {
      grant: ["amounts_edit"],
      revoke: ["contracts_orders_edit"],
      assignedClientIds: [17],
    })
    expect(canEditOrderLineAmounts(lead, 17)).toBe(true)
    expect(canEditOrderLineAmounts(lead, 18)).toBe(false)
  })
})
