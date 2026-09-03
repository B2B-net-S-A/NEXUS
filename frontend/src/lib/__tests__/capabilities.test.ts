import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { visibleNavSections } from "@/components/v2/shell/SidebarV2";
import {
  CAPABILITY_ROLES,
  hasAnyCapability,
  hasCapability,
  type Capability,
} from "@/lib/capabilities";
import type { UserRole } from "@/store/auth";

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
];

const mkUser = (role: UserRole) => ({ role });

/**
 * Oczekiwana macierz capability × rola. Pisana ręcznie (a nie wyliczana
 * z rejestru), żeby każda zmiana uprawnień była świadomym diffem w PR,
 * a nie cichym efektem ubocznym.
 *
 * `true` = akcja widoczna i klikalna, `false` = ukryta.
 */
const EXPECTED: Record<
  Capability,
  Record<Exclude<UserRole, "finance" | "talent_community_manager">, boolean>
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
  // POST /api/clients → TacPlus narrowed by the Delivery section write gate
  "client.create": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // PATCH /api/clients/{id} → TacPlus narrowed by the Delivery section write gate
  "client.update": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // PUT/POST confirm/DELETE /api/clients/{id}/cv-rule → DeliveryLeadPlus.
  // TAC celowo na false (decyzja 02.09.2026): edytuje kartę klienta, ale
  // reguł CV nie prowadzi — kontrolki mają być dla niego niewidoczne.
  "cv_rule.manage": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // POST /api/contracts → TacPlus narrowed by the Delivery section write gate
  "contract.create": {
    admin: true,
    head_of_recruitment: false,
    delivery_lead: true,
    tac: false,
    recruiter: false,
    sourcer: false,
    user: false,
  },
  // ClientAccess.can_edit_contacts → ADMIN_LIKE ∪ CLIENT_TEAM
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
  // CandidateWriteAccess = CANDIDATE_WRITE_ROLES (RecruiterPlus, bez HoR).
  // HoR czyta teczkę, ale nie wgrywa — upload dostałby 403.
  "candidate.document.manage": {
    admin: true,
    head_of_recruitment: false,
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
  "nav.cortex": {
    admin: true,
    head_of_recruitment: true,
    delivery_lead: true,
    tac: true,
    recruiter: true,
    sourcer: true,
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
  // /api/finance/* → require_roles(admin, finance) — moduł własny finance
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
};

/**
 * Reguła dla `finance` (decyzja produktowa Artura 19.08 — pełny dostęp
 * operacyjny): Finance ma tier recruitera, własny moduł oraz jawne moduły
 * business-read kontraktów, klientów i Cortex. Wyliczana z macierzy, nie ręczna
 * lista — dzięki temu nowa capability przyznana recruiterowi automatycznie obejmuje finance, a
 * odstępstwo od reguły wymaga świadomej zmiany tej funkcji.
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
      "nav.cortex",
    ].includes(capability)
  ) {
    return true;
  }
  return EXPECTED[capability].recruiter;
}

function talentCommunityManagerExpected(capability: Capability): boolean {
  return [
    "candidate.create",
    "calendar_event.create",
    "invite_link.create",
    "candidate.document.manage",
    "candidate.profile_fact.manage",
    "dashboard.recruitment_stats.view",
    "nav.candidates",
    "nav.talents",
    "nav.talent_radar",
    "nav.sourcing",
    "nav.clients",
    "nav.my_clients",
    "nav.order_mail",
    "nav.my_relationships",
    "nav.contracts",
    "nav.cortex",
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

  it("żadna capability nie jest pusta (martwa bramka blokująca wszystkich)", () => {
    for (const capability of ALL_CAPABILITIES) {
      expect(CAPABILITY_ROLES[capability].length).toBeGreaterThan(0);
    }
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
    // Hybryda HoR + TCM — HoR sam nie zakłada kandydatów, TCM tak.
    const hybrid = {
      role: "head_of_recruitment" as UserRole,
      roles: ["head_of_recruitment", "talent_community_manager"] as UserRole[],
    };
    expect(hasCapability(mkUser("head_of_recruitment"), "candidate.create")).toBe(
      false,
    );
    expect(hasCapability(hybrid, "candidate.create")).toBe(true);
  });

  it("brak `roles` (stary cache localStorage) fallbackuje na primary `role`", () => {
    expect(hasCapability({ role: "tac" }, "job.create")).toBe(true);
    expect(hasCapability({ role: "recruiter" }, "job.create")).toBe(false);
  });

  it("admin ma wszystko — żadna bramka go nie blokuje", () => {
    for (const capability of ALL_CAPABILITIES) {
      expect(hasCapability(mkUser("admin"), capability)).toBe(true);
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
    expect(hasCapability(mkUser("finance"), "nav.cortex")).toBe(true);
  });

  it("Talent Community Manager ma biznes bez Finansów i tylko odczyt Delivery", () => {
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
  });

  it("efektywna sekcja zawęża akcje do read i może całkiem ukryć nawigację", () => {
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

  it("indywidualny grant sekcji nie omija węższej reguły roli", () => {
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
  });
});

describe("regresja C6: teczka plików \u2260 fakty profilowe (granica po HoR)", () => {
  it("HoR edytuje fakty globalne, ale nie wgrywa plik\u00f3w", () => {
    const hor = mkUser("head_of_recruitment");
    // CandidateProfileFacts*Access = _INTERNAL_OPERATIONAL_ROLES (z HoR).
    expect(hasCapability(hor, "candidate.profile_fact.manage")).toBe(true);
    // CandidateWriteAccess = CANDIDATE_WRITE_ROLES (bez HoR) \u2192 upload = 403.
    // Ta asercja p\u0119ka, gdy kto\u015b „upro\u015bci" oba wpisy do jednego \u2014 r\u00f3\u017cnica
    // mi\u0119dzy nimi to dok\u0142adnie HoR i jest niewidoczna w code review od strony UI.
    expect(hasCapability(hor, "candidate.document.manage")).toBe(false);
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
    const visible = QUICK_ACTIONS.filter((c) =>
      hasCapability(mkUser("head_of_recruitment"), c),
    );
    expect(visible).toEqual([]);
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

  it("kontrakt i firma dzielą bramkę Delivery, a rekrutacja zostaje w Pipeline", () => {
    for (const role of ALL_ROLES) {
      const contract = hasCapability(mkUser(role), "contract.create");
      expect(hasCapability(mkUser(role), "client.create")).toBe(contract);
    }
    expect(hasCapability(mkUser("tac"), "job.create")).toBe(true);
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
// Świadomie POZA zakresem: `middleware.ts` nie eksportuje `ROLE_ROUTES`, więc
// jego lustro trzeba domknąć osobno — tam też zaczyna się od eksportu tablicy.
// ───────────────────────────────────────────────────────────────────────────

const BACKEND_FILES = {
  deps: "backend/app/api/deps.py",
  contracts: "backend/app/api/contracts.py",
  candidateAccess: "backend/app/api/candidate_access.py",
  recruitmentAccess: "backend/app/api/recruitment_access.py",
  clientAccess: "backend/app/services/client_access.py",
  cortex: "backend/app/api/cortex.py",
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
function readBackendAssignments(file: BackendFile): Map<string, string> {
  const source = readFileSync(join(REPO_ROOT, BACKEND_FILES[file]), "utf8");
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

const BACKEND_ASSIGNMENTS = new Map<BackendFile, Map<string, string>>(
  (Object.keys(BACKEND_FILES) as BackendFile[]).map(
    (file): [BackendFile, Map<string, string>] => [
      file,
      readBackendAssignments(file),
    ],
  ),
);

/** Zbiór ról stojący za nazwanym strażnikiem backendu. Rzuca, gdy symbol
 *  zniknął albo został przemianowany — cichy brak byłby gorszy niż czerwony
 *  test, bo zamieniłby kontrakt w zawsze-zielony no-op. */
function backendRoles(file: BackendFile, symbol: string): UserRole[] {
  const assignments = BACKEND_ASSIGNMENTS.get(file)!;
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
 * Capability → strażnik(-e) backendu, których jest lustrem. `guards` znaczy
 * „ma być DOKŁADNIE sumą tych zbiorów" (nie podzbiorem — podzbiór przepuszcza
 * drugi kierunek awarii: backend otwarty, a UI dalej chowa funkcję).
 * `productDecision` = świadomy brak pojedynczego strażnika; wymuszony wpis
 * sprawia, że nowa capability nie prześlizgnie się bez decyzji.
 */
const CAPABILITY_BACKEND_MIRROR: Record<
  Capability,
  { guards: readonly GuardRef[] } | { productDecision: string }
> = {
  "candidate.create": { guards: [["deps", "RecruiterPlus"]] },
  "job.create": { guards: [["deps", "TacPlus"]] },
  "job.update": { guards: [["deps", "TacPlus"]] },
  "client.create": {
    productDecision:
      "TacPlus intersected with the Delivery section write matrix; TAC is section-denied, leaving Admin and Delivery Lead.",
  },
  "client.update": {
    productDecision:
      "TacPlus intersected with the Delivery section write matrix; TAC is section-denied, leaving Admin and Delivery Lead.",
  },
  "cv_rule.manage": { guards: [["deps", "DeliveryLeadPlus"]] },
  "contract.create": {
    productDecision:
      "TacPlus intersected with the Delivery section write matrix; TAC is section-denied, leaving Admin and Delivery Lead.",
  },
  // ClientAccess.can_edit_contacts = ADMIN_LIKE ∪ CLIENT_TEAM.
  "contact.create": {
    productDecision:
      "ClientAccess writers intersected with the Delivery section write matrix; only Admin and scoped Delivery Lead remain.",
  },
  "calendar_event.create": {
    guards: [["recruitmentAccess", "CALENDAR_WRITE_ROLES"]],
  },
  "invite_link.create": { guards: [["deps", "RecruiterPlus"]] },
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
  "nav.talents": { guards: [["candidateAccess", "CandidateSearchAccess"]] },
  "nav.talent_radar": {
    productDecision:
      "Oba endpointy radaru stoją na CurrentUser (decyzja 19.08) — nie ma zbioru ról do porównania, bramką jest samo zalogowanie.",
  },
  "nav.sourcing": { guards: [["candidateAccess", "CandidateSearchAccess"]] },
  "nav.clients": {
    productDecision:
      "GET /api/clients is additionally protected by the central Delivery section dependency.",
  },
  "nav.my_clients": {
    productDecision:
      "GET /api/my-clients is protected by Delivery section access; Admin, Finance, TCM and scoped Delivery Lead can read it.",
  },
  "nav.order_mail": {
    productDecision:
      "Order-mail is a Delivery surface: Admin/Finance/TCM read organization-wide, DL reads its portfolio, and only Admin/scoped DL may apply.",
  },
  "nav.my_relationships": {
    productDecision:
      "GET /api/my-relationships is protected by Delivery section access; Admin, Finance, TCM and scoped Delivery Lead can read it.",
  },
  "nav.contracts": {
    productDecision:
      "ContractReadUser is intersected with the central Delivery section read matrix.",
  },
  "nav.cortex": { guards: [["cortex", "CortexUser"]] },
  "nav.manager": { guards: [["deps", "DeliveryLeadPlus"]] },
  "nav.finance": { guards: [["deps", "FinanceModuleUser"]] },
};

describe("kontrakt backend ↔ rejestr capability", () => {
  it("każda capability ma zadeklarowane lustro w backendzie", () => {
    // Nowa capability bez wpisu = nowa bramka bez ustalonego źródła prawdy.
    expect(Object.keys(CAPABILITY_BACKEND_MIRROR).sort()).toEqual(
      [...ALL_CAPABILITIES].sort(),
    );
  });

  for (const capability of ALL_CAPABILITIES) {
    const mirror = CAPABILITY_BACKEND_MIRROR[capability];
    if (!("guards" in mirror)) continue;
    const label = mirror.guards
      .map(([file, symbol]) => `${file}.${symbol}`)
      .join(" ∪ ");
    it(`${capability} = ${label}`, () => {
      const expected = sortRoles(
        mirror.guards.flatMap(([file, symbol]) => backendRoles(file, symbol)),
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

/** Role, dla których `visibleNavSections` pokazuje daną pozycję menu. */
function rolesSeeingHref(href: string): UserRole[] {
  return ALL_ROLES.filter((role) =>
    visibleNavSections(
      { role, roles: [role] },
      // `true`, żeby kolejka telefonów w ogóle pojawiła się w inwentarzu —
      // inaczej flaga wyłączona ukryłaby przed tym testem jej listę ról.
      { contactQueueEnabled: true },
    ).some((section) => section.items.some((item) => item.href === href)),
  );
}

/** Pozycja sidebara → capability, której lista `roles` ma być lustrem. */
const SIDEBAR_HREF_CAPABILITY: Record<string, Capability> = {
  "/candidates": "nav.candidates",
  "/talents": "nav.talents",
  "/talent-radar": "nav.talent_radar",
  "/sourcing/marketplace": "nav.sourcing",
  "/clients": "nav.clients",
  "/my-clients": "nav.my_clients",
  "/order-mail": "nav.order_mail",
  "/my-relationships": "nav.my_relationships",
  "/contracts": "nav.contracts",
  "/cortex": "nav.cortex",
  "/finance": "nav.finance",
  // `nav.manager` (/manager) NIE ma dziś pozycji w sidebarze — „Panel Managera"
  // jest zakomentowany od 2026-05-28. Bramkę pilnuje middleware.
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
];

describe("kontrakt sidebar ↔ rejestr capability", () => {
  for (const [href, capability] of Object.entries(SIDEBAR_HREF_CAPABILITY)) {
    it(`${href} widoczne dokładnie dla ról z ${capability}`, () => {
      expect(sortRoles(rolesSeeingHref(href))).toEqual(
        sortRoles(CAPABILITY_ROLES[capability]),
      );
    });
  }

  it("żadna NOWA pozycja sidebara nie omija rejestru", () => {
    const gated = new Set<string>();
    for (const role of ALL_ROLES) {
      for (const section of visibleNavSections(
        { role, roles: [role] },
        { contactQueueEnabled: true },
      )) {
        for (const item of section.items) {
          if (rolesSeeingHref(item.href).length < ALL_ROLES.length) {
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
