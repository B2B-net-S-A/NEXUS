import { describe, expect, it } from "vitest"

import cases from "@/lib/__fixtures__/request-work-state-cases.json"
import type { BoardRequest, LoadPerson, RequestBoard } from "@/lib/api/requestAllocation"
import {
  EMPTY_FILTERS,
  activeFilterCount,
  boardPeople,
  deadlineLabel,
  filtersFromParams,
  filtersToParams,
  groupRequests,
  hasActiveFilters,
  leadOptions,
  loadBarScale,
  loadSummary,
  matchesFilters,
  needsRecruiter,
  orderLoad,
  orderRequests,
  outsideP1Href,
  p1LoadLabel,
  p1Word,
  pendingProposalCount,
  recruiterPickOptions,
  requestWord,
  sentBound,
  sentRangeLabel,
  unstaffedCount,
} from "@/lib/request-board"
import { visibleState } from "@/lib/request-work-state"

const TODAY = "2026-09-24"

function req(partial: Partial<BoardRequest> & { job_id: number }): BoardRequest {
  return {
    title: `Request ${partial.job_id}`,
    client_name: "Nordea",
    category_id: 2,
    deadline: null,
    sent: 0,
    champion: false,
    people: [],
    ...partial,
  }
}

const board: RequestBoard = {
  mode: "shadow",
  availability_known: false,
  groups: [
    { category_id: 1, name: "Infra", slug: "infrastructure_operations", total: 1, searching: 1, champion: 0 },
    { category_id: 2, name: "Development", slug: "software_development", total: 3, searching: 2, champion: 1 },
  ],
  requests: [
    req({ job_id: 1, category_id: 1, title: "DevOps Engineer", client_name: "Polkomtel", deadline: "2026-09-30", priority_level: "p1", delivery_lead: { id: 31, name: "Gosia Delivery" } }),
    req({ job_id: 2, title: "Senior Java Developer", deadline: "2026-09-26", delivery_lead: { id: 32, name: "Adam Lider" }, people: [{ user_id: 7, name: "Anna Przykładowa", proposed: false, source: "auto" }] }),
    req({ job_id: 3, title: "React Developer", sent: 3, champion: true, deadline: "2026-09-28", priority_level: "accepting" }),
    // Sama propozycja automatu — nikt jeszcze nie pracuje.
    req({ job_id: 4, title: "Kotlin Developer", sent: 1, deadline: "2026-09-20", delivery_lead: { id: 31, name: "Gosia Delivery" }, people: [{ user_id: 8, name: "Bartek Testowy", proposed: true, source: "auto" }] }),
  ],
  load: [],
  changes: [],
}

describe("visibleState", () => {
  it.each(cases.cases)("$work_state + champion=$champion → $visible", (c) => {
    expect(visibleState(c.work_state, c.champion ? "2026-09-24T09:00:00Z" : null)).toBe(c.visible)
  })
})

describe("filters", () => {
  it("round-trip through the URL keeps unrelated params", () => {
    const base = new URLSearchParams("tab=x")
    const filters = { ...EMPTY_FILTERS, client: ["Nordea"], due: ["late" as const], who: ["7"] }
    const params = filtersToParams(filters, base)
    expect(params.get("tab")).toBe("x")
    expect(filtersFromParams(params)).toEqual(filters)
  })

  it("ignores unknown due/sent values from a hand-edited URL", () => {
    const parsed = filtersFromParams(new URLSearchParams("rb_due=soon&rb_sent=9"))
    expect(parsed.due).toEqual([])
    expect(parsed.sent).toEqual([])
  })

  it("Delivery Lead, priorytet i „Bez rekrutera” żyją w adresie pod kluczami rb_", () => {
    const filters = { ...EMPTY_FILTERS, lead: ["31"], prio: ["p1" as const], nobody: "1" as const }
    const params = filtersToParams(filters, new URLSearchParams())
    expect(params.toString()).toBe("rb_lead=31&rb_prio=p1&rb_nobody=1")
    expect(filtersFromParams(params)).toEqual(filters)
    expect(hasActiveFilters(filters)).toBe(true)
    expect(hasActiveFilters(EMPTY_FILTERS)).toBe(false)
  })

  it("nieznany priorytet i przełącznik spoza „1” z ręcznie wpisanego adresu nic nie filtrują", () => {
    const parsed = filtersFromParams(new URLSearchParams("rb_prio=p9&rb_nobody=tak"))
    expect(parsed.prio).toEqual([])
    expect(parsed.nobody).toBe("")
  })

  it("title search ignores Polish characters and case", () => {
    const row = req({ job_id: 9, title: "Specjalista ds. bezpieczeństwa" })
    expect(matchesFilters(row, { ...EMPTY_FILTERS, q: "BEZPIECZENSTWA" }, TODAY)).toBe(true)
  })

  it("pole „Stanowisko” znajduje request po numerze u klienta", () => {
    const row = req({ job_id: 10, title: "Java Developer", client_reference: "REQ-48213" })
    expect(matchesFilters(row, { ...EMPTY_FILTERS, q: "48213" }, TODAY)).toBe(true)
    expect(matchesFilters(row, { ...EMPTY_FILTERS, q: "99999" }, TODAY)).toBe(false)
    expect(matchesFilters(req({ job_id: 11 }), { ...EMPTY_FILTERS, q: "48213" }, TODAY)).toBe(false)
  })

  it("deadline buckets", () => {
    const late = req({ job_id: 1, deadline: "2026-09-20" })
    const week = req({ job_id: 2, deadline: "2026-09-30" })
    const none = req({ job_id: 3 })
    const f = (due: "late" | "week" | "two" | "none") => ({ ...EMPTY_FILTERS, due: [due] })
    expect([late, week, none].filter((r) => matchesFilters(r, f("late"), TODAY)).map((r) => r.job_id)).toEqual([1])
    expect([late, week, none].filter((r) => matchesFilters(r, f("week"), TODAY)).map((r) => r.job_id)).toEqual([2])
    expect([late, week, none].filter((r) => matchesFilters(r, f("none"), TODAY)).map((r) => r.job_id)).toEqual([3])
  })

  it("sent buckets keep champions apart", () => {
    const f = (sent: "0" | "12" | "3" | "champ") => ({ ...EMPTY_FILTERS, sent: [sent] })
    const ids = (sent: "0" | "12" | "3" | "champ") =>
      board.requests.filter((r) => matchesFilters(r, f(sent), TODAY)).map((r) => r.job_id)
    expect(ids("0")).toEqual([1, 2])
    expect(ids("12")).toEqual([4])
    expect(ids("3")).toEqual([])
    expect(ids("champ")).toEqual([3])
  })

  const idsFor = (filters: Partial<typeof EMPTY_FILTERS>) =>
    board.requests
      .filter((r) => matchesFilters(r, { ...EMPTY_FILTERS, ...filters }, TODAY))
      .map((r) => r.job_id)

  it("„Rekruter” liczy osobę, która pracuje — propozycja automatu to za mało", () => {
    expect(idsFor({ who: ["7"] })).toEqual([2])
    // Bartek ma przy requeście 4 tylko propozycję.
    expect(idsFor({ who: ["8"] })).toEqual([])
  })

  it("Delivery Lead: po id, a `none` = requesty bez Delivery Leada", () => {
    expect(idsFor({ lead: ["31"] })).toEqual([1, 4])
    expect(idsFor({ lead: ["32"] })).toEqual([2])
    expect(idsFor({ lead: ["none"] })).toEqual([3])
    expect(leadOptions(board)).toEqual({
      options: [
        { id: "32", name: "Adam Lider" },
        { id: "31", name: "Gosia Delivery" },
      ],
      hasNone: true,
    })
    expect(leadOptions({ requests: board.requests.filter((r) => r.delivery_lead) }).hasNone).toBe(false)
  })

  it("priorytet: brak pola z serwera to P2 (stan domyślny)", () => {
    expect(idsFor({ prio: ["p1"] })).toEqual([1])
    expect(idsFor({ prio: ["accepting"] })).toEqual([3])
    expect(idsFor({ prio: ["p2"] })).toEqual([2, 4])
  })

  it("kilka wartości w jednym filtrze = dowolna z nich; między filtrami wszystkie", () => {
    expect(idsFor({ lead: ["32", "none"] })).toEqual([2, 3])
    expect(idsFor({ prio: ["p1", "accepting"] })).toEqual([1, 3])
    expect(idsFor({ cat: ["1", "2"] })).toEqual([1, 2, 3, 4])
    // Termin: po terminie (4) albo do 7 dni (1, 2, 3).
    expect(idsFor({ due: ["late", "week"] })).toEqual([1, 2, 3, 4])
    expect(idsFor({ lead: ["31", "32"], prio: ["p2"] })).toEqual([2, 4])
    expect(idsFor({ sent: ["0", "champ"] })).toEqual([1, 2, 3])
  })

  it("kilka wartości w adresie: powtórzony klucz, stary link z jedną wartością działa", () => {
    const filters = {
      ...EMPTY_FILTERS,
      client: ["Nordea", "Bank, S.A."],
      cat: ["1", "none"],
      sent: ["0" as const, "champ" as const],
      sentFrom: "2",
      sentTo: "5",
    }
    const params = filtersToParams(filters, new URLSearchParams())
    expect(params.getAll("rb_client")).toEqual(["Nordea", "Bank, S.A."])
    expect(params.get("rb_sent_from")).toBe("2")
    expect(filtersFromParams(params)).toEqual(filters)
    expect(filtersFromParams(new URLSearchParams("rb_cat=4&rb_sent=12")).cat).toEqual(["4"])
    // Zdjęcie filtra czyści wszystkie powtórzenia klucza.
    expect(filtersToParams(EMPTY_FILTERS, params).toString()).toBe("")
  })

  it("„Wysłani”: własny przedział od–do, razem z zaznaczonymi pozycjami, bez championów", () => {
    const rows = [
      req({ job_id: 1, sent: 0 }),
      req({ job_id: 2, sent: 2 }),
      req({ job_id: 3, sent: 4 }),
      req({ job_id: 4, sent: 7 }),
      req({ job_id: 5, sent: 5, champion: true }),
    ]
    const ids = (f: Partial<typeof EMPTY_FILTERS>) =>
      rows.filter((r) => matchesFilters(r, { ...EMPTY_FILTERS, ...f }, TODAY)).map((r) => r.job_id)
    expect(ids({ sentFrom: "2", sentTo: "5" })).toEqual([2, 3])
    expect(ids({ sentFrom: "4" })).toEqual([3, 4])
    expect(ids({ sentTo: "2" })).toEqual([1, 2])
    // Odwrócone granice czytamy jako ten sam przedział.
    expect(ids({ sentFrom: "5", sentTo: "2" })).toEqual([2, 3])
    // Przedział i pozycja z listy: wystarczy jedno z nich.
    expect(ids({ sentFrom: "6", sent: ["0", "champ"] })).toEqual([1, 4, 5])
  })

  it("„Wysłani”: granice tylko z liczb całkowitych, w liczniku jeden filtr", () => {
    const parsed = filtersFromParams(new URLSearchParams("rb_sent_from=-1&rb_sent_to=3.5"))
    expect(parsed.sentFrom).toBe("")
    expect(parsed.sentTo).toBe("")
    expect(sentBound(" 07 ")).toBe("7")
    expect(sentRangeLabel({ sentFrom: "2", sentTo: "5" })).toBe("2–5")
    expect(sentRangeLabel({ sentFrom: "3", sentTo: "" })).toBe("od 3")
    expect(sentRangeLabel({ sentFrom: "", sentTo: "4" })).toBe("do 4")
    expect(sentRangeLabel({ sentFrom: "3", sentTo: "3" })).toBe("3")
    const range = { ...EMPTY_FILTERS, sent: ["0" as const], sentFrom: "1" }
    expect(activeFilterCount(range)).toBe(1)
    expect(hasActiveFilters({ ...EMPTY_FILTERS, sentTo: "2" })).toBe(true)
    expect(activeFilterCount({ ...EMPTY_FILTERS, client: ["A", "B"], cat: ["1"] })).toBe(2)
    expect(activeFilterCount(EMPTY_FILTERS)).toBe(0)
  })

  it("„Bez rekrutera”: nikt nie pracuje — także przy samej propozycji; champion się nie liczy", () => {
    expect(board.requests.filter(needsRecruiter).map((r) => r.job_id)).toEqual([1, 4])
    expect(idsFor({ nobody: "1" })).toEqual([1, 4])
    // Liczba na przełączniku = tyle wierszy zostanie przy pozostałych filtrach.
    expect(unstaffedCount(board, EMPTY_FILTERS, TODAY)).toBe(2)
    expect(unstaffedCount(board, { ...EMPTY_FILTERS, lead: ["32"] }, TODAY)).toBe(0)
    expect(unstaffedCount(board, { ...EMPTY_FILTERS, cat: ["1"], nobody: "1" }, TODAY)).toBe(1)
  })
})

describe("kto jest przy requeście", () => {
  const working = { user_id: 7, name: "Anna Przykładowa", proposed: false, source: "manual" as const }
  const proposal = { user_id: 8, name: "Bartek Testowy", proposed: true, source: "auto" as const }

  it("propozycję pokazujemy tylko wtedy, gdy nikt nie pracuje", () => {
    expect(boardPeople({ people: [proposal] })).toEqual([proposal])
    // Ktoś już pracuje — propozycja jest nieaktualna (serwer odmówiłby akceptacji).
    expect(boardPeople({ people: [working, proposal] })).toEqual([working])
    expect(boardPeople({ people: [] })).toEqual([])
    // Request z championem wypada z puli automatu — propozycja jest nieaktualna
    // i „Akceptuj” skończyłoby się odmową.
    expect(boardPeople({ people: [proposal], champion: true })).toEqual([])
    expect(boardPeople({ people: [proposal], champion: false })).toEqual([proposal])
  })

  it("liczy propozycje czekające na decyzję", () => {
    expect(pendingProposalCount(board)).toBe(1)
    expect(
      pendingProposalCount({ requests: [req({ job_id: 9, people: [working, proposal] })] }),
    ).toBe(0)
  })
})

describe("obłożenie", () => {
  const person = (user_id: number, name: string, count: number, proposed?: number) => ({
    user_id,
    name,
    count,
    proposed,
    leave_until: null,
    requests: [],
  })

  it("kolejność po requestach w pracy; propozycje jej nie zmieniają", () => {
    const load = [person(1, "Zofia", 1, 3), person(2, "Adam", 2), person(3, "Bogna", 1)]
    expect(orderLoad(load).map((p) => p.name)).toEqual(["Adam", "Bogna", "Zofia"])
    // Wejście zostaje nietknięte.
    expect(load.map((p) => p.name)).toEqual(["Zofia", "Adam", "Bogna"])
  })

  it("„2 + 1” i to samo słowami — obłożenie to rekrutacje P1 (14.10.2026)", () => {
    expect(loadSummary(person(1, "A", 2, 1))).toEqual({
      label: "2 + 1",
      spoken: "2 rekrutacje P1 · 1 propozycja do akceptacji",
    })
    expect(loadSummary(person(1, "A", 0, 2))).toEqual({
      label: "0 + 2",
      spoken: "0 rekrutacji P1 · 2 propozycje do akceptacji",
    })
    expect(loadSummary(person(1, "A", 5, 5)).spoken).toBe(
      "5 rekrutacji P1 · 5 propozycji do akceptacji",
    )
    // Starszy backend nie oddaje `proposed` — sama liczba.
    expect(loadSummary(person(1, "A", 1))).toEqual({ label: "1", spoken: "1 rekrutacja P1" })
    expect(loadSummary(person(1, "A", 3, 0))).toEqual({ label: "3", spoken: "3 rekrutacje P1" })
  })

  it("„N P1” w okienkach wyboru i odmiana „rekrutacja P1”", () => {
    expect([0, 1, 4].map(p1LoadLabel)).toEqual(["0 P1", "1 P1", "4 P1"])
    expect([1, 2, 5, 22].map(p1Word)).toEqual([
      "rekrutacja P1",
      "rekrutacje P1",
      "rekrutacji P1",
      "rekrutacje P1",
    ])
  })

  it("pasek: najbardziej obłożona osoba (z propozycjami) ma pełny pasek, pusta lista nie dzieli przez zero", () => {
    expect(loadBarScale([person(1, "A", 8), person(2, "B", 6, 3), person(3, "C", 0)])).toBe(9)
    expect(loadBarScale([person(1, "A", 0)])).toBe(1)
    expect(loadBarScale([])).toBe(1)
  })

  it("„Pokaż na liście rekrutacji”: otwarte, „Szukamy”, osoba, bez P1", () => {
    const href = outsideP1Href(7)
    expect(href.startsWith("/jobs?")).toBe(true)
    const params = new URLSearchParams(href.slice("/jobs?".length))
    expect(params.get("open")).toBe("1")
    expect(params.getAll("stage")).toEqual(["searching"])
    expect(params.getAll("who")).toEqual(["7"])
    expect(params.get("prio")).toBe("p2,accepting")
  })
})

describe("grouping", () => {
  it("champion goes to the bottom of its group, the rest by deadline", () => {
    expect(orderRequests(board.requests.filter((r) => r.category_id === 2)).map((r) => r.job_id)).toEqual([4, 2, 3])
  })

  it("P0 stoi na górze kategorii przed terminem i championem; wygasłe P0 nie", () => {
    const now = new Date("2026-10-27T09:09:00Z")
    const rows = [
      req({ job_id: 1, category_id: 9, deadline: "2026-10-28", champion: false }),
      req({ job_id: 2, category_id: 9, deadline: "2026-12-01", champion: false, is_p0: true, p0_until: "2026-10-28T09:09:00Z" }),
      req({ job_id: 3, category_id: 9, deadline: "2026-10-27", champion: false, is_p0: true, p0_until: "2026-10-27T09:00:00Z" }),
    ]
    expect(orderRequests(rows, now).map((r) => r.job_id)).toEqual([2, 3, 1])
  })

  it("filtered group says N z M and empty groups disappear", () => {
    const { groups, shown, total } = groupRequests(board, { ...EMPTY_FILTERS, q: "java" }, TODAY)
    expect(total).toBe(4)
    expect(shown).toBe(1)
    expect(groups.map((g) => [g.name, g.shownLabel])).toEqual([["Development", "1 z 3 requestów"]])
  })

  it("polish plural for requests", () => {
    expect([1, 2, 5, 12, 22, 25].map(requestWord)).toEqual([
      "request",
      "requesty",
      "requestów",
      "requestów",
      "requesty",
      "requestów",
    ])
  })

  it("deadline label speaks Polish", () => {
    expect(deadlineLabel("2026-09-23", TODAY)).toBe("po terminie 1 dzień")
    expect(deadlineLabel("2026-09-25", TODAY)).toBe("jutro")
    expect(deadlineLabel(null, TODAY)).toBe("brak terminu")
  })
})

describe("zakres kafelka i daily", () => {
  it("scopeFilters: kategoria widza, DL-em widz, „wszystkie” bez filtra", async () => {
    const { scopeFilters } = await import("@/lib/request-board")
    const viewer = { user_id: 31, primary_category_id: 2 }
    expect(scopeFilters("my_category", viewer)).toEqual({ cat: ["2"] })
    expect(scopeFilters("my_lead", viewer)).toEqual({ lead: ["31"] })
    expect(scopeFilters("all", viewer)).toEqual({})
    // Bez kategorii albo bez danych o widzu — wszystkie requesty, nie pusta tabela.
    expect(scopeFilters("my_category", { user_id: 31, primary_category_id: null })).toEqual({})
    expect(scopeFilters("my_lead", null)).toEqual({})
    expect(scopeFilters("my_category", undefined)).toEqual({})
    // Wartości w formacie filtrów: zakres „Moja kategoria” wybiera grupę Development.
    const scoped = { ...EMPTY_FILTERS, ...scopeFilters("my_category", viewer) }
    expect(board.requests.filter((r) => matchesFilters(r, scoped, TODAY)).map((r) => r.job_id)).toEqual([2, 3, 4])
    const lead = { ...EMPTY_FILTERS, ...scopeFilters("my_lead", viewer) }
    expect(board.requests.filter((r) => matchesFilters(r, lead, TODAY)).map((r) => r.job_id)).toEqual([1, 4])
  })

  it("hasUrlFilters: tylko niepuste `rb_*`", async () => {
    const { hasUrlFilters } = await import("@/lib/request-board")
    expect(hasUrlFilters(new URLSearchParams("tab=x"))).toBe(false)
    expect(hasUrlFilters(new URLSearchParams("rb_cat="))).toBe(false)
    expect(hasUrlFilters(new URLSearchParams("rb_cat=4"))).toBe(true)
    expect(hasUrlFilters(new URLSearchParams("rb_nobody=1"))).toBe(true)
  })

  it("nextCategory: po kolei grupy, z ostatniej na „Wszystkie”", async () => {
    const { nextCategory } = await import("@/lib/request-board")
    const groups = [{ category_id: 1 }, { category_id: 2 }, { category_id: null }]
    expect(nextCategory(groups, "")).toBe("1")
    expect(nextCategory(groups, "1")).toBe("2")
    expect(nextCategory(groups, "2")).toBe("none")
    expect(nextCategory(groups, "none")).toBe("")
    expect(nextCategory(groups, "99")).toBe("1")
    expect(nextCategory([], "")).toBe("")
  })

  it("changesSinceLabel: dzień tygodnia w dopełniaczu i godzina w czasie firmy", async () => {
    const { changesSinceLabel } = await import("@/lib/request-board")
    expect(changesSinceLabel("2026-10-02T07:30:00Z")).toBe("od piątku 9:30")
    // Zimą Warszawa to UTC+1.
    expect(changesSinceLabel("2026-12-01T13:05:00Z")).toBe("od wtorku 14:05")
    expect(changesSinceLabel(null)).toBeNull()
    expect(changesSinceLabel("nie-data")).toBeNull()
  })
})

describe("lista wyboru rekrutera (kolumna „Rekruter” listy)", () => {
  const directory = [
    { id: 1, name: "Zofia Przykładowa", role: "recruiter", roles: ["recruiter"] },
    { id: 2, name: "Michał Testowy", role: "recruiter", roles: ["recruiter"] },
    { id: 3, name: "Anna Wzorcowa", role: "recruiter", roles: ["recruiter"] },
    // Delivery Lead bez roli rekrutera — serwer odmówi (409), więc go nie ma.
    { id: 4, name: "Damian Lider", role: "delivery_lead", roles: ["delivery_lead"] },
    // Rola rekrutera jako dodatkowa wystarcza.
    { id: 5, name: "Celina Dodatkowa", role: "delivery_lead", roles: ["delivery_lead", "recruiter"] },
    { id: 6, name: "Bartek Nieaktywny", role: "recruiter", roles: ["recruiter"], is_active: false },
  ]
  const load: LoadPerson[] = [
    { user_id: 1, name: "Zofia Przykładowa", count: 0, proposed: 1, leave_until: null, requests: [] },
    { user_id: 2, name: "Michał Testowy", count: 3, leave_until: null, requests: [] },
    { user_id: 3, name: "Anna Wzorcowa", count: 1, leave_until: "2026-10-20", requests: [] },
  ]

  it("od najmniej obłożonej, urlop na końcu, osoby spoza obłożenia za nimi alfabetycznie", () => {
    const options = recruiterPickOptions(directory, load, [], "")
    expect(options.map((o) => o.user_id)).toEqual([1, 2, 3, 5])
    expect(options[0]).toEqual({
      user_id: 1,
      name: "Zofia Przykładowa",
      count: 0,
      proposed: 1,
      leave_until: null,
    })
    // Spoza puli automatu: liczby nie znamy, więc jej nie zgadujemy.
    expect(options[3]).toMatchObject({ user_id: 5, count: null, proposed: 0 })
  })

  it("pomija osoby, które już pracują, bez roli rekrutera i nieaktywne", () => {
    const ids = recruiterPickOptions(directory, load, [2], "").map((o) => o.user_id)
    expect(ids).not.toContain(2)
    expect(ids).not.toContain(4)
    expect(ids).not.toContain(6)
  })

  it("szuka bez polskich znaków i wielkości liter", () => {
    expect(recruiterPickOptions(directory, load, [], "michal").map((o) => o.user_id)).toEqual([2])
    expect(recruiterPickOptions(directory, load, [], "  PRZYKŁAD ").map((o) => o.user_id)).toEqual([1])
  })

  it("bez obłożenia (awaria pulpitu) zostaje sama lista alfabetycznie", () => {
    const options = recruiterPickOptions(directory, null, [], "")
    expect(options.map((o) => o.name)).toEqual([
      "Anna Wzorcowa",
      "Celina Dodatkowa",
      "Michał Testowy",
      "Zofia Przykładowa",
    ])
    expect(options.every((o) => o.count === null)).toBe(true)
  })
})

describe("boardPeople na osobach z wiersza listy", () => {
  it("przyjmuje osoby z `recruiters` rekrutacji (bez pola `source`)", () => {
    const working = { user_id: 1, name: "A", proposed: false, via: "owner" as const, assigned_by_name: null }
    const proposal = { user_id: 2, name: "B", proposed: true, via: "assignment" as const, assigned_by_name: null }
    expect(boardPeople({ people: [working, proposal] })).toEqual([working])
    expect(boardPeople({ people: [proposal] })).toEqual([proposal])
  })
})
