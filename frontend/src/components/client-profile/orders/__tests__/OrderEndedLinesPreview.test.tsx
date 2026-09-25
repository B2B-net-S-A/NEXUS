/**
 * Harness `/preview/order-ended-lines` jest PUBLICZNY — jego twarda obietnica
 * to zero zapytań do API, także po decyzji „Zostaw jako historię".
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
  it("pokazuje wszystkie stany karty i decyzję bez zapytań do API", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(<OrderEndedLinesPreview />);

    const heading = screen.getByRole("heading", {
      name: /Zakończone \(4\)\s*· 2 wymagają decyzji/,
    });
    expect(within(heading).getByRole("button")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Zostawiony jako historia")).toBeInTheDocument();
    expect(screen.getByText("Zastąpiony przez Ewa Następna")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Podejmij decyzję — Karol Przykładowy" }),
    );
    await user.click(screen.getByRole("button", { name: /Zostaw jako historię/ }));

    expect(
      screen.getByRole("heading", { name: /Zakończone \(4\)\s*· 1 wymaga decyzji/ }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Zostawiony jako historia")).toHaveLength(2);
    expect(vi.mocked(api.get)).not.toHaveBeenCalled();
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
  }, 20_000);
});
