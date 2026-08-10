import { describe, expect, it } from "vitest"

import {
  CAPABILITY_ROLES,
  hasAnyCapability,
  hasCapability,
  type Capability,
} from "@/lib/capabilities"
import type { UserRole } from "@/store/auth"

// Wszystkie role z backendu (backend/app/models/user.py). Macierz MUSI być
// domknięta — `head_of_recruitment` bywał pomijany w listach testowych i to
// właśnie jego brak przepuszczał bramki, których backend mu nie daje (F-19).
const ALL_ROLES: UserRole[] = [
  "admin",
  "finance",
  "head_of_recruitment",
  "delivery_lead",
  "tac",
  "recruiter",
  "sourcer",
  "user",
]

const mkUser = (role: UserRole) => ({ role })

/**
 * Oczekiwana macierz capability × rola. Pisana ręcznie (a nie wyliczana
 * z rejestru), żeby każda zmiana uprawnień była świadomym diffem w PR,
 * a nie cichym efektem ubocznym.
 *
 * `true` = akcja widoczna i klikalna, `false` = ukryta.
 */
const EXPECTED: Record<
  Capability,
  Record<Exclude<UserRole, "finance">, boolean>
> = {
  // POST /api/candidates → RecruiterPlus (bez HoR!)
  "candidate.create": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  // POST /api/jobs → TacPlus
  "job.create": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: true,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // PATCH /api/jobs/{id} → TacPlus. HoR celowo na false: inline-edycja pól
  // oferty dostałaby 403, więc kontrolka ma być dla niego niewidoczna.
  "job.update": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: true,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // POST /api/clients → TacPlus
  "client.create": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: true,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // PATCH /api/clients/{id} → TacPlus (bramka przycisku "Edytuj" na karcie)
  "client.update": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: true,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // POST /api/contracts → TacPlus
  "contract.create": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: true,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // ClientAccess.can_edit_contacts → ADMIN_LIKE ∪ CLIENT_TEAM
  "contact.create": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // CalendarWriteAccess → CALENDAR_WRITE_ROLES (bez HoR)
  "calendar_event.create": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  // POST /api/invite-links → RecruiterPlus
  "invite_link.create": {
    admin: true,
    head_of_recruitment: false,
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
  "nav.talents": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
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
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
    user: false,
  },
  "nav.my_clients": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  "nav.my_relationships": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  "nav.contracts": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: true,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  "nav.cortex": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  "nav.manager": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
}

const ALL_CAPABILITIES = Object.keys(CAPABILITY_ROLES) as Capability[]

describe("rejestr capability — kompletność", () => {
  it("każda capability z rejestru ma wpis w oczekiwanej macierzy", () => {
    expect(Object.keys(EXPECTED).sort()).toEqual([...ALL_CAPABILITIES].sort())
  })

  it("każda capability wymienia wyłącznie znane role", () => {
    for (const capability of ALL_CAPABILITIES) {
      for (const role of CAPABILITY_ROLES[capability]) {
        expect(ALL_ROLES).toContain(role)
      }
    }
  })

  it("żadna capability nie jest pusta (martwa bramka blokująca wszystkich)", () => {
    for (const capability of ALL_CAPABILITIES) {
      expect(CAPABILITY_ROLES[capability].length).toBeGreaterThan(0)
    }
  })
})

describe("hasCapability — pełna macierz rola × capability", () => {
  for (const capability of ALL_CAPABILITIES) {
    for (const role of ALL_ROLES) {
      // Finance jest rolą ekskluzywną. Istniejący rejestr opisuje wyłącznie
      // capability operacyjne, więc wszystkie są dla niej fail-closed.
      const expected =
        role === "finance" ? false : EXPECTED[capability][role]
      it(`${role} ${expected ? "MA" : "NIE ma"} ${capability}`, () => {
        expect(hasCapability(mkUser(role), capability)).toBe(expected)
      })
    }
  }
})

describe("hasCapability — przypadki brzegowe", () => {
  it("fail-closed dla braku usera", () => {
    for (const capability of ALL_CAPABILITIES) {
      expect(hasCapability(null, capability)).toBe(false)
      expect(hasCapability(undefined, capability)).toBe(false)
    }
  })

  it("multi-role: druga rola nadaje uprawnienie, którego primary nie ma", () => {
    // Hybryda HoR + TAC — HoR sam nie zakłada firm, TAC tak.
    const hybrid = { role: "head_of_recruitment" as UserRole, roles: ["head_of_recruitment", "tac"] as UserRole[] }
    expect(hasCapability(mkUser("head_of_recruitment"), "client.create")).toBe(false)
    expect(hasCapability(hybrid, "client.create")).toBe(true)
  })

  it("brak `roles` (stary cache localStorage) fallbackuje na primary `role`", () => {
    expect(hasCapability({ role: "tac" }, "job.create")).toBe(true)
    expect(hasCapability({ role: "recruiter" }, "job.create")).toBe(false)
  })

  it("admin ma wszystko — żadna bramka go nie blokuje", () => {
    for (const capability of ALL_CAPABILITIES) {
      expect(hasCapability(mkUser("admin"), capability)).toBe(true)
    }
  })

  it("rola `user` (read-only viewer) nie ma NICZEGO", () => {
    for (const capability of ALL_CAPABILITIES) {
      expect(hasCapability(mkUser("user"), capability)).toBe(false)
    }
  })

  it("rola `finance` nie dziedziczy żadnej capability operacyjnej", () => {
    for (const capability of ALL_CAPABILITIES) {
      expect(hasCapability(mkUser("finance"), capability)).toBe(false)
    }
  })
})

describe("hasAnyCapability", () => {
  it("zwraca true gdy choć jedna capability przechodzi", () => {
    expect(
      hasAnyCapability(mkUser("recruiter"), "job.create", "candidate.create")
    ).toBe(true)
  })

  it("zwraca false gdy żadna nie przechodzi", () => {
    expect(
      hasAnyCapability(mkUser("user"), "job.create", "candidate.create")
    ).toBe(false)
  })

  it("bez argumentów zwraca false (fail-closed)", () => {
    expect(hasAnyCapability(mkUser("admin"))).toBe(false)
  })
})

describe("regresja F-19: Quick Actions nie pokazuje akcji bez capability", () => {
  const QUICK_ACTIONS: Capability[] = [
    "candidate.create",
    "job.create",
    "client.create",
    "contact.create",
    "calendar_event.create",
    "invite_link.create",
  ]

  it("read-only viewer nie widzi ŻADNEJ akcji Quick Actions", () => {
    const visible = QUICK_ACTIONS.filter((c) => hasCapability(mkUser("user"), c))
    expect(visible).toEqual([])
  })

  it("sourcer widzi tylko kandydata, spotkanie i link aplikacyjny", () => {
    const visible = QUICK_ACTIONS.filter((c) =>
      hasCapability(mkUser("sourcer"), c)
    )
    expect(visible).toEqual([
      "candidate.create",
      "calendar_event.create",
      "invite_link.create",
    ])
  })

  it("head_of_recruitment widzi tylko osobę kontaktową", () => {
    const visible = QUICK_ACTIONS.filter((c) =>
      hasCapability(mkUser("head_of_recruitment"), c)
    )
    expect(visible).toEqual(["contact.create"])
  })
})

describe("regresja F-19: żadna akcja tworzenia nie omija rejestru", () => {
  // Komplet capability typu `*.create` — także tych bramkowanych poza Quick
  // Actions (nagłówki list, zakładki profilu klienta, strona szczegółów oferty).
  const CREATE_CAPABILITIES = ALL_CAPABILITIES.filter((c) =>
    c.endsWith(".create")
  )

  it("każda akcja tworzenia ma wpis w rejestrze", () => {
    expect(CREATE_CAPABILITIES).toEqual([
      "candidate.create",
      "job.create",
      "client.create",
      "contract.create",
      "contact.create",
      "calendar_event.create",
      "invite_link.create",
    ])
  })

  it("read-only viewer nie tworzy NICZEGO", () => {
    for (const capability of CREATE_CAPABILITIES) {
      expect(hasCapability(mkUser("user"), capability)).toBe(false)
    }
  })

  it("recruiter/sourcer nie tworzą kontraktów, rekrutacji, firm ani kontaktów", () => {
    for (const role of ["recruiter", "sourcer"] as UserRole[]) {
      expect(hasCapability(mkUser(role), "contract.create")).toBe(false)
      expect(hasCapability(mkUser(role), "job.create")).toBe(false)
      expect(hasCapability(mkUser(role), "client.create")).toBe(false)
      expect(hasCapability(mkUser(role), "contact.create")).toBe(false)
    }
  })

  it("kontrakt, rekrutacja i firma dzielą tę samą bramkę (TacPlus)", () => {
    for (const role of ALL_ROLES) {
      const contract = hasCapability(mkUser(role), "contract.create")
      expect(hasCapability(mkUser(role), "job.create")).toBe(contract)
      expect(hasCapability(mkUser(role), "client.create")).toBe(contract)
    }
  })
})
