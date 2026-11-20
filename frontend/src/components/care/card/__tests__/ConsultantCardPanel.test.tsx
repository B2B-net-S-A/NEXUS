/**
 * Karta konsultanta w panelu `/care` (`layout="panel"`) — strażnik przebudowy
 * zakładki „Opieka i rozmowy” kontraktu (wariant A, 20.11.2026). Kontrakt
 * dostał własny układ (`layout="page"`), a panel `/care` ma zostać bez zmian:
 * zdrowie z „dlaczego”, cztery liczby, „Następny krok”, „Co wiemy
 * o projekcie”, sprawy, zwinięty plan, jedna „Historia” z filtrami
 * i „Więcej” z „Otwórz kontrakt”.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showError: vi.fn() }),
}));

if (!Element.prototype.hasPointerCapture) {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => undefined,
    releasePointerCapture: () => undefined,
  });
}

import { ConsultantCard } from "@/components/care/card/ConsultantCard";
import type { ConsultantCardData, ContractTimeline } from "@/lib/api/care";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });
}

const CARD: ConsultantCardData = {
  contract_id: 5,
  candidate_id: 9,
  candidate_name: "Anna Przykładowa",
  client_id: 3,
  client_name: "Firma Testowa",
  role: "Analityczka danych",
  form: "b2b",
  start_on: "2026-10-01",
  end_on: null,
  owner: { user_id: 2, name: "Natalia Opiekunka", source: "delivery_lead" },
  cadence: { level: "biweekly", label: "co 2 tygodnie", until_on: null },
  health: { level: "watch", label: "Uwaga", reasons: ["rozmowa zaległa od 14 dni"] },
  kpis: {
    last_contact: null,
    satisfaction: { value: 3, previous: 5 },
    manager_feedback: { avg: 3.7, extension: "likely", on: "2026-10-12" },
    order_end: { on: "2026-11-20", days: 29 },
  },
  next_step: { kind: "conversation", label: "Zaległa rozmowa", detail: "Dzień 7 · 14 dni po terminie." },
  known_project: null,
  cases: [],
  plan: [{ id: 11, kind: "day_7", label: "Dzień 7", due_on: "2026-10-08", status: "open", skip_reason: null }],
  can_edit: true,
  can_change_owner: true,
  can_see_feedback: true,
};

const TIMELINE: Pick<ContractTimeline, "events" | "feedback_visible" | "can_edit"> = {
  events: [
    { kind: "start", on: "2026-10-01", title: "Start u klienta", detail: null, link: null, future: false },
    { kind: "case_opened", on: "2026-10-06", title: "Sprawa: Dostęp do VPN", detail: null, link: null, future: false },
  ],
  feedback_visible: true,
  can_edit: true,
};

function renderPanel() {
  mocks.get.mockImplementation((url: string) => {
    if (url.endsWith("/card")) return Promise.resolve({ data: CARD });
    if (url.endsWith("/timeline")) return Promise.resolve({ data: TIMELINE });
    if (url === "/api/hr/config") return Promise.reject(httpError(403));
    return Promise.resolve({ data: { items: [] } });
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConsultantCard contractId={5} layout="panel" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
});

describe("ConsultantCard w panelu /care", () => {
  it("nagłówek z imieniem, zdrowiem i „dlaczego”, cztery liczby i „Następny krok”", async () => {
    renderPanel();
    expect(await screen.findByRole("heading", { name: "Anna Przykładowa" })).toBeInTheDocument();
    expect(screen.getByText("Uwaga")).toBeInTheDocument();
    expect(screen.getByText(/Dlaczego „Uwaga”:/).parentElement).toHaveTextContent(
      "Dlaczego „Uwaga”: rozmowa zaległa od 14 dni.",
    );
    const kpis = screen.getByRole("region", { name: "Najważniejsze liczby" });
    expect(within(kpis).getByText("Ostatni kontakt")).toBeInTheDocument();
    expect(within(kpis).getByText("Zadowolenie")).toBeInTheDocument();
    expect(within(kpis).getByText("Opinia menedżera")).toBeInTheDocument();
    expect(within(kpis).getByText("Koniec zamówienia")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Następny krok" })).toHaveTextContent("Zaległa rozmowa");
    expect(screen.getByText(/· opiekun Natalia Opiekunka$/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Zapisz rozmowę" }).length).toBeGreaterThan(0);
  });

  it("plan zwinięty, historia z filtrami, „Więcej” prowadzi do kontraktu", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    renderPanel();
    await screen.findByRole("heading", { name: "Anna Przykładowa" });
    expect(screen.getByRole("button", { name: /Plan kontaktów/ })).toHaveAttribute("aria-expanded", "false");
    const history = await screen.findByRole("list", { name: "Historia konsultanta" });
    expect(within(history).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("group", { name: "Filtr historii" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Więcej akcji" }));
    expect(await screen.findByRole("menuitem", { name: "Otwórz kontrakt" })).toHaveAttribute(
      "href",
      "/contracts/5?tab=care",
    );
    expect(screen.getByRole("menuitem", { name: "Zmień opiekuna" })).toBeInTheDocument();
  });
});
