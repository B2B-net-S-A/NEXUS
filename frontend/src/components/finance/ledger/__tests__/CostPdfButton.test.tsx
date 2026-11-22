import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openAuthenticatedFile = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/authenticated-files", () => ({
  openAuthenticatedFile: (...a: unknown[]) => openAuthenticatedFile(...a),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/lib/api", () => ({ __esModule: true, api: { get: vi.fn() } }));

import { CostPdfButton } from "@/components/finance/ledger/CostPdfButton";

beforeEach(() => {
  openAuthenticatedFile.mockReset();
  showToast.mockReset();
});

describe("CostPdfButton", () => {
  it("otwiera podgląd PDF faktury z kolejki", async () => {
    openAuthenticatedFile.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<CostPdfButton entryId={11} invoiceNumber="7/11/2026" />);
    await user.click(screen.getByRole("button", { name: "Podgląd PDF faktury 7/11/2026" }));
    expect(openAuthenticatedFile).toHaveBeenCalledWith(
      "/api/finance/costs/11/pdf",
      "application/pdf",
      "faktura-11.pdf",
    );
    expect(showToast).not.toHaveBeenCalled();
  });

  it("odmowę backendu pokazuje komunikatem, a nie pustą kartą", async () => {
    openAuthenticatedFile.mockRejectedValue(
      Object.assign(new Error("Nie ma tej faktury w KSeF."), {
        response: { status: 404, data: { detail: "Nie ma tej faktury w KSeF." } },
      }),
    );
    const user = userEvent.setup();
    render(<CostPdfButton entryId={12} invoiceNumber={null} look="icon" />);
    await user.click(screen.getByRole("button", { name: "Podgląd PDF faktury #12" }));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Nie ma tej faktury w KSeF.", "error"),
    );
  });
});
