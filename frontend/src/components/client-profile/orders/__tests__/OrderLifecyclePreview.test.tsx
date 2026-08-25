/**
 * Harness `/preview/order-lifecycle` jest PUBLICZNY (poza `PROTECTED_ROUTES`),
 * więc jego jedyna twarda obietnica brzmi: zero zapytań do API. Niezasiany
 * klucz react-query poleciałby po dane, dostał 401, a globalny interceptor
 * axiosa przerzuciłby stronę na `/login` — podgląd zniknąłby oglądającemu
 * z ekranu. Ten test pilnuje tej obietnicy przy każdej kolejnej zmianie kart.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import OrderLifecyclePreview from "@/app/preview/order-lifecycle/page";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn(() => Promise.reject(new Error("harness nie może wołać API"))) },
}));

import { api } from "@/lib/api";

describe("Harness /preview/order-lifecycle", () => {
  it("rozwija każdą historię z zasianego cache i nie wysyła ani jednego zapytania", async () => {
    const user = userEvent.setup();
    render(<OrderLifecyclePreview />);

    for (const button of screen.getAllByRole("button", {
      name: /Historia zamówienia/,
    })) {
      await user.click(button);
    }

    // Wpis `transfer_md` z powiązaniem — numer jest przejściem do następcy.
    expect(
      screen.getByRole("button", { name: "Pokaż zamówienie nr 4500029903" }),
    ).toBeInTheDocument();
    // …i ten sam typ wpisu bez powiązania — sam tekst, bez martwego przycisku.
    expect(
      screen.getByText(/kontynuacja na zamówieniu nr 4500029904/),
    ).toBeInTheDocument();
    // Awaria pobrania renderuje się inaczej niż pustka — gdyby któryś klucz
    // nie był zasiany, zobaczylibyśmy tu komunikat błędu, nie wpisy.
    expect(screen.queryByText(/Nie udało się wczytać historii/)).toBeNull();
    expect(vi.mocked(api.get)).not.toHaveBeenCalled();
    // Jawny limit: ten test przeklikuje historię KAŻDEJ karty harnessu, więc
    // rośnie razem z listą przypadków i domyślne 5 s przestaje wystarczać.
  }, 20_000);
});
