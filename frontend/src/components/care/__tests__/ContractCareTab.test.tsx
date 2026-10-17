/**
 * Zakładka „Opieka” kontraktu: awaria odczytu nie wygląda jak brak rozmów,
 * czytelnik bez prawa zapisu nie widzi przycisków, plan pokazuje zaległość.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  showToast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    put: vi.fn(),
    patch: (...a: unknown[]) => mocks.patch(...a),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.showToast, showError: vi.fn() }),
}));

// Lista wyboru Radix w jsdom: brak API przechwytywania wskaźnika.
if (!Element.prototype.hasPointerCapture) {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => undefined,
    releasePointerCapture: () => undefined,
  });
}

import { ContractCareTab } from "@/components/care/ContractCareTab";
import type { ContractCare } from "@/lib/api/care";

function httpError(status: number, detail?: string) {
  return Object.assign(new Error(`HTTP ${status}`), {
    response: { status, data: detail ? { detail } : {} },
  });
}

function care(overrides: Partial<ContractCare> = {}): ContractCare {
  return {
    contract: {
      id: 5,
      label: "Anna Przykładowa · Firma Testowa",
      candidate_id: 9,
      candidate_name: "Anna Przykładowa",
      client_id: 3,
      client_name: "Firma Testowa",
      job_id: null,
      job_title: null,
      status: "active",
      is_live: true,
      start_date: "2026-10-01",
      end_date: null,
      day_of_cooperation: 16,
    },
    owner: { user: { id: 2, name: "Natalia Opiekunka" }, source: "delivery_lead", explicit: false },
    client_default_owner: null,
    plan: [
      {
        id: 11,
        kind: "day_7",
        label: "Dzień 7",
        due_on: "2026-10-08",
        status: "open",
        overdue: true,
        done_conversation_id: null,
        resolved_at: null,
      },
    ],
    next_contact: { due_on: "2026-10-08", label: "Dzień 7", overdue: true, plan_item_id: 11 },
    last_satisfaction: null,
    conversations: [],
    tech_cards: [],
    redeploy: [],
    project_end: null,
    can_edit: true,
    ...overrides,
  };
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContractCareTab contractId={5} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.patch.mockReset();
});

describe("ContractCareTab", () => {
  it("awaria serwera to komunikat z ponowieniem, nie pusta oś", async () => {
    mocks.get.mockRejectedValue(httpError(500));
    renderTab();
    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText(/Nie ma jeszcze rozmów/)).not.toBeInTheDocument();
  });

  it("wyłączony moduł mówi to wprost", async () => {
    mocks.get.mockRejectedValue(httpError(404, "Ten moduł nie jest jeszcze włączony."));
    renderTab();
    expect(await screen.findByText("Ten moduł nie jest jeszcze włączony.")).toBeInTheDocument();
  });

  it("pokazuje opiekuna i zaległy punkt planu; czytelnik nie ma przycisków zapisu", async () => {
    mocks.get.mockResolvedValue({ data: care({ can_edit: false }) });
    renderTab();
    expect(await screen.findByText("Natalia Opiekunka")).toBeInTheDocument();
    expect(screen.getByText("po terminie")).toBeInTheDocument();
    expect(screen.getByText(/Nie ma jeszcze rozmów/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz rozmowę" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz" })).not.toBeInTheDocument();
  });

  it("„Zapisz” przy punkcie planu wysyła rozmowę zamykającą ten punkt", async () => {
    mocks.get.mockImplementation((url: string) =>
      Promise.resolve({ data: url.includes("/owners") ? { items: [] } : care() }),
    );
    mocks.post.mockResolvedValue({ data: care({ plan: [] }) });
    renderTab();
    fireEvent.click(await screen.findByRole("button", { name: "Zapisz" }));
    expect(await screen.findByText(/Zamyka punkt planu: Dzień 7/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz rozmowę" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    const [url, body] = mocks.post.mock.calls[0] as [string, Record<string, unknown>];
    expect(url).toBe("/api/care/contracts/5/conversations");
    expect(body.plan_item_id).toBe(11);
    expect(body.channel).toBe("phone");
  });

  it("„Pomiń” wymaga powodu z listy i wysyła go z notatką", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    mocks.get.mockImplementation((url: string) =>
      Promise.resolve({ data: url.includes("/owners") ? { items: [] } : care() }),
    );
    mocks.patch.mockResolvedValue({ data: care({ plan: [] }) });
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Pomiń" }));
    const dialog = await screen.findByRole("dialog", { name: "Pomiń kontakt" });
    await user.click(within(dialog).getByRole("button", { name: "Pomiń" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Wybierz powód pominięcia.");
    expect(mocks.patch).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("combobox", { name: /Powód/ }));
    await user.click(await screen.findByRole("option", { name: "Nieobecność konsultanta" }));
    await user.type(within(dialog).getByLabelText(/Notatka/), "Wraca za tydzień.");
    await user.click(within(dialog).getByRole("button", { name: "Pomiń" }));
    await waitFor(() => expect(mocks.patch).toHaveBeenCalled());
    expect(mocks.patch.mock.calls[0]).toEqual([
      "/api/care/plan-items/11",
      { status: "skipped", reason: "absence", note: "Wraca za tydzień." },
    ]);
  });

  it("pokazuje rytm kontaktu z podpisem i powód pominiętego punktu", async () => {
    mocks.get.mockResolvedValue({
      data: care({
        can_edit: false,
        cadence: {
          level: "biweekly",
          source: "period",
          starts_on: "2026-10-10",
          until_on: "2026-11-30",
          returns_to: "monthly",
          reason: "wants_change",
          note: null,
          author: { id: 2, name: "Natalia Opiekunka" },
          can_edit: false,
        },
        plan: [
          {
            id: 12,
            kind: "cadence",
            label: "Rozmowa według rytmu",
            due_on: "2026-10-15",
            status: "skipped",
            overdue: false,
            done_conversation_id: null,
            resolved_at: "2026-10-15T09:00:00Z",
            skip_reason: "unreachable",
            skip_note: null,
          },
        ],
      }),
    });
    renderTab();
    expect(await screen.findByText("co 2 tygodnie")).toBeInTheDocument();
    expect(screen.getByText("do 30.11 · chce zmiany projektu")).toBeInTheDocument();
    expect(screen.getByText(/pominięty · konsultant nieosiągalny/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zmień" })).not.toBeInTheDocument();
  });
});
