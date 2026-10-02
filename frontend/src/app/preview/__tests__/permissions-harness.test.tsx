/**
 * `/preview/permissions` renderuje prawdziwy ekran „Osoby i role” w trzech
 * wariantach i nie wysyła ani jednego żądania. Strażnik kluczy
 * (`harness-seeds.test.ts`) czyta źródła; ten test montuje stronę — niezasiany
 * odczyt wyszedłby tu jako stan błędu albo wywołanie adaptera.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import PermissionsPreviewPage from "../permissions/page";

const address = vi.hoisted(() => ({ search: "" }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(address.search),
}));

const adapter = vi.fn();
let previousAdapter: typeof api.defaults.adapter;

beforeEach(() => {
  address.search = "";
  adapter.mockReset();
  previousAdapter = api.defaults.adapter;
  api.defaults.adapter = adapter;
});

afterEach(() => {
  api.defaults.adapter = previousAdapter;
  useAuthStore.setState({ user: null, realUser: null });
});

describe("/preview/permissions", () => {
  it("domyślnie: zakładka „Uprawnienia”, rola Finanse, dziewięć przełączników", async () => {
    render(<PermissionsPreviewPage />);

    expect(await screen.findAllByRole("switch")).toHaveLength(9);
    expect(screen.getByRole("button", { name: "Finanse" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText(/Każda rola może pracować z kandydatami/)).toHaveTextContent(
      "Finanse · 1 osoba.",
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(adapter).not.toHaveBeenCalled();
  });

  it("`?tab=users`: lista osób z plakietką dodatkowych uprawnień", async () => {
    address.search = "tab=users";
    render(<PermissionsPreviewPage />);

    const row = await screen.findByRole("row", { name: /Celina Wzorcowa/ });
    expect(within(row).getByText("+1 uprawnienie")).toBeInTheDocument();
    expect(
      within(screen.getByRole("row", { name: /Borys Przykładowy/ })).getByText(
        "+2 uprawnienia",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(adapter).not.toHaveBeenCalled();
  });

  it("`?modal=1`: okno osoby z listą tego, czego jej rola nie daje", async () => {
    address.search = "modal=1";
    render(<PermissionsPreviewPage />);

    expect(
      await screen.findByRole("heading", { name: "Edytuj użytkownika" }),
    ).toBeInTheDocument();
    const group = screen.getByRole("group", { name: "Dodatkowe uprawnienia" });
    expect(
      within(group).getByRole("checkbox", {
        name: "Kontrakty i zamówienia: tworzenie i edycja",
      }),
    ).toBeChecked();
    expect(within(group).getAllByRole("checkbox")).toHaveLength(6);
    expect(group).toHaveTextContent(
      "Lista pokazuje tylko to, czego rola Talent Community Manager nie daje.",
    );
    expect(adapter).not.toHaveBeenCalled();
  });

  it("ołówek przy osobie ze starymi ograniczeniami pokazuje je bez zapytania", async () => {
    address.search = "tab=users";
    const user = userEvent.setup();
    render(<PermissionsPreviewPage />);

    const row = await screen.findByRole("row", { name: /Oskar Podglądowy/ });
    await user.click(within(row).getByRole("button", { name: "Edytuj" }));

    const group = await screen.findByRole("group", { name: "Dodatkowe uprawnienia" });
    await waitFor(() =>
      expect(group).toHaveTextContent("Stare ograniczenia tej osoby:"),
    );
    expect(within(group).getByRole("button", { name: "Usuń ograniczenia" })).toBeInTheDocument();
    expect(adapter).not.toHaveBeenCalled();
  });
});
