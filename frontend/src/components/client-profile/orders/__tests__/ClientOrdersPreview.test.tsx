/**
 * Harness `/preview/client-orders` jest PUBLICZNY — renderuje całą zakładkę
 * „Zamówienia" na zasianym cache i obiecuje zero zapytań do API, także po
 * otwarciu każdego rodzaju panelu i przy wejściu z `?group=` / `?order=` /
 * `?contract=`.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  const reject = () => Promise.reject(new Error("harness nie może wołać API"));
  return {
    ...actual,
    api: {
      get: vi.fn(reject),
      post: vi.fn(reject),
      put: vi.fn(reject),
      patch: vi.fn(reject),
      delete: vi.fn(reject),
      interceptors: { request: { use: vi.fn(() => 1), eject: vi.fn() } },
    },
  };
});

import ClientOrdersPreview from "@/app/preview/client-orders/page";
import { api } from "@/lib/api";

function expectNoRequests() {
  for (const method of ["get", "post", "put", "patch", "delete"] as const) {
    expect(vi.mocked(api[method]), method).not.toHaveBeenCalled();
  }
}

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("Harness /preview/client-orders", () => {
  it("pokazuje sekcje MD → Kosztowe → Okresowe i każdy panel bez zapytań", async () => {
    window.history.replaceState(null, "", "/preview/client-orders");
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const view = render(<ClientOrdersPreview />);

    await screen.findByText("Zamówienie nr 4599050001");
    const text = view.container.textContent ?? "";
    expect(text.indexOf("MD (")).toBeLessThan(text.indexOf("Kosztowe ("));
    expect(text.indexOf("Kosztowe (")).toBeLessThan(text.indexOf("Okresowe ("));
    // Decyzja czeka — sekcja „Zakończone” rozwinięta, pigułka widoczna.
    expect(
      screen.getByRole("button", { name: /^Zakończone \(3\)\s*· 1 wymaga decyzji$/ }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "Wymaga decyzji (1)" })).toBeInTheDocument();

    await user.click(document.getElementById("order-group-anchor-501")!);
    await user.click(
      within(screen.getByTestId("order-group-panel")).getByRole("tab", { name: /^Historia/ }),
    );
    expect(await screen.findByText("Import MD")).toBeInTheDocument();

    await user.click(document.getElementById("order-line-5011")!);
    expect(await screen.findByText("lip 2026")).toBeInTheDocument();

    await user.click(document.getElementById("order-line-5015")!);
    expect(
      within(screen.getByTestId("order-line-panel")).getByRole("button", {
        name: "Podejmij decyzję",
      }),
    ).toBeInTheDocument();

    await user.click(document.getElementById("contractor-row-813")!);
    expect(screen.getByTestId("contractor-order-panel")).toHaveTextContent("Leon Szkicowy");

    expect(screen.queryByText(/Nie udało się wczytać/)).toBeNull();
    expectNoRequests();
  }, 30_000);

  it.each([
    ["?group=503", "order-group-panel", "Zamówienie nr SAP 4599050003"],
    ["?order=5015", "order-line-panel", "Ewa Czekająca"],
    ["?contract=813", "contractor-order-panel", "Leon Szkicowy"],
  ])("%s otwiera od wejścia właściwy panel", async (query, testId, text) => {
    window.history.replaceState(null, "", `/preview/client-orders${query}`);
    render(<ClientOrdersPreview />);
    await waitFor(() => expect(screen.getByTestId(testId)).toHaveTextContent(text));
    expectNoRequests();
  });
});
