import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { MyTasksDashboard } from "@/components/v2/dashboard/MyTasksDashboard"
import { calendarApi, notificationsApi } from "@/lib/api"

vi.mock("@/lib/api", () => ({
  calendarApi: { listEvents: vi.fn() },
  notificationsApi: { list: vi.fn() },
}))

const listEvents = vi.mocked(calendarApi.listEvents)
const listNotifications = vi.mocked(notificationsApi.list)

function renderDashboard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MyTasksDashboard />
    </QueryClientProvider>,
  )
}

describe("MyTasksDashboard", () => {
  beforeEach(() => {
    listEvents.mockReset()
    listNotifications.mockReset()
    listEvents.mockResolvedValue({
      data: [
        {
          id: 1,
          title: "Wyślij feedback do klienta",
          description: null,
          event_type: "deadline",
          start_time: "2026-09-02T08:00:00Z",
          end_time: null,
          all_day: false,
          candidate_id: 4,
          candidate_name: "Anna Kandydat",
          job_id: 7,
          job_title: "Java Developer",
          client_id: 2,
          client_name: "Nordic Bank",
          attendees: [],
          location: null,
          teams_link: null,
          online_meeting_url: null,
          recording_url: null,
          created_by: 11,
          reminder_minutes: 15,
          status: "scheduled",
          created_at: null,
        },
        {
          id: 2,
          title: "Interview z klientem",
          description: null,
          event_type: "interview",
          start_time: "2026-09-02T11:00:00Z",
          end_time: "2026-09-02T12:00:00Z",
          all_day: false,
          candidate_id: 5,
          candidate_name: "Jan Kandydat",
          job_id: 8,
          job_title: "Data Engineer",
          client_id: 3,
          client_name: "Data SA",
          attendees: [],
          location: null,
          teams_link: null,
          online_meeting_url: null,
          recording_url: null,
          created_by: 11,
          reminder_minutes: 15,
          status: "scheduled",
          created_at: null,
        },
      ],
    } as Awaited<ReturnType<typeof calendarApi.listEvents>>)
    listNotifications.mockResolvedValue({
      data: {
        items: [
          {
            id: 9,
            user_id: 11,
            title: "Kandydat czeka na decyzję",
            message: "Sprawdź proces Java Developer",
            link: "/jobs/7",
            notification_type: "stage_stuck_7d",
            is_read: false,
            created_at: "2026-09-02T07:00:00Z",
          },
          {
            id: 8,
            user_id: 11,
            title: "Przeczytana informacja",
            message: "Ta pozycja nie wymaga już reakcji",
            link: "/jobs/8",
            notification_type: "stage_changed",
            is_read: true,
            created_at: "2026-09-01T07:00:00Z",
          },
        ],
        unread_count: 1,
      },
    } as Awaited<ReturnType<typeof notificationsApi.list>>)
  })

  it("separates today's deadlines, meetings and notifications", async () => {
    renderDashboard()

    expect(await screen.findByText("Wyślij feedback do klienta")).toBeVisible()
    expect(screen.getByText("Interview z klientem")).toBeVisible()
    expect(screen.getByText("Kandydat czeka na decyzję")).toBeVisible()
    expect(screen.queryByText("Przeczytana informacja")).toBeNull()
    expect(listEvents).toHaveBeenCalledWith(
      expect.objectContaining({
        mine_only: true,
        status: "scheduled",
        limit: 100,
      }),
    )
    expect(listNotifications).toHaveBeenCalledWith(20)
  })

  it("allows the whole personal-work section to be collapsed", async () => {
    const user = userEvent.setup()
    renderDashboard()
    await screen.findByText("Interview z klientem")

    await user.click(screen.getByRole("button", { name: /Moje zadania/ }))

    expect(screen.queryByText("Interview z klientem")).toBeNull()
  })
})
