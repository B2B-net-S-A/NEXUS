import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlacementExclusionsTab } from "./PlacementExclusionsTab";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({ default: { get: mocks.get } }));

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <PlacementExclusionsTab />
    </QueryClientProvider>,
  );
}

describe("PlacementExclusionsTab", () => {
  beforeEach(() => vi.clearAllMocks());

  it("pokazuje kandydata, rekrutację, kto ustawił i powód", async () => {
    mocks.get.mockResolvedValue({
      data: {
        total: 1,
        series_threshold: 10,
        reasons: {},
        items: [
          {
            id: 1,
            candidate_id: 5,
            candidate_name: "Anna Przykładowa",
            job_id: 9,
            job_title: "Java Developer",
            client_id: 3,
            client_name: "Firma Testowa",
            hired_at: "2025-09-24T08:00:00Z",
            moved_by_user_id: 2,
            moved_by_name: "Konto Testowe",
            reason: "admin_bulk_no_cv",
            reason_label: "Seria bez CV",
            had_cv_sent: false,
            series_day: "2025-09-24",
            series_size: 22,
            rule_version: 1,
            detected_at: "2026-09-22T10:00:00Z",
          },
        ],
      },
    });
    renderTab();

    expect(await screen.findByText("Anna Przykładowa")).toBeTruthy();
    expect(screen.getByText("Java Developer")).toBeTruthy();
    expect(screen.getByText("Firma Testowa")).toBeTruthy();
    expect(screen.getByText("Konto Testowe")).toBeTruthy();
    expect(screen.getByText("Seria bez CV")).toBeTruthy();
    expect(screen.getByText(/seria: 22 pary w dniu/)).toBeTruthy();
    expect(screen.getByText("1 wykluczony placement")).toBeTruthy();
  });

  it("403 to „brak uprawnień”, nie pusta lista", async () => {
    mocks.get.mockRejectedValue(
      new AxiosError("forbidden", "ERR_BAD_REQUEST", undefined, undefined, {
        status: 403,
        statusText: "Forbidden",
        data: {},
        headers: {},
        config: { headers: new AxiosHeaders() },
      }),
    );
    renderTab();

    expect(await screen.findByText("Brak uprawnień")).toBeTruthy();
    expect(screen.queryByText("Żaden placement nie jest wykluczony.")).toBeNull();
  });
});
