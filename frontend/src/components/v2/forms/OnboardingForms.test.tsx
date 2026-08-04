import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { OnboardingDLV2 } from "@/components/v2/forms/OnboardingDLV2"
import { OnboardingRecruiterV2 } from "@/components/v2/forms/OnboardingRecruiterV2"
import api from "@/lib/api"
import { type User, useAuthStore } from "@/store/auth"

const { replaceMock, markOnboardingCompletedMock } = vi.hoisted(() => ({
  replaceMock: vi.fn(),
  markOnboardingCompletedMock: vi.fn(),
}))

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    replace: replaceMock,
  }),
}))

vi.mock("@/lib/onboarding-storage", () => ({
  markOnboardingCompleted: markOnboardingCompletedMock,
}))

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)

function fullUser(role: "delivery_lead" | "recruiter"): User {
  const isDeliveryLead = role === "delivery_lead"
  return {
    id: 17,
    email: `${role}@example.com`,
    name: isDeliveryLead ? "Delivery Lead" : "Recruiter",
    role,
    roles: isDeliveryLead ? ["delivery_lead", "tac"] : ["recruiter", "sourcer"],
    profile_completed: true,
    profile_completed_at: "2026-07-31T08:00:00Z",
    force_password_change: false,
    force_password_change_at: null,
    allowed_sections: ["delivery-lead"],
    analytics_capabilities: ["view_client_operations"],
    capabilities: isDeliveryLead
      ? ["view_client_operations", "view_operational_aggregates"]
      : ["view_own_recruitment_kpi"],
    available_dashboard_presets: isDeliveryLead
      ? ["delivery-lead", "my-work"]
      : ["my-work"],
    default_dashboard_preset: isDeliveryLead ? "delivery-lead" : "my-work",
    authorization_version: 9,
    data_scope: isDeliveryLead
      ? {
          kind: "delivery_clients",
          user_id: 17,
          allowed_client_ids: [10],
          allowed_tac_user_ids: [17, 21],
          allowed_operator_user_ids: [17, 21],
          allowed_client_tac_pairs: [
            { client_id: 10, tac_user_id: 21 },
          ],
        }
      : {
          kind: "self",
          user_id: 17,
          allowed_client_ids: [],
          allowed_tac_user_ids: [17],
          allowed_operator_user_ids: [17],
          allowed_client_tac_pairs: [],
        },
  }
}

function renderForm(node: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>{node}</QueryClientProvider>,
  )
}

function arrangeApi(refreshedUser: User) {
  apiGet.mockImplementation(async (url) => {
    if (url === "/api/users/me/onboarding/jobs") {
      return { data: { items: [], total: 0 } } as never
    }
    if (url === "/api/auth/me") {
      return { data: refreshedUser } as never
    }
    throw new Error(`Unexpected GET ${String(url)}`)
  })
  apiPost.mockResolvedValue({ data: { user: refreshedUser } } as never)
}

function seedIncompleteSession(user: User) {
  act(() => {
    useAuthStore.setState({
      user: {
        ...user,
        profile_completed: false,
        profile_completed_at: null,
      },
      token: "onboarding-token",
      realUser: null,
      hydrated: true,
    })
  })
}

describe("role onboarding forms", () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    replaceMock.mockReset()
    markOnboardingCompletedMock.mockReset()
    window.localStorage.clear()
  })

  afterEach(() => {
    act(() => {
      useAuthStore.setState({
        user: null,
        token: null,
        realUser: null,
        hydrated: true,
      })
    })
  })

  it("uses the scoped endpoint and preserves the complete DL auth contract", async () => {
    const refreshedUser = fullUser("delivery_lead")
    arrangeApi(refreshedUser)
    seedIncompleteSession(refreshedUser)

    renderForm(<OnboardingDLV2 />)

    await waitFor(() =>
      expect(apiGet).toHaveBeenCalledWith("/api/users/me/onboarding/jobs"),
    )
    expect(apiGet).not.toHaveBeenCalledWith(
      "/api/jobs",
      expect.anything(),
    )

    fireEvent.click(screen.getByRole("button", { name: /Dalej/ }))
    fireEvent.click(screen.getByRole("button", { name: /Zakończ/ }))

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("/api/users/me/onboarding", {
        priority_job_ids: [],
        needs_sourcing_job_ids: [],
      }),
    )
    await waitFor(() =>
      expect(apiGet).toHaveBeenCalledWith("/api/auth/me"),
    )
    expect(useAuthStore.getState().user).toEqual(refreshedUser)
    expect(useAuthStore.getState().user?.roles).toEqual([
      "delivery_lead",
      "tac",
    ])
    expect(useAuthStore.getState().user?.available_dashboard_presets).toEqual([
      "delivery-lead",
      "my-work",
    ])
    expect(useAuthStore.getState().user?.authorization_version).toBe(9)
    expect(markOnboardingCompletedMock).toHaveBeenCalledOnce()
    expect(replaceMock).toHaveBeenCalledWith("/")
  })

  it("uses the scoped endpoint and refreshes the recruiter session from auth/me", async () => {
    const refreshedUser = fullUser("recruiter")
    arrangeApi(refreshedUser)
    seedIncompleteSession(refreshedUser)

    renderForm(<OnboardingRecruiterV2 />)

    await waitFor(() =>
      expect(apiGet).toHaveBeenCalledWith("/api/users/me/onboarding/jobs"),
    )
    fireEvent.click(
      screen.getByRole("button", { name: /Zakończ onboarding/ }),
    )

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("/api/users/me/onboarding", {
        active_job_ids: [],
      }),
    )
    await waitFor(() =>
      expect(apiGet).toHaveBeenCalledWith("/api/auth/me"),
    )
    expect(useAuthStore.getState().user).toEqual(refreshedUser)
    expect(useAuthStore.getState().user?.capabilities).toEqual([
      "view_own_recruitment_kpi",
    ])
    expect(useAuthStore.getState().user?.data_scope?.kind).toBe("self")
    expect(markOnboardingCompletedMock).toHaveBeenCalledOnce()
    expect(replaceMock).toHaveBeenCalledWith("/")
  })
})
