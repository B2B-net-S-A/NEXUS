/**
 * Harness `/preview/order-md-scopes` ma być PUBLICZNY, więc jego jedyna twarda
 * obietnica brzmi: zero zapytań do API — także po otwarciu rozliczeń
 * miesięcznych (lazy query) i historii zamówienia.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import OrderMdScopesPreview from "@/app/preview/order-md-scopes/page";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(() => Promise.reject(new Error("harness nie może wołać API"))),
    put: vi.fn(() => Promise.reject(new Error("harness nie może wołać API"))),
    delete: vi.fn(() => Promise.reject(new Error("harness nie może wołać API"))),
  },
}));

import { api } from "@/lib/api";

describe("Harness /preview/order-md-scopes", () => {
  it("renderuje oba warianty, otwiera rozliczenia z cache i nie wysyła zapytań", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(<OrderMdScopesPreview />);

    // Nagłówek: umowa wykonawcza z częścią i kwoty tylko w wariancie z finansami.
    expect(screen.getAllByText("Umowa wykonawcza CeZ/242/2025 · Cz. II")).toHaveLength(2);
    expect(screen.getAllByText(/Wykorzystano wartości umowy/)).toHaveLength(1);
    // Karta konsultanta CeZ: zastąpiony → następca, brak opcji w umowie,
    // przekroczenie i korekta ręczna wprost przy „Łącznie".
    expect(screen.getAllByText("Zastąpiony")).toHaveLength(2);
    expect(screen.getAllByText("Brak opcji w umowie").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/przekroczono o 8 MD/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/w tym korekta \+10 MD/).length).toBeGreaterThan(0);
    // Przyszłe zamówienie pod kartą (tylko wariant z finansami).
    expect(screen.getByText("Przyszłe zamówienia (1)")).toBeInTheDocument();

    await user.click(
      screen.getAllByRole("button", { name: "Rozliczenia miesięczne — Anna Przykładowa" })[0],
    );
    expect(await screen.findByText("gru 2025")).toBeInTheDocument();
    expect(screen.queryByText(/Nie udało się wczytać/)).toBeNull();

    expect(vi.mocked(api.get)).not.toHaveBeenCalled();
  }, 20_000);
});
