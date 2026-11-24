import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CandidateSourcesPanel } from "@/components/candidates/CandidateSourcesPanel";

const mocks = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("@/lib/api", () => ({
  candidateSourcesApi: { list: (...args: unknown[]) => mocks.list(...args) },
}));

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CandidateSourcesPanel candidateId={7} />
    </QueryClientProvider>,
  );
}

describe("Źródła aplikacji przy awarii zapytania (audyt 24.11.2026)", () => {
  beforeEach(() => {
    mocks.list.mockReset();
  });

  it("błąd API to komunikat błędu, nie „Brak zarejestrowanych źródeł”", async () => {
    mocks.list.mockRejectedValue(Object.assign(new Error("Request failed"), { response: { status: 500, data: {} } }));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wczytać źródeł aplikacji.");
    expect(screen.queryByText("Brak zarejestrowanych źródeł aplikacji.")).not.toBeInTheDocument();
  });

  it("pusta lista po udanym zapytaniu = pusty stan", async () => {
    mocks.list.mockResolvedValue({ data: [] });
    renderPanel();
    expect(await screen.findByText("Brak zarejestrowanych źródeł aplikacji.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
