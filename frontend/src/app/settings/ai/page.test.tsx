import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AISettingsPage from "./page";

/**
 * Panel Ustawienia → AI nie miał żadnego testu FE, a to JEDYNA powierzchnia
 * z miesięcznymi limitami i głównym kill-switchem. C13 dokłada tu model per
 * funkcja (z rejestru backendu) i tokeny — oraz tekst P-A o niezależności
 * wyszukiwania semantycznego. Test pokrywa render, oba te pola, przełącznik
 * funkcji i edycję limitu.
 */

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  setMaster: vi.fn(),
  updateFeature: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  aiSettingsApi: {
    get: mocks.get,
    setMaster: mocks.setMaster,
    updateFeature: mocks.updateFeature,
  },
}));

const RESPONSE = {
  master_enabled: true,
  features: [
    {
      feature: "cv_generator",
      enabled: true,
      monthly_limit: 0,
      model: "claude-sonnet-4-6",
      label: "Generator CV B2B",
      data_sent_to_ai: ["Treść CV"],
    },
    {
      feature: "cv_parser",
      enabled: true,
      monthly_limit: 100,
      model: "claude-sonnet-5",
      label: "Tworzenie kandydata z CV",
      data_sent_to_ai: ["Treść CV"],
    },
  ],
  usage: [
    {
      feature: "cv_generator",
      used: 12,
      input_tokens: 34_000,
      output_tokens: 8_000,
      limit: 0,
      period_start: "2026-09-01",
      period_end: "2026-09-30",
    },
    {
      feature: "cv_parser",
      used: 3,
      input_tokens: 0,
      output_tokens: 0,
      limit: 100,
      period_start: "2026-09-01",
      period_end: "2026-09-30",
    },
  ],
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AISettingsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockResolvedValue({ data: RESPONSE });
  mocks.setMaster.mockResolvedValue({ data: RESPONSE });
  mocks.updateFeature.mockResolvedValue({ data: RESPONSE });
});

describe("Panel Ustawienia → AI", () => {
  it("pokazuje tekst o niezależności wyszukiwania semantycznego (P-A)", async () => {
    renderPage();
    await screen.findByText("Generator CV B2B");
    expect(screen.getByText(/Funkcje generatywne AI/)).toBeInTheDocument();
    expect(screen.getByText(/NIEZALEŻNIE/)).toBeInTheDocument();
  });

  it("renderuje model funkcji z rejestru backendu", async () => {
    renderPage();
    await screen.findByText("Generator CV B2B");
    const models = screen.getAllByTestId("feature-model").map((el) => el.textContent);
    expect(models).toContain("claude-sonnet-4-6");
    expect(models).toContain("claude-sonnet-5");
  });

  it("pokazuje tokeny tylko gdy niezerowe", async () => {
    renderPage();
    await screen.findByText("Generator CV B2B");
    const tokenLines = screen.getAllByTestId("feature-tokens");
    // Tylko cv_generator ma niezerowe tokeny; cv_parser (0/0) nie renderuje linii.
    expect(tokenLines).toHaveLength(1);
    expect(tokenLines[0].textContent).toMatch(/34\D?000/);
  });

  it("przełącznik funkcji woła updateFeature z enabled", async () => {
    renderPage();
    await screen.findByText("Generator CV B2B");
    const switches = screen.getAllByRole("switch");
    // switches[0] = master; switches[1] = pierwsza funkcja
    fireEvent.click(switches[1]);
    await waitFor(() =>
      expect(mocks.updateFeature).toHaveBeenCalledWith("cv_generator", {
        enabled: false,
      }),
    );
  });

  it("edycja limitu woła updateFeature z monthly_limit", async () => {
    renderPage();
    await screen.findByText("Tworzenie kandydata z CV");
    // cv_parser ma limit 100 → przycisk pokazuje sformatowaną liczbę
    fireEvent.click(screen.getByRole("button", { name: "100" }));
    const input = await screen.findByDisplayValue("100");
    fireEvent.change(input, { target: { value: "250" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(mocks.updateFeature).toHaveBeenCalledWith("cv_parser", {
        monthly_limit: 250,
      }),
    );
  });
});
