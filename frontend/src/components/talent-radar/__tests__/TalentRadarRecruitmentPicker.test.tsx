import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.get(...args) },
}));

import { TalentRadarRecruitmentPicker } from "@/components/talent-radar/TalentRadarRecruitmentPicker";

function renderPicker(onChange = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <TalentRadarRecruitmentPicker value={null} onChange={onChange} />
    </QueryClientProvider>,
  );
  return onChange;
}

describe("TalentRadarRecruitmentPicker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue({
      data: {
        items: [
          {
            id: 71,
            title: "Senior Python Developer",
            client_id: 7,
            client_name: "Acme Sp. z o.o.",
          },
          {
            id: 72,
            title: "Zamknięty rekord bez klienta",
            client_id: null,
            client_name: null,
          },
        ],
      },
    });
  });

  it("pobiera otwarte rekrutacje i zwraca id razem z klientem", async () => {
    const user = userEvent.setup();
    const onChange = renderPicker();

    await user.click(
      screen.getByRole("combobox", { name: /Wybierz rekrutację/ }),
    );
    await user.click(
      await screen.findByRole("option", { name: /Senior Python Developer/ }),
    );

    expect(mocks.get).toHaveBeenCalledWith("/api/jobs", {
      params: { open_only: true, page_size: 100, sort: "newest" },
    });
    expect(onChange).toHaveBeenCalledWith({
      id: 71,
      title: "Senior Python Developer",
      clientId: 7,
      clientName: "Acme Sp. z o.o.",
    });
    expect(
      screen.queryByText("Zamknięty rekord bez klienta"),
    ).not.toBeInTheDocument();
  });
});
