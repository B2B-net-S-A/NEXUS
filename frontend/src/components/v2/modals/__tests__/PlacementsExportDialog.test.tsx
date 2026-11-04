import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlacementsExportDialog } from "@/components/v2/modals/PlacementsExportDialog";
import { defaultPlacementsRange } from "@/lib/placements-export";
import { localTodayIso } from "@/lib/client-order-list";

function setup(onExport = vi.fn().mockResolvedValue(true)) {
  const onOpenChange = vi.fn();
  render(
    <PlacementsExportDialog
      open
      onOpenChange={onOpenChange}
      busy={false}
      onExport={onExport}
    />,
  );
  return { onExport, onOpenChange };
}

describe("PlacementsExportDialog", () => {
  it("starts on the current month and downloads that range", async () => {
    const { onExport, onOpenChange } = setup();

    fireEvent.click(screen.getByRole("button", { name: "Pobierz" }));

    await waitFor(() =>
      expect(onExport).toHaveBeenCalledWith(defaultPlacementsRange(localTodayIso())),
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("blocks a reversed range and says why", () => {
    const { onExport } = setup();

    fireEvent.change(screen.getByLabelText("Start od"), {
      target: { value: "2026-10-31" },
    });
    fireEvent.change(screen.getByLabelText("Start do"), {
      target: { value: "2026-10-01" },
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Data „do” jest wcześniejsza niż „od”.",
    );
    expect(screen.getByRole("button", { name: "Pobierz" })).toBeDisabled();
    expect(onExport).not.toHaveBeenCalled();
  });

  it("stays open when the download fails", async () => {
    const { onExport, onOpenChange } = setup(vi.fn().mockResolvedValue(false));

    fireEvent.click(screen.getByRole("button", { name: "Pobierz" }));

    await waitFor(() => expect(onExport).toHaveBeenCalled());
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});
