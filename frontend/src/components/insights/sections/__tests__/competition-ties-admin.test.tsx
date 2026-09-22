/**
 * „Remis do rozstrzygnięcia" — panel admina w rozdziale Rywalizacja.
 *
 * Pilnuje trzech rzeczy:
 * 1. panel widzi wyłącznie admin i tylko gdy jest remis do decyzji;
 * 2. zapis wymaga DRUGIEGO kroku z podsumowaniem (bez `window.confirm`);
 * 3. wysyłana kolejność to ta ustawiona w oknie.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  role: { current: "admin" as string },
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  },
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (s: { user: { role: string } }) => unknown) =>
    selector({ user: { role: mocks.role.current } }),
}));

import { CompetitionTiesAdmin } from "@/components/insights/sections/CompetitionTiesAdmin";
import { moveItem } from "@/lib/competition-ties-api";

const PENDING = {
  items: [
    {
      competition_type: "monthly_placements",
      period: "2026-10",
      closed_at: "2026-11-04T10:00:00+01:00",
      tie_break_rule: "placements→margin_per_hour_sum→admin",
      ties: [
        {
          positions: [1, 2],
          user_ids: [11, 12],
          reason: "placements_margin_unresolved",
          prizes_pln: { "1": 1500, "2": 0 },
          entries: [
            { user_id: 11, name: "Anna", metric_value: 2, margin_per_hour_sum: 80 },
            { user_id: 12, name: "Bartek", metric_value: 2, margin_per_hour_sum: null },
          ],
        },
      ],
    },
  ],
};

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.role.current = "admin";
});

describe("CompetitionTiesAdmin", () => {
  it("nie renderuje nic poza adminem i nie pyta serwera", () => {
    mocks.role.current = "recruiter";
    const { container } = renderWithClient(<CompetitionTiesAdmin />);
    expect(container).toBeEmptyDOMElement();
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("bez remisów nie renderuje nic", async () => {
    mocks.get.mockResolvedValue({ data: { items: [] } });
    const { container } = renderWithClient(<CompetitionTiesAdmin />);
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("zapis idzie dopiero z drugiego kroku, z kolejnością ustawioną w oknie", async () => {
    mocks.get.mockResolvedValue({ data: PENDING });
    mocks.post.mockResolvedValue({ data: {} });
    renderWithClient(<CompetitionTiesAdmin />);

    fireEvent.click(await screen.findByRole("button", { name: "Rozstrzygnij" }));
    expect(screen.getByText("marża niepoliczalna", { exact: false })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Przesuń Bartek wyżej" }));
    fireEvent.click(screen.getByRole("button", { name: "Dalej" }));
    expect(mocks.post).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Zatwierdź rozstrzygnięcie" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(mocks.post).toHaveBeenCalledWith(
      "/api/competitions/monthly_placements/2026-10/resolve-tie",
      { user_ids: [12, 11] },
    );
  });
});

describe("moveItem", () => {
  it("przesuwa bez mutacji i ignoruje ruch poza listę", () => {
    const list = [1, 2, 3];
    expect(moveItem(list, 2, -1)).toEqual([1, 3, 2]);
    expect(moveItem(list, 0, -1)).toEqual([1, 2, 3]);
    expect(list).toEqual([1, 2, 3]);
  });
});
