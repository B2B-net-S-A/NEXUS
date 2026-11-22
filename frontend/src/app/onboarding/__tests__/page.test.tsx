// 22.11.2026: nowa osoba z Poligonem wymaganym po „Zakończ onboarding” lądowała
// na pulpicie. Formularz prowadził już na `/poligon`, ale efekt strony
// (`!requiresOnboarding(user)` → `/`) odpalał po odświeżeniu sesji i wygrywał.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import OnboardingPage from "@/app/onboarding/page"
import api from "@/lib/api"
import { type User, useAuthStore } from "@/store/auth"

const { replaceMock } = vi.hoisted(() => ({ replaceMock: vi.fn() }))

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock }),
}))

vi.mock("@/lib/api", () => {
  const client = { get: vi.fn(), post: vi.fn() }
  return { default: client, api: client }
})

const apiGet = vi.mocked(api.get)
const apiPost = vi.mocked(api.post)

const recruiter = {
  id: 267,
  email: "rekruter@example.com",
  name: "Rekruter",
  role: "recruiter",
  roles: ["recruiter"],
  profile_completed: true,
  profile_completed_at: "2026-11-22T17:00:00Z",
  force_password_change: false,
  force_password_change_at: null,
} as unknown as User

function arrange(redirect: "/poligon" | "/start" | null) {
  apiGet.mockImplementation(async (url) => {
    if (url === "/api/users/me/onboarding/jobs") return { data: { items: [], total: 0 } } as never
    if (url === "/api/auth/me") return { data: recruiter } as never
    if (url === "/api/novelties/start" && redirect)
      return {
        data: { enforced: true, gate_on: true, done: 0, total: 27, items: [], redirect },
      } as never
    throw new Error(`Unexpected GET ${String(url)}`)
  })
  apiPost.mockResolvedValue({ data: {} } as never)
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <OnboardingPage />
    </QueryClientProvider>,
  )
}

async function finishOnboarding() {
  await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/api/users/me/onboarding/jobs"))
  fireEvent.click(screen.getByRole("button", { name: /Zakończ onboarding/ }))
  await waitFor(() => expect(useAuthStore.getState().user?.profile_completed).toBe(true))
  await waitFor(() => expect(replaceMock).toHaveBeenCalled())
}

describe("/onboarding — dokąd po zakończeniu", () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    replaceMock.mockReset()
    window.localStorage.clear()
    act(() => {
      useAuthStore.setState({
        user: { ...recruiter, profile_completed: false, profile_completed_at: null },
        token: "onboarding-token",
        realUser: null,
        hydrated: true,
      })
    })
  })

  afterEach(() => {
    act(() => {
      useAuthStore.setState({ user: null, token: null, realUser: null, hydrated: true })
    })
  })

  it("nowa osoba z Poligonem wymaganym trafia na /poligon, nie na pulpit", async () => {
    arrange("/poligon")
    renderPage()
    await finishOnboarding()
    expect(replaceMock).toHaveBeenLastCalledWith("/poligon")
    expect(replaceMock).not.toHaveBeenCalledWith("/")
  })

  it("przy samym Starcie zostaje pulpit (pulpit jest dla Startu wolny)", async () => {
    arrange("/start")
    renderPage()
    await finishOnboarding()
    expect(replaceMock).toHaveBeenLastCalledWith("/")
  })

  it("awaria stanu Startu niczego nie blokuje — pulpit", async () => {
    arrange(null)
    renderPage()
    await finishOnboarding()
    expect(replaceMock).toHaveBeenLastCalledWith("/")
  })
})
