import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { useAuthStore, type User } from "@/store/auth"

import { MyRecruitmentsTile, myRoleInJob } from "../MyRecruitmentsTile"

const getMock = vi.fn()

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  const api = { get: (...args: unknown[]) => getMock(...args) }
  return { ...actual, api, default: api }
})

function renderTile() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MyRecruitmentsTile />
    </QueryClientProvider>,
  )
}

function userWith(roles: string[]) {
  return { id: 7, email: "x@example.com", name: "X", role: roles[0], roles, is_active: true } as unknown as User
}

const rows = [
  {
    id: 1,
    title: "Java Developer",
    working_title: null,
    client_name: "Bank A",
    deadline: null,
    delivery_lead_id: 7,
    recruiters: [{ user_id: 7, name: "Ja Sam", via: "owner", proposed: false, assigned_by_name: null }],
    stage_breakdown: { new: 2, hired: 1 },
  },
  {
    id: 2,
    title: "Tester",
    working_title: null,
    client_name: "Bank B",
    deadline: null,
    delivery_lead_id: 7,
    recruiters: [{ user_id: 9, name: "Marta Kowalska", via: "owner", proposed: false, assigned_by_name: null }],
    stage_breakdown: {},
  },
]

beforeEach(() => {
  getMock.mockReset()
  useAuthStore.setState({ user: userWith(["recruiter"]), hydrated: true })
})

describe("myRoleInJob", () => {
  it("DL, Rekruter, oba", () => {
    expect(myRoleInJob(rows[0] as never, 7)).toBe("DL + Rekruter")
    expect(myRoleInJob(rows[1] as never, 7)).toBe("DL")
    expect(myRoleInJob(rows[1] as never, 9)).toBe("Rekruter")
    expect(myRoleInJob(rows[1] as never, 1)).toBeNull()
  })
})

describe("MyRecruitmentsTile", () => {
  it("pusty stan", async () => {
    getMock.mockResolvedValue({ data: { items: [], total: 0 } })
    renderTile()
    expect(await screen.findByText("Nie masz otwartych rekrutacji.")).toBeInTheDocument()
    expect(getMock).toHaveBeenCalledWith("/api/jobs", {
      params: expect.objectContaining({ mine: true, open_only: true, include_stage_counts: true }),
    })
  })

  it("błąd to komunikat z ponowieniem", async () => {
    getMock.mockRejectedValue(new Error("boom"))
    renderTile()
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument()
  })

  it("rekruter: bez kolumn Rekruter i Twoja rola", async () => {
    getMock.mockResolvedValue({ data: { items: rows, total: 2 } })
    renderTile()
    expect(await screen.findByRole("link", { name: "Java Developer" })).toHaveAttribute("href", "/jobs/1")
    expect(screen.getAllByTestId("job-stage-counts")).toHaveLength(2)
    expect(screen.queryByRole("columnheader", { name: "Twoja rola" })).toBeNull()
    expect(screen.queryByRole("columnheader", { name: "Rekruter" })).toBeNull()
  })

  it("DL + rekruter: kolumna „Twoja rola”", async () => {
    useAuthStore.setState({ user: userWith(["delivery_lead", "recruiter"]), hydrated: true })
    getMock.mockResolvedValue({ data: { items: rows, total: 2 } })
    renderTile()
    expect(await screen.findByRole("columnheader", { name: "Twoja rola" })).toBeInTheDocument()
    expect(screen.getByText("DL + Rekruter")).toBeInTheDocument()
    expect(screen.getByText("Marta K.")).toBeInTheDocument()
  })

  it("sam DL: kolumna Rekruter bez „Twojej roli”", async () => {
    useAuthStore.setState({ user: userWith(["delivery_lead"]), hydrated: true })
    getMock.mockResolvedValue({ data: { items: rows, total: 2 } })
    renderTile()
    expect(await screen.findByRole("columnheader", { name: "Rekruter" })).toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "Twoja rola" })).toBeNull()
  })
})
