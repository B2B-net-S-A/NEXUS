/**
 * Harness `/preview/order-ended-lines` jest PUBLICZNY — jego twarda obietnica
 * to zero zapytań do API, także po otwarciu panelu osoby i decyzji
 * „Zostaw jako historię".
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import OrderEndedLinesPreview from "@/app/preview/order-ended-lines/page";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(() => Promise.reject(new Error("harness nie może wołać API"))),
    post: vi.fn(() => Promise.reject(new Error("harness nie może wołać API"))),
  },
}));

import { api } from "@/lib/api";

describe("Harness /preview/order-ended-lines", () => {
  it("pokazuje wszystkie stany osoby zakończonej i decyzję bez zapytań do API", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(<OrderEndedLinesPreview />);

    const toggle = screen.getByRole("button", {
      name: /^Zakończone \(4\)\s*· 2 wymagają decyzji$/,
    });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const table = within(document.querySelector("[data-orders-table]") as HTMLElement);
    expect(table.getByText("Zostawiony jako historia")).toBeInTheDocument();
    expect(table.getByText("Zastąpiony przez Ewa Następna")).toBeInTheDocument();

    // Panel osoby: zużycie MD i historia z zasianego cache.
    await user.click(document.getElementById("order-line-2")!);
    const panel = within(screen.getByTestId("order-line-panel"));
    await user.click(panel.getByRole("tab", { name: "Zużycie MD" }));
    await user.click(panel.getByRole("tab", { name: "Historia" }));
    expect(screen.queryByText(/Nie udało się wczytać/)).toBeNull();

    await user.click(panel.getByRole("button", { name: "Podejmij decyzję" }));
    await user.click(screen.getByRole("button", { name: /Zostaw jako historię/ }));

    expect(
      screen.getByRole("button", { name: /^Zakończone \(4\)\s*· 1 wymaga decyzji$/ }),
    ).toBeInTheDocument();
    expect(table.getAllByText("Zostawiony jako historia")).toHaveLength(2);
    expect(vi.mocked(api.get)).not.toHaveBeenCalled();
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
  }, 20_000);
});
