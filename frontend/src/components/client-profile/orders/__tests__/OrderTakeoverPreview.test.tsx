/**
 * Harness `/preview/order-takeover` jest PUBLICZNY — obiecuje zero zapytań
 * do API i pokazuje stany z ticketu 09.2026 (zastępstwo, zaplanowane).
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
}));
vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(() => Promise.reject(new Error("harness nie może wołać API"))),
    post: vi.fn(() => Promise.reject(new Error("harness nie może wołać API"))),
  },
}));

import OrderTakeoverPreview from "@/app/preview/order-takeover/page";
import { api } from "@/lib/api";

describe("Harness /preview/order-takeover", () => {
  it("pokazuje zastępstwo i zastępstwo zaplanowane bez zapytań", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(<OrderTakeoverPreview />);

    // Po zastępstwie: plakietka w tabeli i opis przejęcia w otwartym panelu.
    expect(within(document.getElementById("order-line-4")!).getByText("Zastępstwo")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("order-line-panel")).getByText(
        /Przejęła po: Konrad Odchodzący · 187 MD \(1:1\)/,
      ),
    ).toBeInTheDocument();

    // Zaplanowane: wiersz osoby odchodzącej i osoby wchodzącej.
    expect(document.getElementById("order-line-10")).toHaveTextContent("Zastępstwo od 01.11.2026");
    expect(document.getElementById("order-line-11")).toHaveTextContent("Zastępstwo od 01.11.2026");
    await user.click(document.getElementById("order-line-11")!);
    expect(
      within(screen.getAllByTestId("order-line-panel").at(-1)!).getByText(
        "Zaplanowane zastępstwo od 01.11.2026",
      ),
    ).toBeInTheDocument();

    expect(vi.mocked(api.get)).not.toHaveBeenCalled();
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
  });
});
