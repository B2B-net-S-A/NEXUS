import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewBatchTeamPanel } from "./ReviewBatchTeamPanel";

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ default: api }));

const team = {
  day: "2026-11-09",
  enabled: true,
  minimum: 10,
  good_before_11: 1,
  measured: 2,
  rows: [
    {
      user_id: 1,
      name: "Rekruter A",
      absent: false,
      done_today: 10,
      minimum: 10,
      required: 10,
      pending: 54,
      minimum_at: "09:42",
      screened: 6,
      rejected: 4,
      open_screenings: 2,
      blocked_today: 0,
    },
    {
      user_id: 2,
      name: "Rekruter B",
      absent: false,
      done_today: 3,
      minimum: 40,
      required: 10,
      pending: 118,
      minimum_at: null,
      screened: 3,
      rejected: 0,
      open_screenings: 3,
      blocked_today: 7,
    },
  ],
  streams: {
    weeks: [{ start: "2026-11-02", system: 31, manual: 90, all: 170, complete: true, found_via: { search: 40 } }],
    baseline_week: { system: 31, manual: 93.5, all: 170.5 },
    stop_drop_percent: 10,
    stop_weeks: 2,
    stop: false,
  },
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ReviewBatchTeamPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  api.get.mockReset();
});

describe("ReviewBatchTeamPanel", () => {
  it("nie pyta serwera, dopóki HoR nie rozwinie tabeli", () => {
    renderPanel();
    expect(api.get).not.toHaveBeenCalled();
  });

  it("pokazuje kolumny, podświetla osobę z blokadami i liczy minimum przed 11:00", async () => {
    api.get.mockResolvedValue({ data: team });
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Zobacz zespół dziś" }));
    expect(await screen.findByText("Rekruter B")).toBeInTheDocument();
    expect(screen.getByText("09:42")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Poziom" })).toBeInTheDocument();
    expect(screen.getByText("40")).toBeInTheDocument();
    expect(screen.getByText("6:4")).toBeInTheDocument();
    expect(screen.getByText("Rekruter B").closest("tr")).toHaveClass("bg-warning/10");
    expect(screen.getByText("Rekruter A").closest("tr")).not.toHaveClass("bg-warning/10");
    expect(screen.getByText(/1 z 2 zrobiło minimum przed 11:00/)).toBeInTheDocument();
  });

  it("awaria nie wygląda jak pusta tabela", async () => {
    api.get.mockRejectedValue({ response: { status: 500 } });
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Zobacz zespół dziś" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wczytać porcji zespołu.");
  });
});
