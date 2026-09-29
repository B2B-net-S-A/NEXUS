/**
 * Harness `/preview/order-lifecycle` jest PUBLICZNY (poza `PROTECTED_ROUTES`),
 * więc jego jedyna twarda obietnica brzmi: zero zapytań do API. Niezasiany
 * klucz react-query poleciałby po dane, dostał 401, a globalny interceptor
 * axiosa przerzuciłby stronę na `/login` — podgląd zniknąłby oglądającemu
 * z ekranu. Ten test pilnuje tej obietnicy przy każdej kolejnej zmianie
 * tabeli i paneli.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import OrderLifecyclePreview from "@/app/preview/order-lifecycle/page";

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn(() => Promise.reject(new Error("harness nie może wołać API"))) },
}));

import { api } from "@/lib/api";

/** Otwiera panel każdego zamówienia i jego historię — to są listy, które
 *  renderują się dopiero po kliknięciu. */
async function openEveryHistory(user: ReturnType<typeof userEvent.setup>) {
  const rows = Array.from(
    document.querySelectorAll<HTMLElement>('[data-order-row="group"], [data-order-row="future"]'),
  );
  expect(rows.length).toBeGreaterThanOrEqual(8);
  for (const row of rows) {
    await user.click(row);
    const panel = within(screen.getByTestId("order-group-panel"));
    await user.click(panel.getByRole("tab", { name: /^Historia/ }));
    expect(screen.queryByText(/Nie udało się wczytać historii/)).toBeNull();
  }
}

describe("Harness /preview/order-lifecycle", () => {
  it("otwiera historię każdego zamówienia z zasianego cache i nie wysyła ani jednego zapytania", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(<OrderLifecyclePreview />);

    await openEveryHistory(user);

    // Wpis `transfer_md` z powiązaniem — numer otwiera panel następcy.
    const transferRow = document.getElementById("order-group-anchor-15")!;
    await user.click(transferRow);
    await user.click(
      within(screen.getByTestId("order-group-panel")).getByRole("tab", { name: /^Historia/ }),
    );
    await user.click(screen.getByRole("button", { name: "Pokaż zamówienie nr 4599009903" }));
    expect(
      within(screen.getByTestId("order-group-panel")).getByText("Zamówienie nr 4599009903"),
    ).toBeInTheDocument();
    expect(document.getElementById("order-group-anchor-16")).toHaveAttribute("aria-selected", "true");

    // …i ten sam typ wpisu bez powiązania — sam tekst, bez martwego przycisku.
    await user.click(transferRow);
    await user.click(
      within(screen.getByTestId("order-group-panel")).getByRole("tab", { name: /^Historia/ }),
    );
    expect(screen.getByText(/kontynuacja na zamówieniu nr 4599009904/)).toBeInTheDocument();

    // Panel osoby: zużycie MD z zasianego cache.
    await user.click(document.getElementById("order-line-146")!);
    await user.click(
      within(screen.getByTestId("order-line-panel")).getByRole("tab", { name: "Zużycie MD" }),
    );
    expect(screen.queryByText(/Nie udało się wczytać/)).toBeNull();
    expect(vi.mocked(api.get)).not.toHaveBeenCalled();
    // Jawny limit: test przeklikuje historię KAŻDEGO zamówienia harnessu.
  }, 30_000);

  /**
   * Zduplikowany `key` w tabeli nie jest kosmetyką: React przy kolizji
   * ZOSTAWIA JEDNO dziecko, więc wiersz osoby albo wpis historii po cichu
   * znika z ekranu. Ostrzeżenie leci tylko na `console.error` w trybie
   * deweloperskim, więc bez tego testu nikt go nie zobaczy w CI.
   */
  it("renderuje wszystkie tabele i panele bez ostrzeżeń Reacta o kluczach", async () => {
    const warnings: string[] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
      warnings.push(args.map((arg) => String(arg)).join(" "));
    });

    try {
      const user = userEvent.setup({ pointerEventsCheck: 0 });
      render(<OrderLifecyclePreview />);
      for (const toggle of screen.getAllByRole("button", { name: /^Zakończone/ })) {
        if (toggle.getAttribute("aria-expanded") === "false") await user.click(toggle);
      }
      await openEveryHistory(user);
    } finally {
      spy.mockRestore();
    }

    expect(warnings.filter((line) => line.includes("same key"))).toEqual([]);
  }, 30_000);
});
