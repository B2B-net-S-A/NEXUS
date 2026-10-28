import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

import {
  MANAGED_IN_NEXUS_LABELS,
  ManagedInNexusChip,
} from "@/components/v2/jobs/ManagedInNexusSwitch";

// Traffit wyłączony na stałe 14.10.2026 (decyzja Artura): chip „Prowadzona
// w NEXUSIE” nie oferuje już powrotu, nawet gdy strona poda `canRevert`.

const mocks = vi.hoisted(() => ({
  setManagedInNexus: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  jobsApi: {
    setManagedInNexus: (...args: unknown[]) => mocks.setManagedInNexus(...args),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

function renderWithQuery(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const managedJob = {
  id: 7,
  external_source: "traffit",
  managed_in_nexus: true,
  managed_in_nexus_at: "2026-09-17T08:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ManagedInNexusChip po wyłączeniu Traffita", () => {
  it("nie otwiera okna powrotu do Traffita, nawet z canRevert", () => {
    renderWithQuery(<ManagedInNexusChip job={managedJob} canRevert />);
    const chip = screen.getByTestId("managed-in-nexus-chip");

    expect(chip).toHaveTextContent("Prowadzona w NEXUSIE od");
    expect(chip).not.toHaveAttribute("role", "button");
    expect(chip).not.toHaveAttribute("tabindex");
    // Dymek to tylko pełny tekst plakietki (skraca się w wąskim nagłówku,
    // 28.10.2026) — bez podpowiedzi powrotu do Traffita.
    expect(chip.getAttribute("title")).toBe(chip.textContent);

    fireEvent.click(chip);
    fireEvent.keyDown(chip, { key: "Enter" });

    expect(screen.queryByText(/Wrócić do prowadzenia w Traffitcie/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("managed-in-nexus-revert-confirm")).not.toBeInTheDocument();
    expect(mocks.setManagedInNexus).not.toHaveBeenCalled();
  });

  it("nie ma już tekstów powrotu do Traffita", () => {
    expect(Object.values(MANAGED_IN_NEXUS_LABELS).join(" ")).not.toMatch(/Wróć do Traffita|wróciła do Traffita/);
  });

  it("podpowiedź plakietki nie obiecuje nocnego importu", () => {
    expect(MANAGED_IN_NEXUS_LABELS.noticeHint).not.toMatch(/nocny import/);
  });
});
