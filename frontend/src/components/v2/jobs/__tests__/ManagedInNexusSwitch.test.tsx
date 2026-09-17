import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

import {
  MANAGED_IN_NEXUS_LABELS,
  ManagedInNexusBanner,
  ManagedInNexusChip,
} from "@/components/v2/jobs/ManagedInNexusSwitch";

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

const traffitJob = {
  id: 7,
  external_source: "traffit",
  managed_in_nexus: false,
  managed_in_nexus_at: null,
};

const managedJob = {
  id: 7,
  external_source: "traffit",
  managed_in_nexus: true,
  managed_in_nexus_at: "2026-09-17T08:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.setManagedInNexus.mockResolvedValue({ data: managedJob });
});

describe("ManagedInNexusBanner", () => {
  it("shows the banner for a Traffit recruitment that is not switched yet", () => {
    renderWithQuery(<ManagedInNexusBanner job={traffitJob} canSwitch />);
    expect(screen.getByTestId("managed-in-nexus-banner")).toBeInTheDocument();
    expect(screen.getByText(MANAGED_IN_NEXUS_LABELS.bannerTitle)).toBeInTheDocument();
    expect(screen.getByTestId("managed-in-nexus-switch")).toBeInTheDocument();
  });

  it("renders nothing for a recruitment created in NEXUS", () => {
    renderWithQuery(
      <ManagedInNexusBanner job={{ ...traffitJob, external_source: "manual" }} canSwitch />,
    );
    expect(screen.queryByTestId("managed-in-nexus-banner")).not.toBeInTheDocument();
  });

  it("renders nothing once the recruitment is managed in NEXUS", () => {
    renderWithQuery(<ManagedInNexusBanner job={managedJob} canSwitch />);
    expect(screen.queryByTestId("managed-in-nexus-banner")).not.toBeInTheDocument();
  });

  it("hides the switch button without permission but keeps the warning", () => {
    renderWithQuery(<ManagedInNexusBanner job={traffitJob} canSwitch={false} />);
    expect(screen.getByTestId("managed-in-nexus-banner")).toBeInTheDocument();
    expect(screen.queryByTestId("managed-in-nexus-switch")).not.toBeInTheDocument();
  });

  it("switches the recruitment after confirmation", async () => {
    renderWithQuery(<ManagedInNexusBanner job={traffitJob} canSwitch />);
    fireEvent.click(screen.getByTestId("managed-in-nexus-switch"));
    expect(await screen.findByText(MANAGED_IN_NEXUS_LABELS.enableTitle)).toBeInTheDocument();
    expect(mocks.setManagedInNexus).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("managed-in-nexus-confirm"));

    await waitFor(() => expect(mocks.setManagedInNexus).toHaveBeenCalledWith(7, true));
    await waitFor(() =>
      expect(mocks.showSuccess).toHaveBeenCalledWith(MANAGED_IN_NEXUS_LABELS.enabledToast),
    );
  });
});

describe("ManagedInNexusChip", () => {
  it("renders only for a managed recruitment and shows the switch date", () => {
    const { rerender } = renderWithQuery(
      <ManagedInNexusChip job={traffitJob} canRevert />,
    );
    expect(screen.queryByTestId("managed-in-nexus-chip")).not.toBeInTheDocument();

    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <ManagedInNexusChip job={managedJob} canRevert />
      </QueryClientProvider>,
    );
    const chip = screen.getByTestId("managed-in-nexus-chip");
    expect(chip).toHaveTextContent("Prowadzona w NEXUSIE od");
    expect(chip).toHaveTextContent(
      new Intl.DateTimeFormat("pl-PL").format(new Date(managedJob.managed_in_nexus_at)),
    );
  });

  it("does not open the revert dialog without permission", () => {
    renderWithQuery(<ManagedInNexusChip job={managedJob} canRevert={false} />);
    fireEvent.click(screen.getByTestId("managed-in-nexus-chip"));
    expect(screen.queryByText(MANAGED_IN_NEXUS_LABELS.revertTitle)).not.toBeInTheDocument();
    expect(mocks.setManagedInNexus).not.toHaveBeenCalled();
  });

  it("reverts to Traffit after confirmation when allowed", async () => {
    mocks.setManagedInNexus.mockResolvedValue({ data: traffitJob });
    renderWithQuery(<ManagedInNexusChip job={managedJob} canRevert />);
    fireEvent.click(screen.getByTestId("managed-in-nexus-chip"));
    expect(await screen.findByText(MANAGED_IN_NEXUS_LABELS.revertTitle)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("managed-in-nexus-revert-confirm"));

    await waitFor(() => expect(mocks.setManagedInNexus).toHaveBeenCalledWith(7, false));
    await waitFor(() =>
      expect(mocks.showSuccess).toHaveBeenCalledWith(MANAGED_IN_NEXUS_LABELS.revertedToast),
    );
  });
});
