import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { RecruitmentStatsSection } from "@/components/v2/dashboard/RecruitmentStatsSection"
import {
  getRecruitmentStats,
  type DashboardKpi,
  type RecruitmentStatsResponse,
} from "@/lib/dashboard-v2-api"
import { useAuthStore, type User } from "@/store/auth"

vi.mock("@/lib/dashboard-v2-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dashboard-v2-api")>()
  return { ...actual, getRecruitmentStats: vi.fn() }
})

const getStats = vi.mocked(getRecruitmentStats)

const kpi = (value: number | null, quality = "complete"): DashboardKpi => ({
  value,
  unit: "count",
  quality: quality as DashboardKpi["quality"],
  target: null,
  comparison: null,
  definition: "Definicja KPI.",
  drilldown_href: null,
})

function user(role: User["role"], roles?: User["roles"]): User {
  return {
    id: 7,
    email: `${role}@example.com`,
    name: `Test ${role}`,
    role,
    roles: roles ?? [role],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    available_dashboard_presets: ["my-work"],
    default_dashboard_preset: "my-work",
    authorization_version: 1,
    data_scope: {
      kind: "self",
      user_id: 7,
      allowed_client_ids: [],
      allowed_tac_user_ids: [],
      allowed_operator_user_ids: [7],
      allowed_client_tac_pairs: [],
    },
  }
}

function fullResponse(): RecruitmentStatsResponse {
  return {
    schema_version: "2",
    generated_at: "2026-08-07T10:00:00Z",
    scope: {
      kind: "self",
      user_id: 7,
      client_ids: [],
      tac_user_ids: [],
      operator_user_ids: [7],
      client_tac_pairs: [],
    },
    data_quality: {
      status: "complete",
      warnings: [],
      source_watermarks: {},
      sections: {
        team_funnel: { status: "complete", warnings: [], source_watermarks: {} },
      },
    },
    data: {
      period: {
        kind: "month",
        start: "2026-08-01T00:00:00+02:00",
        end: "2026-09-01T00:00:00+02:00",
        timezone: "Europe/Warsaw",
      },
      kpis: {
        verifications: kpi(132),
        recommendations: kpi(97),
        interviews: kpi(41),
        acceptances: kpi(12),
        placements: kpi(7),
      },
      team_table: {
        precision_target_pct: 75,
        rows: [
          {
            user_id: 7,
            name: "Marlena Testowa",
            role: "recruiter",
            verifications: 44,
            recommendations: 31,
            interviews: 12,
            acceptances: 4,
            placements: 3,
            cv_to_base: 58,
            precision_pct: 70.5,
            precision_verified_30d: 44,
            precision_sent_30d: 31,
          },
        ],
        totals: {
          verifications: 132,
          recommendations: 97,
          interviews: 41,
          acceptances: 12,
          placements: 7,
          cv_to_base: 214,
          precision_pct: 73.4,
          people: 14,
        },
      },
      conversions: {
        verified_to_recommendation_pct: 73.5,
        recommendation_to_interview_pct: 42.3,
        interview_to_acceptance_pct: 29.3,
        acceptance_to_placement_pct: 58.3,
        interview_to_placement_pct: 17.1,
        overall_pct: 5.3,
      },
      quarterly_league: null,
      monthly_races: null,
      hall_of_fame: null,
      linkedin: null,
      trend: null,
    },
  }
}

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <RecruitmentStatsSection />
    </QueryClientProvider>,
  )
}

describe("RecruitmentStatsSection", () => {
  beforeEach(() => {
    getStats.mockReset()
  })

  afterEach(() => {
    act(() => {
      useAuthStore.setState({ user: null, hydrated: true })
    })
  })

  it("renders 5 tiles (including Akceptacje) and the named team table for a recruiter", async () => {
    act(() => {
      useAuthStore.setState({ user: user("recruiter"), hydrated: true })
    })
    getStats.mockResolvedValue(fullResponse())

    renderSection()

    // „Akceptacje"/„Weryfikacje"/… występują jako label kafla ORAZ nagłówek
    // kolumny tabeli — stąd *AllByText.
    expect((await screen.findAllByText("Akceptacje")).length).toBeGreaterThan(0)
    expect(screen.getAllByText("Weryfikacje").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Rekomendacje").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Interviews").length).toBeGreaterThan(0)
    expect(screen.getAllByText("Placements").length).toBeGreaterThan(0)
    // Kafle = totals tabeli.
    expect(screen.getAllByText("132").length).toBeGreaterThan(0)
    expect(screen.getAllByText("12").length).toBeGreaterThan(0)
    // Pełna tabela imienna widoczna dla zwykłego rekrutera.
    expect(screen.getByText("Marlena Testowa")).toBeInTheDocument()
    expect(screen.getByText(/Razem \(1\)/)).toBeInTheDocument()
    // Default = miesiąc.
    expect(getStats).toHaveBeenCalledWith("month")
  })

  it("does not mount at all for the legacy viewer role", () => {
    act(() => {
      useAuthStore.setState({ user: user("user"), hydrated: true })
    })

    const { container } = renderSection()

    expect(container).toBeEmptyDOMElement()
    expect(getStats).not.toHaveBeenCalled()
  })

  // Regresja ODWROTNA (zmiana polityki, nie przypadek): finance ma tier
  // operacyjny od 19.08, a backendowy OperationalUser (dashboard_v2.py)
  // odpowiada mu 200. Do tej pory ten plik utrwalał stan sprzed decyzji —
  // front chował dane, do których użytkownik ma prawo. Bramka węższa od API
  // jest gorsza niż jej brak: wygląda jak „nie ma danych".
  it("mounts for finance (tier operacyjny, decyzja 19.08)", async () => {
    act(() => {
      useAuthStore.setState({ user: user("finance"), hydrated: true })
    })
    getStats.mockResolvedValue(fullResponse())

    renderSection()

    expect(await screen.findByText("Marlena Testowa")).toBeInTheDocument()
    expect(getStats).toHaveBeenCalledWith("month")
  })

  it("renders dashes (never zeros) when the funnel source is unavailable", async () => {
    act(() => {
      useAuthStore.setState({ user: user("recruiter"), hydrated: true })
    })
    const degraded = fullResponse()
    degraded.data_quality = {
      status: "partial",
      warnings: ["team_funnel: RuntimeError"],
      source_watermarks: {},
      sections: {
        team_funnel: {
          status: "unavailable",
          warnings: ["team_funnel: RuntimeError"],
          source_watermarks: {},
        },
      },
    }
    degraded.data.kpis = {
      verifications: kpi(null, "unavailable"),
      recommendations: kpi(null, "unavailable"),
      interviews: kpi(null, "unavailable"),
      acceptances: kpi(null, "unavailable"),
      placements: kpi(null, "unavailable"),
    }
    degraded.data.team_table = null
    degraded.data.conversions = null
    getStats.mockResolvedValue(degraded)

    renderSection()

    expect(await screen.findByText("Dane częściowe")).toBeInTheDocument()
    const dashes = screen.getAllByText("—")
    expect(dashes.length).toBeGreaterThanOrEqual(5)
    expect(screen.queryByText("0")).not.toBeInTheDocument()
    expect(
      screen.getByText(/Dane zespołu są chwilowo niedostępne/),
    ).toBeInTheDocument()
  })

  it("shows the error boundary (no zeros) when the request fails", async () => {
    act(() => {
      useAuthStore.setState({ user: user("recruiter"), hydrated: true })
    })
    getStats.mockRejectedValue(new Error("boom"))

    renderSection()

    expect(
      await screen.findByText("Nie udało się załadować danych."),
    ).toBeInTheDocument()
    expect(screen.queryByText("0")).not.toBeInTheDocument()
  })

  it("renders competitions, hall of fame, linkedin and trend from the full payload", async () => {
    act(() => {
      useAuthStore.setState({ user: user("recruiter"), hydrated: true })
    })
    const full = fullResponse()
    const entry = (rank: number, name: string, metric: number) => ({
      rank,
      user_id: rank,
      name,
      metric_value: metric,
      role: "recruiter",
      hit_ratio: null,
      prize_pln: null,
      excluded: false,
      qualified: true,
      placements: 2,
      interviews: 3,
      recommendations: 10,
      verifications: 20,
      precision_pct: 80,
      required_verifications: 40,
      disqualification_reasons: [],
    })
    full.data.quarterly_league = {
      period: "Q3 2026",
      days_remaining: 54,
      points_formula: { placement: 150, interview: 15, recommendation: 5 },
      prizes_pln: { "1": 5000, "2": 3000, "3": 2000 },
      requirement: "Wymagane minimum 3 placementów w kwartale.",
      top3: [entry(1, "Liga Lider", 980)],
      full_ranking: [entry(1, "Liga Lider", 980)],
    }
    full.data.monthly_races = {
      period: "2026-08",
      days_remaining: 24,
      prize_amount_pln: 1500,
      prize_name: "Voucher 1 500 PLN (Modivo, Douglas, Media Markt)",
      recommendations: {
        requirements: ["Wymóg: min. 4 weryfikacji/dzień roboczy"],
        ranking: [entry(1, "Rekomendacyjna Mistrzyni", 28)],
        excluded_user_ids: [],
        qualified_leader_user_id: 1,
      },
      placements: {
        requirements: ["Minimum 2 placementy do kwalifikacji"],
        ranking: [entry(1, "Placementowy Mistrz", 4)],
        excluded_user_ids: [],
        qualified_leader_user_id: 1,
      },
    }
    full.data.hall_of_fame = {
      all_time: [entry(1, "Legenda Wszechczasów", 31)],
      history: [
        {
          period: "Q2 2026",
          top3: [
            {
              rank: 1,
              user_id: 5,
              name: "Zamrożona Zwyciężczyni",
              metric_value: 900,
              points: 900,
              prize_pln: 5000,
            },
          ],
        },
      ],
    }
    full.data.linkedin = {
      date_from: "2026-08-01",
      date_to: "2026-08-31",
      per_user: [
        {
          user_id: 7,
          name: "Linkedinowa Osoba",
          role: "tac",
          cv_added: 40,
          messages_sent: 210,
          responses_received: 18,
          response_rate: 8.6,
          cv_response_rate: 45.0,
          days_reported: 5,
        },
      ],
      totals: {
        cv_added: 320,
        messages_sent: 1400,
        responses_received: 120,
        response_rate: 8.6,
        cv_response_rate: 37.5,
        active_users: 11,
      },
    }
    full.data.trend = {
      months: [
        {
          month: "2026-07",
          verifications: 120,
          recommendations: 84,
          interviews: 30,
          acceptances: 9,
          placements: 5,
        },
        {
          month: "2026-08",
          verifications: 132,
          recommendations: 97,
          interviews: 41,
          acceptances: 12,
          placements: 7,
        },
      ],
    }
    getStats.mockResolvedValue(full)

    renderSection()

    expect(await screen.findByText("Liga Mistrzów")).toBeInTheDocument()
    expect(screen.getByText("Wyścig Rekomendacji")).toBeInTheDocument()
    expect(screen.getByText("Wyścig Placementów")).toBeInTheDocument()
    expect(
      screen.getByText("Hall of Fame — placementy all-time"),
    ).toBeInTheDocument()
    expect(screen.getByText(/Zamrożona Zwyciężczyni/)).toBeInTheDocument()
    expect(screen.getByText("LinkedIn Performance")).toBeInTheDocument()
    expect(screen.getByText("Linkedinowa Osoba")).toBeInTheDocument()
    expect(screen.getByText("Trend 12 miesięcy")).toBeInTheDocument()
    expect(
      screen.getByText("Efektywność lejka (wybrany okres)"),
    ).toBeInTheDocument()
  })

  it("renders unavailable notices (never zeros) when optional blocks are null", async () => {
    act(() => {
      useAuthStore.setState({ user: user("recruiter"), hydrated: true })
    })
    getStats.mockResolvedValue(fullResponse()) // bloki opcjonalne = null

    renderSection()

    await screen.findAllByText("Akceptacje")
    expect(
      screen.getByText(/Liga Mistrzów: dane chwilowo niedostępne/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/LinkedIn: dane chwilowo niedostępne/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Trend: dane chwilowo niedostępne/),
    ).toBeInTheDocument()
  })

  it("refetches with the chosen period when the section toggle changes", async () => {
    act(() => {
      useAuthStore.setState({ user: user("recruiter"), hydrated: true })
    })
    getStats.mockResolvedValue(fullResponse())

    renderSection()
    await screen.findAllByText("Akceptacje")

    fireEvent.click(screen.getByRole("button", { name: "Kwartał" }))
    expect(getStats).toHaveBeenLastCalledWith("quarter")
  })
})
