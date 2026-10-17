import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { HrConfig, HrModuleKey } from "@/lib/api/hr"
import type { LeaveRequestRow } from "@/lib/api/hr-leave"
import { useAuthStore, type User } from "@/store/auth"

import { EquipmentTasksTile, equipmentTaskStats } from "../EquipmentTasksTile"
import { HrApprovalsTile, approvalsLabel } from "../HrApprovalsTile"
import { HrMyTimeTile, nearestApprovedLeave } from "../HrMyTimeTile"
import { HrSubstitutionTile, warningText } from "../HrSubstitutionTile"
import { HrTileGate } from "../HrTileGate"
import { TileCatalogSheet } from "../TileCatalogSheet"

// Odpowiedzi API po adresie; brak wpisu = awaria (500), żeby test widział,
// że kafelek nie zamienia jej w zero.
let routes: Record<string, unknown> = {}

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  const api = {
    get: async (url: string) => {
      const key = Object.keys(routes).find((route) => url === route || url.startsWith(route))
      if (key === undefined) {
        throw Object.assign(new Error("boom"), { response: { status: 500 } })
      }
      return { data: routes[key] }
    },
  }
  return { ...actual, api, default: api }
})

const MODULES: HrModuleKey[] = ["people", "leave", "time", "payroll", "lifecycle", "care", "cases", "equipment"]

function hrConfig(
  open: Partial<Record<HrModuleKey, boolean>> = { leave: true, time: true, equipment: true },
  me: Partial<HrConfig["me"]> = {},
): HrConfig {
  const modules = Object.fromEntries(MODULES.map((key) => [key, open[key] ?? false])) as Record<
    HrModuleKey,
    boolean
  >
  return {
    modules,
    open_modules: modules,
    me: {
      has_profile: true,
      employment_status: "active",
      is_manager: false,
      direct_reports: 0,
      is_admin: false,
      people_admin: false,
      payroll: false,
      equipment: false,
      cases: false,
      ...me,
    },
  }
}

function renderWith(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

function leaveRow(values: Partial<LeaveRequestRow>): LeaveRequestRow {
  return {
    id: "r1",
    user_id: 7,
    user_name: "Anna Przykładowa",
    leave_type: "vacation",
    leave_type_label: "Urlop wypoczynkowy",
    status: "approved",
    start_date: "2099-12-23",
    end_date: "2099-12-31",
    half_day: null,
    days_total: "5",
    paid_days: "5",
    unpaid_days: "0",
    note: null,
    substitute_user_id: null,
    substitute_name: null,
    forward_mail_consent: false,
    oof_internal_message: null,
    oof_external_message: null,
    decided_by_name: null,
    decided_at: null,
    decision_note: null,
    source: "self",
    created_at: null,
    can_cancel: true,
    ...values,
  }
}

beforeEach(() => {
  routes = {}
  useAuthStore.setState({
    user: { id: 7, role: "recruiter", roles: ["recruiter"] } as unknown as User,
    hydrated: true,
  })
})

describe("„W zastępstwie”", () => {
  const item = {
    owner_user_id: 5,
    owner_name: "Kamil Przykładowy",
    start_date: "2026-10-19",
    end_date: "2026-10-23",
    recruitments: {
      count: 3,
      items: [
        { job_id: 1, title: "Java Developer", client_name: "Bank Przykładowy" },
        { job_id: 2, title: "QA Engineer", client_name: null },
      ],
    },
    client_meetings: { count: 2, items: [] },
    pipeline_cards: 7,
  }

  it("pokazuje, za kogo i do kiedy, oraz pracę z silnika", async () => {
    routes["/api/hr/dashboard/substitution"] = {
      enabled: true,
      fresh: true,
      items: [item],
      warnings: [],
    }
    renderWith(<HrSubstitutionTile />)
    const card = await screen.findByRole("region", { name: "Zastępstwo: Kamil Przykładowy" })
    expect(within(card).getByText(/Zastępujesz: Kamil Przykładowy/)).toBeInTheDocument()
    expect(within(card).getByText("· do pt 23.10")).toBeInTheDocument()
    expect(within(card).getByText("rekrutacje")).toBeInTheDocument()
    expect(within(card).getByText("Java Developer · Bank Przykładowy, QA Engineer")).toBeInTheDocument()
    expect(within(card).getByText("rozmowy u klienta")).toBeInTheDocument()
    expect(within(card).getByText("kandydatów w procesie")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Otwórz pracę w „Moich” rekrutacjach" })).toHaveAttribute(
      "href",
      "/jobs?mine=1",
    )
  })

  it("awaria to blok błędu z ponowieniem — ani zer, ani „nikogo nie zastępujesz”", async () => {
    renderWith(<HrSubstitutionTile />)
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument()
    expect(screen.queryByText("Dziś nikogo nie zastępujesz.")).toBeNull()
    expect(screen.queryByText("0")).toBeNull()
  })

  it("pusto: spokojne zdanie; bez źródła urlopów — kiedy ruszy", async () => {
    routes["/api/hr/dashboard/substitution"] = { enabled: true, fresh: true, items: [], warnings: [] }
    const { unmount } = renderWith(<HrSubstitutionTile />)
    expect(await screen.findByText("Dziś nikogo nie zastępujesz.")).toBeInTheDocument()
    unmount()
    routes["/api/hr/dashboard/substitution"] = { enabled: false, fresh: false, items: [], warnings: [] }
    renderWith(<HrSubstitutionTile />)
    expect(
      await screen.findByText("Zastępstwa ruszą, gdy NEXUS dostanie dane o urlopach."),
    ).toBeInTheDocument()
  })

  it("ostrzeżenie „zastępca nieobecny” — inne zdanie dla zastępcy i dla przełożonego", async () => {
    const base = {
      owner_user_id: 5,
      owner_name: "Adam Przykładowy",
      substitute_user_id: 7,
      substitute_name: "Ola Testowa",
    }
    expect(warningText({ ...base, you_are_substitute: true })).toBe(
      "Jesteś zastępcą: Adam Przykładowy. Masz dziś nieobecność, więc ta praca czeka bez zastępcy — daj znać przełożonemu.",
    )
    expect(warningText({ ...base, you_are_substitute: false })).toBe(
      "Adam Przykładowy — zastępca (Ola Testowa) też ma dziś nieobecność. Praca czeka bez zastępcy.",
    )
    routes["/api/hr/dashboard/substitution"] = {
      enabled: true,
      fresh: true,
      items: [],
      warnings: [{ ...base, you_are_substitute: false }],
    }
    renderWith(<HrSubstitutionTile />)
    expect(await screen.findByText(/zastępca \(Ola Testowa\) też ma dziś nieobecność/)).toBeInTheDocument()
    expect(screen.queryByText("Dziś nikogo nie zastępujesz.")).toBeNull()
  })
})

describe("„Mój czas”", () => {
  it("najbliższy zatwierdzony urlop, który się jeszcze nie skończył", () => {
    const rows = [
      leaveRow({ id: "past", start_date: "2026-01-05", end_date: "2026-01-09" }),
      leaveRow({ id: "pending", status: "pending", start_date: "2026-10-20", end_date: "2026-10-21" }),
      leaveRow({ id: "later", start_date: "2026-12-23", end_date: "2026-12-31" }),
      leaveRow({ id: "now", start_date: "2026-10-15", end_date: "2026-10-19" }),
    ]
    expect(nearestApprovedLeave(rows, "2026-10-17")?.id).toBe("now")
    expect(nearestApprovedLeave(rows, "2026-10-20")?.id).toBe("later")
    expect(nearestApprovedLeave([], "2026-10-17")).toBeNull()
  })

  it("pula, najbliższy urlop, godziny wobec normy i dwa skróty do „Mojego czasu”", async () => {
    routes["/api/hr/leave/balance"] = { has_pool: true, remaining_days: "11.5", year: 2026 }
    routes["/api/hr/leave/my-requests"] = { items: [leaveRow({})] }
    routes["/api/hr/time/me/"] = {
      totals: { work_hours: 121, norm_hours: 176, days_missing: 2 },
    }
    renderWith(<HrMyTimeTile config={hrConfig()} />)
    expect(await screen.findByText("11,5 dnia")).toBeInTheDocument()
    expect(screen.getByText("23–31.12.2099")).toBeInTheDocument()
    expect(screen.getByText("zatwierdzony")).toBeInTheDocument()
    expect(await screen.findByText("121 / 176 h")).toBeInTheDocument()
    expect(screen.getByText("2 dni do uzupełnienia")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Złóż wniosek" })).toHaveAttribute("href", "/my-time?tab=leave")
    expect(screen.getByRole("link", { name: "Uzupełnij dzień" })).toHaveAttribute("href", "/my-time?tab=month")
  })

  it("awaria salda nie udaje „0 dni” — zdanie z ponowieniem; godziny dalej widać", async () => {
    routes["/api/hr/leave/my-requests"] = { items: [] }
    routes["/api/hr/time/me/"] = { totals: { work_hours: 8, norm_hours: 176, days_missing: 0 } }
    renderWith(<HrMyTimeTile config={hrConfig()} />)
    expect(await screen.findByText("Nie udało się wczytać urlopów.")).toBeInTheDocument()
    expect(screen.queryByText(/0 dni/)).toBeNull()
    expect(await screen.findByText("8 / 176 h")).toBeInTheDocument()
  })

  it("moduł czasu pracy wyłączony — bez godzin i bez „Uzupełnij dzień”", async () => {
    routes["/api/hr/leave/balance"] = { has_pool: false, remaining_days: null, year: 2026 }
    routes["/api/hr/leave/my-requests"] = { items: [] }
    renderWith(<HrMyTimeTile config={hrConfig({ leave: true })} />)
    expect(await screen.findByText("bez puli")).toBeInTheDocument()
    expect(screen.getByText("brak zaplanowanego")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Uzupełnij dzień" })).toBeNull()
  })
})

describe("„Do akceptacji”", () => {
  it("liczba z liczników „Ludzi” — ta sama co zakładka „Akceptacje”", async () => {
    expect(approvalsLabel(1)).toBe("wniosek lub timesheet czeka")
    expect(approvalsLabel(3)).toBe("wnioski lub timesheety czekają")
    expect(approvalsLabel(12)).toBe("wniosków lub timesheetów czeka")
    routes["/api/hr/counts"] = { approvals: 3, cases: null }
    renderWith(<HrApprovalsTile />)
    expect(await screen.findByText("wnioski lub timesheety czekają na Twoją decyzję")).toBeInTheDocument()
    expect(screen.getByText("3")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Ludzie → Akceptacje" })).toHaveAttribute("href", "/people/approvals")
  })

  it("zero tylko po udanym odczycie: spokojne zdanie", async () => {
    routes["/api/hr/counts"] = { approvals: 0, cases: null }
    renderWith(<HrApprovalsTile />)
    expect(await screen.findByText("Nic nie czeka na Twoją decyzję.")).toBeInTheDocument()
  })

  it("awaria liczników to blok błędu, nie „0” ani „nic nie czeka”", async () => {
    renderWith(<HrApprovalsTile />)
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(screen.queryByText("0")).toBeNull()
    expect(screen.queryByText("Nic nie czeka na Twoją decyzję.")).toBeNull()
  })
})

describe("„Sprzęt do zrobienia”", () => {
  const task = (id: number, overdue: number, title: string) => ({
    id,
    kind: "wydanie",
    status: "otwarte",
    title,
    due_on: "2026-10-20",
    overdue_days: overdue,
    holder: { kind: null, id: null, name: null },
    protocol: null,
    details: {},
  })

  it("otwarte zadania, ile po terminie i najbliższe z nazwy", async () => {
    expect(equipmentTaskStats([task(1, 2, "a"), task(2, 0, "b")] as never)).toEqual({ open: 2, overdue: 1 })
    routes["/api/equipment/tasks"] = {
      items: [task(1, 2, "Przygotuj zestaw: Anna Przykładowa"), task(2, 0, "Zwrot: Jan Testowy")],
    }
    renderWith(<EquipmentTasksTile />)
    expect(await screen.findByText("2 otwarte zadania")).toBeInTheDocument()
    expect(screen.getByText("· 1 po terminie")).toBeInTheDocument()
    expect(screen.getByText("Przygotuj zestaw: Anna Przykładowa")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Sprzęt → Do zrobienia" })).toHaveAttribute(
      "href",
      "/equipment?tab=tasks",
    )
  })

  it("awaria listy to blok błędu, nie „nic do zrobienia”", async () => {
    renderWith(<EquipmentTasksTile />)
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(screen.queryByText("Nic do zrobienia przy sprzęcie.")).toBeNull()
  })
})

describe("HrTileGate — kafelek zapisany na pulpicie", () => {
  it("wyłączony moduł: zdanie zamiast zapytań modułu", async () => {
    routes["/api/hr/config"] = hrConfig({})
    renderWith(<HrTileGate type="hr_substitution">{() => <p>treść</p>}</HrTileGate>)
    expect(await screen.findByText(/jest wyłączony/)).toBeInTheDocument()
    expect(screen.queryByText("treść")).toBeNull()
  })

  it("bez kartoteki „Mój czas” mówi „Brak dostępu” z powodem", async () => {
    routes["/api/hr/config"] = hrConfig(undefined, { has_profile: false })
    renderWith(<HrTileGate type="hr_my_time">{() => <p>treść</p>}</HrTileGate>)
    expect(await screen.findByText("Brak dostępu")).toBeInTheDocument()
    expect(screen.getByText("Dla osób z kartoteką pracownika — założą ją Kadry")).toBeInTheDocument()
  })

  it("awaria stanu modułów to blok błędu", async () => {
    renderWith(<HrTileGate type="hr_my_time">{() => <p>treść</p>}</HrTileGate>)
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(screen.queryByText("treść")).toBeNull()
  })

  it("moduł działa: treść kafelka", async () => {
    routes["/api/hr/config"] = hrConfig()
    renderWith(<HrTileGate type="hr_substitution">{() => <p>treść</p>}</HrTileGate>)
    expect(await screen.findByText("treść")).toBeInTheDocument()
  })
})

describe("katalog kafelków a moduły „Ludzi”", () => {
  const sheet = (hr?: HrConfig) =>
    render(
      <TileCatalogSheet
        open
        onOpenChange={() => {}}
        user={{ id: 1, role: "recruiter", roles: ["recruiter"] } as never}
        onPick={() => {}}
        onCustomMetric={() => {}}
        hr={hr}
      />,
    )

  it("moduły włączone: kategoria „Czas i ludzie” i kafelki do dodania", () => {
    sheet(hrConfig(undefined, { is_manager: true }))
    // Ta sama kategoria w kolumnie (komputer) i w chipach (telefon).
    expect(screen.getAllByRole("button", { name: /^Czas i ludzie/ }).length).toBeGreaterThan(0)
    expect(screen.getByRole("button", { name: "Dodaj kafelek W zastępstwie" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Dodaj kafelek Do akceptacji" })).toBeInTheDocument()
  })

  it("moduły wyłączone albo stan nieznany: ani kategorii, ani kafelków", () => {
    const { unmount } = sheet(hrConfig({}))
    expect(screen.queryAllByRole("button", { name: /^Czas i ludzie/ })).toHaveLength(0)
    expect(screen.queryByText("W zastępstwie")).toBeNull()
    unmount()
    sheet(undefined)
    expect(screen.queryByText("Mój czas")).toBeNull()
  })
})
