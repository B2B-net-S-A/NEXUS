import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FeedbackSwitch } from "../ReportReminders";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  error: vi.fn(),
  confirm: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: vi.fn(), put: mocks.put },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: mocks.error }),
}));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.confirm, confirmDialog: null }),
}));

const SETTINGS = "/api/finance/settlements/reminders/settings";

function renderWith(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe("Informacja zwrotna o wadach — przełącznik w „Start rozliczeń”", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue({
      data: { enabled: false, feedback: { mode: "off", external: "off", every_days: 3 } },
    });
    mocks.put.mockResolvedValue({
      data: { feedback: { mode: "dry_run", external: "off", every_days: 3 } },
    });
  });

  it("po potwierdzeniu zapisuje tryb na sucho", async () => {
    mocks.confirm.mockResolvedValue(true);
    renderWith(<FeedbackSwitch />);
    fireEvent.click(await screen.findByRole("radio", { name: "Na sucho" }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith(SETTINGS, { feedback: { mode: "dry_run" } }),
    );
    expect(mocks.confirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Informacja zwrotna o wadach: na sucho?" }),
    );
  });

  it("wysyłka poza firmę bez potwierdzenia nie zapisuje nic", async () => {
    mocks.confirm.mockResolvedValue(false);
    renderWith(<FeedbackSwitch />);
    fireEvent.click(await screen.findByRole("radio", { name: "Wszyscy" }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalled());
    expect(mocks.confirm.mock.calls[0][0].description).toMatch(/spoza firmy/);
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("błąd zapisu idzie do komunikatu po polsku", async () => {
    mocks.confirm.mockResolvedValue(true);
    mocks.put.mockRejectedValue(new Error("boom"));
    renderWith(<FeedbackSwitch />);
    fireEvent.click(await screen.findByRole("radio", { name: "Włączona" }));
    await waitFor(() => expect(mocks.error).toHaveBeenCalled());
  });

  it("backend bez informacji zwrotnej: przełącznika nie ma", async () => {
    mocks.get.mockResolvedValue({ data: { enabled: true } });
    renderWith(<FeedbackSwitch />);
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith(SETTINGS));
    expect(screen.queryByText("Informacja zwrotna o wadach")).not.toBeInTheDocument();
  });
});
