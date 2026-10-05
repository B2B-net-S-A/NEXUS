import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const updateEngagement = vi.fn();
const showError = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { post: vi.fn() },
  candidateProfileApi: {
    updateEngagement: (...a: unknown[]) => updateEngagement(...a),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError, showSuccess: vi.fn(), showToast: vi.fn() }),
}));

import { CandidateEngagementPanel } from "@/components/candidates/CandidateEngagementPanel";

const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
const wrap = (ui: ReactNode) => <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;

const forbidden = {
  isAxiosError: true,
  response: { status: 403, data: { detail: "Brak uprawnień do edycji kandydata." } },
};

beforeEach(() => {
  updateEngagement.mockReset();
  showError.mockReset();
});

describe("CandidateEngagementPanel", () => {
  it("wpisana notatka przeżywa przerysowanie z równym, ale nowym obiektem initial", async () => {
    const view = render(
      wrap(<CandidateEngagementPanel candidateId={7} initial={{ engagement_notes: "stara" }} />),
    );
    const textarea = screen.getByPlaceholderText(/Jaką rolę/);
    await userEvent.clear(textarea);
    await userEvent.type(textarea, "nowa treść");
    view.rerender(
      wrap(<CandidateEngagementPanel candidateId={7} initial={{ engagement_notes: "stara" }} />),
    );
    expect(textarea).toHaveValue("nowa treść");
  });

  it("zmiana kandydata ustawia formularz od nowa", async () => {
    const view = render(
      wrap(<CandidateEngagementPanel candidateId={7} initial={{ engagement_notes: "A" }} />),
    );
    await userEvent.type(screen.getByPlaceholderText(/Jaką rolę/), "x");
    view.rerender(
      wrap(<CandidateEngagementPanel candidateId={8} initial={{ engagement_notes: "B" }} />),
    );
    expect(screen.getByPlaceholderText(/Jaką rolę/)).toHaveValue("B");
  });

  it("nieudany zapis (403) pokazuje toast z powodem", async () => {
    updateEngagement.mockRejectedValue(forbidden);
    render(wrap(<CandidateEngagementPanel candidateId={7} initial={{}} />));
    await userEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await vi.waitFor(() =>
      expect(showError).toHaveBeenCalledWith("Brak uprawnień do edycji kandydata."),
    );
  });
});
