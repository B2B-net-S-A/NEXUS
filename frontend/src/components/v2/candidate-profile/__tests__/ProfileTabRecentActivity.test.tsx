import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    default: { get: vi.fn(() => Promise.resolve({ data: [] })), post: vi.fn(), patch: vi.fn() },
  };
});
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn(), showToast: vi.fn() }),
}));
// Karty zależne od własnych zapytań nie są przedmiotem testu.
vi.mock("@/components/v2/LinkedinSyncPanel", () => ({ LinkedinSyncPanel: () => null }));
vi.mock("@/components/candidates/CandidateEngagementPanel", () => ({
  CandidateEngagementPanel: () => null,
}));
vi.mock("@/components/candidates/CandidateLocationPanel", () => ({
  CandidateLocationPanel: () => null,
}));
vi.mock("@/components/candidates/CandidateSourcesPanel", () => ({
  CandidateSourcesPanel: () => null,
}));
vi.mock("@/components/candidates/CvReparseAction", () => ({ CvReparseAction: () => null }));
vi.mock("@/components/v2/pages/CandidateActivitySummaryCard", () => ({
  CandidateActivitySummaryCard: () => null,
}));
vi.mock("@/components/v2/pages/CandidateNotesFactsCard", () => ({
  CandidateNotesFactsCard: () => null,
}));
vi.mock("@/components/v2/pages/CandidateRecentRecruitmentsCard", () => ({
  CandidateRecentRecruitmentsCard: () => null,
}));
vi.mock("@/components/v2/candidate-profile/JdgPanel", () => ({ JDGPanel: () => null }));

import { ProfileTab } from "@/components/v2/candidate-profile/ProfileTab";

function renderTab(recentActivity: Parameters<typeof ProfileTab>[0]["recentActivity"]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProfileTab
        candidate={{ id: 3, name: "Jan", lastname: "Testowy", skills: [], experience: [] }}
        readOnly
        recentActivity={recentActivity}
        onNavigate={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

describe("ProfileTab — „Ostatnia aktywność” (R10-N15-9)", () => {
  it("awaria osi czasu to komunikat z „Ponów”, nie „Brak zdarzeń.”", () => {
    const refetch = vi.fn();
    renderTab({ items: [], isPending: false, isError: true, refetch });
    expect(screen.queryByText("Brak zdarzeń.")).toBeNull();
    const alert = screen.getByText("Nie udało się pobrać aktywności").closest("[role='alert']");
    expect(alert).not.toBeNull();
    fireEvent.click(within(alert as HTMLElement).getByRole("button", { name: "Ponów" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("pusta, udana oś czasu nadal mówi „Brak zdarzeń.”", () => {
    renderTab({ items: [], isPending: false, isError: false });
    expect(screen.getByText("Brak zdarzeń.")).toBeTruthy();
  });
});
