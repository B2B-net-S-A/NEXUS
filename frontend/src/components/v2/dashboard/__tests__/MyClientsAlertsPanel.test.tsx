import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ToastProvider } from "@/components/Toast"
import {
  cardCta,
  cardMeta,
  cardPill,
  MyClientsAlertsPanel,
} from "@/components/v2/dashboard/MyClientsAlertsPanel"
import type { DlAlertCard } from "@/lib/api/dlAlerts"

vi.mock("@/lib/api/dlAlerts", () => ({
  dlAlertsApi: { cards: vi.fn(), list: vi.fn(), markHandled: vi.fn() },
  dlAlertsExportUrl: (scope: string) => `/api/dl-alerts/export?scope=${scope}`,
}))
vi.mock("@/store/auth", () => ({
  useAuthStore: Object.assign(
    (selector: (s: { user: { role: string } }) => unknown) =>
      selector({ user: { role: "delivery_lead" } }),
    { getState: () => ({ token: "t" }) },
  ),
  hasRole: () => false,
}))

import { dlAlertsApi } from "@/lib/api/dlAlerts"

function card(overrides: Partial<DlAlertCard> = {}): DlAlertCard {
  return {
    id: 1,
    event_key: "periodic_order_ending:order:1:end:2026-10-14:3",
    alert_type: "periodic_order_ending",
    alert_type_label: "Kończące się zamówienie okresowe",
    section: "ending",
    priority: "standard",
    client_id: 12,
    client_name: "Bank Beta",
    order_group_id: null,
    order_id: 1,
    title: "t",
    message: "Zamówienie dla Anita Przykładowa kończy się 2026-10-14.",
    link: "/clients/12?tab=zamowienia&order=1",
    candidate_name: "Anita Przykładowa",
    end_date: "2026-10-14",
    days_left: 23,
    missing_fields: [],
    source: null,
    received_at: null,
    first_alert_at: "2026-09-14T08:00:00Z",
    last_alert_at: "2026-09-14T08:00:00Z",
    repeat_count: 1,
    email_sent: false,
    email_requested: false,
    can_mark_handled: true,
    ...overrides,
  }
}

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MyClientsAlertsPanel refetchIntervalMs={false} />
      </ToastProvider>
    </QueryClientProvider>,
  )
}

const cards = vi.mocked(dlAlertsApi.cards)
const markHandled = vi.mocked(dlAlertsApi.markHandled)

describe("MyClientsAlertsPanel", () => {
  beforeEach(() => {
    cards.mockReset()
    markHandled.mockReset()
  })

  it("groups cards into sections with priority pills and deep-link CTAs", async () => {
    cards.mockResolvedValue({
      data: {
        cards: [
          card({ id: 1, priority: "high", days_left: 7, email_sent: true }),
          card({
            id: 2,
            event_key: "new_contractor_draft:order:4:3",
            alert_type: "new_contractor_draft",
            section: "new_contractor",
            client_name: "Telekom Delta",
            candidate_name: "Jan Próbny",
            message: "Nowy kontraktor Jan Próbny — uzupełnij.",
            link: "/clients/14?tab=zamowienia&order=4",
            source: "b2b_generator",
          }),
          card({
            id: 3,
            event_key: "order_mail_review:order_mail:5:3",
            alert_type: "order_mail_review",
            section: "order_mail",
            client_name: "Słodycze Epsilon",
            link: "/order-mail?doc=5",
          }),
        ],
        total: 3,
      },
    } as Awaited<ReturnType<typeof dlAlertsApi.cards>>)

    renderPanel()

    expect(await screen.findByText("3 do zrobienia")).toBeVisible()
    expect(screen.getByText("Kończące się zamówienia i umowy")).toBeVisible()
    expect(screen.getByText("Nowi kontraktorzy — draft zamówienia")).toBeVisible()
    expect(screen.getByText("Zamówienia z maila do weryfikacji")).toBeVisible()
    expect(screen.queryByText("Decyzje po zakończeniu współpracy")).toBeNull()

    const [urgent] = screen.getAllByTestId("my-clients-card")
    expect(urgent).toHaveAttribute("data-priority", "high")
    expect(within(urgent).getByText("7 dni — pilne")).toBeVisible()
    expect(within(urgent).getByText("Anita Przykładowa").tagName).toBe("STRONG")
    expect(
      within(urgent).getByRole("link", { name: "Przejdź do zamówienia" }),
    ).toHaveAttribute("href", "/clients/12?tab=zamowienia&order=1")
    expect(screen.getByRole("link", { name: "Uzupełnij zamówienie" })).toHaveAttribute(
      "href",
      "/clients/14?tab=zamowienia&order=4",
    )
    expect(screen.getByRole("link", { name: "Przejdź do weryfikacji" })).toHaveAttribute(
      "href",
      "/order-mail?doc=5",
    )
  })

  it("checking a card removes it and closes the case on the server", async () => {
    const user = userEvent.setup()
    cards.mockResolvedValueOnce({
      data: { cards: [card()], total: 1 },
    } as Awaited<ReturnType<typeof dlAlertsApi.cards>>)
    cards.mockResolvedValue({
      data: { cards: [] as DlAlertCard[], total: 0 },
    } as Awaited<ReturnType<typeof dlAlertsApi.cards>>)
    markHandled.mockResolvedValue({ data: {} } as Awaited<
      ReturnType<typeof dlAlertsApi.markHandled>
    >)

    renderPanel()
    await user.click(
      await screen.findByRole("checkbox", { name: /Oznacz jako zrobione: Bank Beta/ }),
    )

    expect(markHandled).toHaveBeenCalledWith(1)
    await waitFor(() => expect(screen.queryByTestId("my-clients-card")).toBeNull())
    expect(await screen.findByText("Brak spraw do zrobienia u Twoich klientów.")).toBeVisible()
  })

  it("brings the card back when marking fails", async () => {
    const user = userEvent.setup()
    cards.mockResolvedValue({
      data: { cards: [card()], total: 1 },
    } as Awaited<ReturnType<typeof dlAlertsApi.cards>>)
    markHandled.mockRejectedValue(new Error("boom"))

    renderPanel()
    await user.click(await screen.findByRole("checkbox", { name: /Bank Beta/ }))

    expect(
      await screen.findByText("Nie udało się oznaczyć sprawy jako zrobionej."),
    ).toBeVisible()
    expect(screen.getAllByTestId("my-clients-card")).toHaveLength(1)
  })

  it("decision cards cannot be checked off from the panel", async () => {
    cards.mockResolvedValue({
      data: {
        cards: [
          card({
            alert_type: "md_consultant_ended",
            section: "decision",
            can_mark_handled: false,
          }),
        ],
        total: 1,
      },
    } as Awaited<ReturnType<typeof dlAlertsApi.cards>>)

    renderPanel()
    expect(
      await screen.findByRole("checkbox", {
        name: "Ta sprawa zamknie się po podjęciu decyzji w zamówieniu",
      }),
    ).toBeDisabled()
    expect(screen.getByRole("link", { name: "Podejmij decyzję" })).toBeVisible()
  })

  it("a failed load is an error, not an empty panel", async () => {
    cards.mockRejectedValue(new Error("down"))
    renderPanel()
    expect(await screen.findByText("Nie udało się wczytać spraw klientów.")).toBeVisible()
    expect(screen.queryByText("Brak spraw do zrobienia u Twoich klientów.")).toBeNull()
    expect(screen.queryByText(/do zrobienia$/)).toBeNull()
  })

  it("labels match the ticket copy", () => {
    expect(cardPill(card({ priority: "high", days_left: 7 }))).toBe("7 dni — pilne")
    expect(cardPill(card({ days_left: 23 }))).toBe("23 dni")
    expect(
      cardPill(card({ alert_type: "candidate_conflict_expired", days_left: null })),
    ).toBe("Wygasł")
    expect(
      cardPill(card({ alert_type: "md_budget_low", days_left: null })),
    ).toBe("Mało MD")
    expect(cardMeta(card({ email_sent: true }))).toBe(
      "Wysłano również mail z przypomnieniem · powtórka za 7 dni, jeśli nieodhaczone",
    )
    expect(cardMeta(card({ email_sent: true, priority: "high" }))).toBe(
      "Wysłano również mail z przypomnieniem · karta zostaje do odhaczenia",
    )
    expect(cardMeta(card())).toBe("Pierwsze przypomnienie · kolejne za 7 dni")
    expect(cardCta(card({ alert_type: "contract_ending" }))).toBe("Przejdź do kontraktu")
    expect(cardCta(card({ alert_type: "candidate_conflict_expired" }))).toBe(
      "Przejdź do kandydata",
    )
  })
})
