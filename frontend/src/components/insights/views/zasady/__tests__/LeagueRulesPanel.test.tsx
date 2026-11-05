import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LeagueRulesPanel } from "../LeagueRulesPanel";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  patch: vi.fn(),
  askConfirm: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, patch: mocks.patch } }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.askConfirm, confirmDialog: null }),
}));

const field = (key: string, group: string, label: string, value: number) => ({
  key,
  value,
  default: value,
  min: 0,
  max: 1000,
  group,
  label,
  unit: "pkt",
  is_default: true,
});

const CONFIG = {
  fields: [
    field("league_points_placement", "league_points", "Punkty za placement", 150),
    field("seniority_senior_placements", "seniority", "Ścieżka rozwoju — placementy na Seniora", 6),
  ],
  notes: {
    league_no_retroactivity: "Od najbliższego kwartału.",
    seniority_retroactive: "Działa wstecz.",
  },
};

const renderPanel = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <LeagueRulesPanel />
    </QueryClientProvider>,
  );

describe("LeagueRulesPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue({ data: CONFIG });
    mocks.patch.mockResolvedValue({ data: {} });
    mocks.askConfirm.mockResolvedValue(true);
  });

  it("wysyła tylko zmienione pola", async () => {
    const user = userEvent.setup();
    renderPanel();
    const input = await screen.findByLabelText(/Punkty za placement/);
    await user.clear(input);
    await user.type(input, "200");
    await user.click(screen.getByRole("button", { name: "Zapisz punktację" }));
    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/insights/scoring-config", {
        values: { league_points_placement: 200 },
      }),
    );
  });

  it("przy zmianie progu Ścieżki ostrzega, że działa wstecz", async () => {
    const user = userEvent.setup();
    renderPanel();
    const input = await screen.findByLabelText(/Placementy na Seniora/);
    await user.clear(input);
    await user.type(input, "7");
    await user.click(screen.getByRole("button", { name: "Zapisz punktację" }));
    await waitFor(() =>
      expect(mocks.askConfirm).toHaveBeenCalledWith(
        expect.objectContaining({ description: "Działa wstecz." }),
      ),
    );
  });

  it("bez potwierdzenia niczego nie zapisuje", async () => {
    mocks.askConfirm.mockResolvedValue(false);
    const user = userEvent.setup();
    renderPanel();
    const input = await screen.findByLabelText(/Punkty za placement/);
    await user.clear(input);
    await user.type(input, "200");
    await user.click(screen.getByRole("button", { name: "Zapisz punktację" }));
    await waitFor(() => expect(mocks.askConfirm).toHaveBeenCalled());
    expect(mocks.patch).not.toHaveBeenCalled();
  });

  it("przycisk zapisu jest nieaktywny bez zmian", async () => {
    renderPanel();
    await screen.findByLabelText(/Punkty za placement/);
    expect(screen.getByRole("button", { name: "Zapisz punktację" })).toBeDisabled();
  });

  it("awaria odczytu nie wygląda jak pusty formularz", async () => {
    mocks.get.mockRejectedValue(new Error("boom"));
    renderPanel();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Zapisz punktację" })).toBeNull());
    await screen.findByRole("button", { name: /Spróbuj|Ponów/ });
  });

  it("odrzucenie zapisu pokazuje komunikat", async () => {
    mocks.patch.mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    renderPanel();
    const input = await screen.findByLabelText(/Punkty za placement/);
    await user.clear(input);
    await user.type(input, "200");
    await user.click(screen.getByRole("button", { name: "Zapisz punktację" }));
    await screen.findByRole("alert");
  });
});

describe("LeagueRulesPanel: wartości spoza zakresu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue({ data: CONFIG });
    mocks.patch.mockResolvedValue({ data: {} });
    mocks.askConfirm.mockResolvedValue(true);
  });

  it("puste pole nie zapisuje się jako 0", async () => {
    const user = userEvent.setup();
    renderPanel();
    const input = await screen.findByLabelText(/Punkty za placement/);
    await user.clear(input);
    expect(screen.getByRole("button", { name: "Zapisz punktację" })).toBeDisabled();
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Punkty za placement");
    expect(mocks.patch).not.toHaveBeenCalled();
  });

  it("wartość powyżej zakresu blokuje zapis", async () => {
    const user = userEvent.setup();
    renderPanel();
    const input = await screen.findByLabelText(/Punkty za placement/);
    await user.clear(input);
    await user.type(input, "1001");
    expect(screen.getByRole("button", { name: "Zapisz punktację" })).toBeDisabled();
  });
});
