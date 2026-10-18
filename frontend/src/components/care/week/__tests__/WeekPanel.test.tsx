/**
 * „Opieka · Ten tydzień”: awaria odczytu nie wygląda jak pusta kolejka,
 * pusty tydzień ma swój stan, a wiersz ma powód i menedżera z drzewa.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), showToast: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.showToast, showError: vi.fn() }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/care",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { WeekPanel } from "@/components/care/week/WeekPanel";
import type { CareWeek } from "@/lib/api/care";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });
}

function week(overrides: Partial<CareWeek> = {}): CareWeek {
  return {
    week: { from: "2026-10-19", to: "2026-10-23", today: "2026-10-20", is_current: true },
    scope: "mine",
    contacts: [],
    feedback: [],
    feedback_visible: true,
    counts: { contacts: 0, overdue: 0, feedback: 0, front_office: 0 },
    can_edit: true,
    can_write_feedback: true,
    ...overrides,
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <WeekPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  window.history.replaceState({}, "", "/care");
});

describe("WeekPanel", () => {
  it("awaria odczytu to komunikat z ponowieniem, nie pusty tydzień", async () => {
    mocks.get.mockRejectedValue(httpError(500));
    renderPanel();
    expect(
      await screen.findByText("Nie udało się wczytać kolejki na ten tydzień."),
    ).toBeInTheDocument();
    expect(screen.queryByText("W tym tygodniu nie ma zaplanowanych kontaktów")).toBeNull();
  });

  it("pusty tydzień (sukces) ma własny stan i liczby", async () => {
    mocks.get.mockResolvedValue({ data: week() });
    renderPanel();
    expect(
      await screen.findByText("W tym tygodniu nie ma zaplanowanych kontaktów"),
    ).toBeInTheDocument();
    expect(screen.getByText("Ten tydzień · 19–23.10")).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/api/care/week", { params: { scope: "mine" } });
  });

  it("wiersz: powód zaległy, menedżer z drzewa i sygnał do front office; Finanse bez opinii", async () => {
    mocks.get.mockResolvedValue({
      data: week({
        feedback_visible: false,
        can_edit: false,
        contacts: [
          {
            contract_id: 4,
            candidate_id: 9,
            candidate_name: "Ewa Przykładowa",
            client_id: 3,
            client_name: "Firma Testowa",
            job_title: "Analityczka",
            start_date: "2026-09-10",
            end_date: "2026-11-20",
            owner: { id: 2, name: "Natalia Opiekunka" },
            reasons: [
              {
                kind: "day_30",
                label: "Dzień 30",
                due_on: "2026-10-17",
                overdue: true,
                plan_item_id: 11,
                from_conversation_on: null,
              },
            ],
            due_on: "2026-10-17",
            overdue: true,
            overdue_days: 3,
            plan_item_id: 11,
            manager: {
              id: 5,
              name: "Piotr Wzorcowy",
              position: "Kierownik",
              area: { id: 1, name: "Data" },
            },
            last_conversation: null,
            signals: [],
            front_office: { reasons: ["project_end"], handed_off_on: null },
          },
        ],
        counts: { contacts: 1, overdue: 1, feedback: 0, front_office: 1 },
      }),
    });
    renderPanel();
    expect(await screen.findByText("zaległy 3 dni · dzień 30")).toBeInTheDocument();
    expect(screen.getByText("Firma Testowa · Data · menedżer: Piotr Wzorcowy")).toBeInTheDocument();
    expect(screen.getByText("do front office: kończy projekt")).toBeInTheDocument();
    expect(screen.getByText("bez rozmów")).toBeInTheDocument();
    // Bez prawa zapisu nie ma „Zapisz rozmowę”; bez D11 nie ma liczby opinii.
    expect(screen.queryByRole("button", { name: "Zapisz rozmowę" })).toBeNull();
    expect(screen.queryByText("opinie od menedżerów")).toBeNull();
  });
});
