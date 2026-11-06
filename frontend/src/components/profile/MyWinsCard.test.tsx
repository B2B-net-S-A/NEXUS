import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MyWinsCard, winPeriodLabel, winPrizeLabel } from "./MyWinsCard";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ default: { get: mocks.get } }));

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MyWinsCard />
    </QueryClientProvider>,
  );
}

function axiosError(status: number) {
  return new AxiosError("err", "ERR_BAD_REQUEST", undefined, undefined, {
    status,
    statusText: "",
    data: {},
    headers: {},
    config: { headers: new AxiosHeaders() },
  });
}

describe("MyWinsCard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("pokazuje miejsce, rywalizację, okres i kwotę", async () => {
    mocks.get.mockResolvedValue({
      data: {
        items: [
          { competition_type: "quarterly_champions_recruiter", label: "Liga Mistrzów rekruterów", period: "Q4 2026", rank: 2, metric_value: 900, prize_pln: 6000 },
          { competition_type: "monthly_placements", label: "Wyścig placementów", period: "2026-10", rank: 1, metric_value: 4, prize_pln: 3000 },
        ],
      },
    });
    renderCard();

    expect(await screen.findByText("1. miejsce · Wyścig placementów")).toBeTruthy();
    expect(screen.getByText("październik 2026")).toBeTruthy();
    expect(screen.getByText(/^3\s000 zł$/)).toBeTruthy();
    expect(screen.getByText("2. miejsce · Liga Mistrzów rekruterów")).toBeTruthy();
    expect(screen.getByText("Q4 2026")).toBeTruthy();
  });

  it("pusta lista mówi to wprost dopiero po udanym zapytaniu", async () => {
    mocks.get.mockResolvedValue({ data: { items: [] } });
    renderCard();
    expect(await screen.findByText(/Jeszcze bez miejsca na podium/)).toBeTruthy();
  });

  it("awaria to komunikat, nie pusta lista", async () => {
    mocks.get.mockRejectedValue(axiosError(500));
    renderCard();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText(/Jeszcze bez miejsca/)).toBeNull();
  });

  it("bez dostępu (403) karty nie ma", async () => {
    mocks.get.mockRejectedValue(axiosError(403));
    const { container } = renderCard();
    await vi.waitFor(() => expect(mocks.get).toHaveBeenCalled());
    await vi.waitFor(() => expect(container.querySelector("section")).toBeNull());
  });
});

describe("formatowanie", () => {
  it("okres i kwota", () => {
    expect(winPeriodLabel("2026-11")).toBe("listopad 2026");
    expect(winPeriodLabel("Q4 2026")).toBe("Q4 2026");
    expect(winPrizeLabel(10000)).toBe("10 000 zł");
    expect(winPrizeLabel(0)).toBeNull();
  });
});
