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
  it("domyślnie: zakładka „Uprawnienia”, rola Finanse, osiemnaście przełączników", async () => {
    render(<PermissionsPreviewPage />);

    expect(await screen.findAllByRole("switch")).toHaveLength(18);
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

  it("`?modal=1`: okno osoby z całym katalogiem i stanem każdego uprawnienia", async () => {
    address.search = "modal=1";
    render(<PermissionsPreviewPage />);

    expect(
      await screen.findByRole("heading", { name: "Edytuj użytkownika" }),
    ).toBeInTheDocument();
    const group = screen.getByRole("group", { name: "Uprawnienia tej osoby" });
    expect(within(group).getAllByRole("radiogroup")).toHaveLength(18);
    const granted = within(group).getByRole("radiogroup", {
      name: "Kontrakty i zamówienia: tworzenie i edycja",
    });
    expect(within(granted).getByRole("radio", { name: "Nadane" })).toBeChecked();
    const fromRole = within(group).getByRole("radiogroup", {
      name: "Zakończenie współpracy, zmiana statusu kontraktu",
    });
    expect(within(fromRole).getByRole("radio", { name: "Z roli" })).toBeChecked();
    expect(group).toHaveTextContent("Rola daje punkt wyjścia.");
    expect(adapter).not.toHaveBeenCalled();
  });

  it("ołówek przy osobie ze starymi ograniczeniami pokazuje je bez zapytania", async () => {
    address.search = "tab=users";
    const user = userEvent.setup();
    render(<PermissionsPreviewPage />);

    const row = await screen.findByRole("row", { name: /Oskar Podglądowy/ });
    await user.click(within(row).getByRole("button", { name: "Edytuj" }));

    const group = await screen.findByRole("group", { name: "Uprawnienia tej osoby" });
    await waitFor(() =>
      expect(group).toHaveTextContent("Stare ograniczenia tej osoby: Delivery: tylko odczyt."),
    );
    expect(within(group).getByRole("button", { name: "Usuń ograniczenia" })).toBeInTheDocument();
    const revoked = within(group).getByRole("radiogroup", {
      name: "Zakończenie współpracy, zmiana statusu kontraktu",
    });
    expect(within(revoked).getByRole("radio", { name: "Odebrane" })).toBeChecked();
    expect(adapter).not.toHaveBeenCalled();
  });
});
