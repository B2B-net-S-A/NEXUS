import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), success: vi.fn(), error: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post } }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.success, showError: mocks.error }),
}));

import { KtoZnaNexus } from "../KtoZnaNexus";

const MATRIX = {
  window_days: 60,
  features: [
    { key: "biore", label: "„Biorę”", group: "Rdzeń procesu", users: 2 },
    { key: "czat", label: "Czat rekrutacji", group: "Zespół i AI", users: 0 },
  ],
  people: [
    { id: 1, name: "Anna  Poligonowa", used: ["biore"], gaps: 1, poligon: null },
    { id: 2, name: "Jakub Szkoleniowy", used: ["biore"], gaps: 1, poligon: null },
  ],
  campaign: null,
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <KtoZnaNexus />
    </QueryClientProvider>,
  );
}

describe("KtoZnaNexus", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.post.mockReset();
    mocks.success.mockReset();
    mocks.error.mockReset();
  });

  it("pokazuje osoby, użycie funkcji i luki", async () => {
    mocks.get.mockResolvedValue({ data: MATRIX });
    renderPanel();
    expect(await screen.findByText("Anna P.")).toBeTruthy();
    expect(screen.getAllByLabelText("Czat rekrutacji: nie używa")).toHaveLength(2);
    expect(screen.getByText(/Najsłabiej: Czat rekrutacji \(0\)/)).toBeTruthy();
  });

  it("awaria zapytania to komunikat, nie pusta tabela", async () => {
    mocks.get.mockRejectedValue(
      Object.assign(new Error("x"), { isAxiosError: true, response: { status: 500, data: { detail: "Serwer leży" } } }),
    );
    renderPanel();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("Anna P.")).toBeNull();
  });

  it("wysyła poligon z lukami dopiero po potwierdzeniu", async () => {
    mocks.get.mockResolvedValue({ data: MATRIX });
    mocks.post.mockResolvedValue({ data: { due: "2026-11-23", people: 2, credited: 8 } });
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /Wyślij poligon z lukami \(2 osób\)/ }));
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "Wyślij" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/novelties/poligon/luki", {}));
    await waitFor(() => expect(mocks.success).toHaveBeenCalledWith("Wysłane do 2 osób, termin pn 23.11."));
  });
});
