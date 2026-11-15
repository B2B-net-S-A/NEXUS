import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: (...a: unknown[]) => get(...a), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

import { ComplianceBanner } from "@/components/compliance/ComplianceBanner";
import { useAuthStore } from "@/store/auth";

function renderBanner() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <div data-testid="host">
        <ComplianceBanner role="accounting" />
      </div>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  useAuthStore.setState({
    user: { id: 5, role: "finance", roles: ["finance"] },
    realUser: null,
    hydrated: true,
  } as never);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("Przepisy — pasek w module", () => {
  it("zmiany do decyzji: liczba, tytuły i link z soczewką roli", async () => {
    get.mockResolvedValue({
      data: {
        enabled: true,
        to_decide: 2,
        deadlines: 1,
        deadline_window_days: 60,
        top: [{ id: 3, title: "Przykładowy termin", urgency: "now", deadline: "2099-01-15" }],
      },
    });
    renderBanner();
    const link = await screen.findByRole("link");
    expect(link).toHaveAttribute("href", "/compliance?lens=accounting");
    expect(link).toHaveTextContent("Przepisy: 2 zmiany dla Księgowości do decyzji");
    expect(link).toHaveTextContent("Przykładowy termin (do 15.01.2099)");
    expect(get).toHaveBeenCalledWith("/api/compliance/summary", { params: { role: "accounting" } });
  });

  it("zero do decyzji: nic", async () => {
    get.mockResolvedValue({
      data: { enabled: true, to_decide: 0, deadlines: 3, deadline_window_days: 60, top: [] },
    });
    renderBanner();
    await waitFor(() => expect(get).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByTestId("host")).toBeEmptyDOMElement();
  });

  it("wyłączony radar albo błąd: nic", async () => {
    get.mockResolvedValueOnce({ data: { enabled: false, to_decide: 0, deadlines: 0, top: [] } });
    const first = renderBanner();
    await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("host")).toBeEmptyDOMElement();
    first.unmount();

    get.mockRejectedValueOnce(Object.assign(new Error("boom"), { response: { status: 500 } }));
    renderBanner();
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("host")).toBeEmptyDOMElement();
  });

  it("osoba bez dostępu do „Przepisów”: bez zapytania", () => {
    useAuthStore.setState({
      user: { id: 6, role: "recruiter", roles: ["recruiter"] },
      realUser: null,
      hydrated: true,
    } as never);
    renderBanner();
    expect(screen.getByTestId("host")).toBeEmptyDOMElement();
    expect(get).not.toHaveBeenCalled();
  });
});
