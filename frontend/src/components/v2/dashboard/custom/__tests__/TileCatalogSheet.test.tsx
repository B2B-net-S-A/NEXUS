import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TileCatalogSheet } from "@/components/v2/dashboard/custom/TileCatalogSheet";

function renderSheet(hiddenPanels: "cv_in_transit"[], onRestorePanel = vi.fn()) {
  render(
    <TileCatalogSheet
      open
      onOpenChange={() => {}}
      user={{ id: 1, role: "recruiter", roles: ["recruiter"] } as never}
      onPick={() => {}}
      onCustomMetric={() => {}}
      hiddenPanels={hiddenPanels}
      onRestorePanel={onRestorePanel}
    />,
  );
  return onRestorePanel;
}

describe("TileCatalogSheet — przywrócenie listy „Twoje CV w drodze”", () => {
  it("lista usunięta z pulpitu ma w katalogu „Przywróć”", async () => {
    const onRestore = renderSheet(["cv_in_transit"]);
    await userEvent.click(screen.getByRole("button", { name: "Przywróć listę Twoje CV w drodze" }));
    expect(onRestore).toHaveBeenCalledWith("cv_in_transit");
  });

  it("lista stoi na pulpicie → katalog jej nie proponuje (każdy ma ją domyślnie)", () => {
    renderSheet([]);
    expect(screen.queryByRole("button", { name: /Przywróć listę/ })).toBeNull();
    expect(screen.getByText("Własna metryka")).toBeTruthy();
  });
});
