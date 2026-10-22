/**
 * `/preview/hr-structure` (etap 2, „Ludzie → Struktura”): prawdziwa Struktura
 * na danych fikcyjnych, ZERO prób żądania — także po zaznaczeniu osób
 * i otwarciu okien zmiany koordynatora, pionu i headów pionów.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-structure",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrStructurePreviewPage from "../hr-structure/page";

// Cała strona z prawdziwymi ekranami — na obciążonej maszynie 5 s nie wystarcza.
vi.setConfig({ testTimeout: 20_000 });

/** Każda PRÓBA żądania, także odrzucona przez interceptor harnessu. */
const attempts = vi.spyOn(Axios.prototype, "request");
const attempted = () =>
  attempts.mock.calls.map(([config]) => {
    const { method, url } = config as { method?: string; url?: string };
    return `${(method ?? "get").toUpperCase()} ${url}`;
  });

afterEach(() => {
  attempts.mockClear();
  window.history.replaceState({}, "", "/");
  useAuthStore.setState({ user: null, realUser: null });
});

describe("/preview/hr-structure", () => {
  it("Schemat (domyślnie): drzewo kart, „Porządki” i menu karty bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-structure");
    render(<HrStructurePreviewPage />);

    expect(await screen.findByRole("button", { name: "Schemat" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByTestId(`org-card-${105}`)).toHaveTextContent("Marta Fikcyjna");
    expect(screen.getAllByText("head: Kamil Testowy").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Więcej: Ewa Makietowa" }));
    await user.click(await screen.findByRole("menuitem", { name: "Zmień koordynatora…" }));
    expect(
      await screen.findByRole("dialog", { name: "Zmień koordynatora (1)" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Anuluj" }));

    await user.click(screen.getByRole("button", { name: /^Porządki · \d+$/ }));
    const panel = await screen.findByRole("dialog", { name: "Porządki" });
    const todo = within(panel).getByRole("region", { name: "Struktura" });
    expect(within(todo).getByText(/kończy współpracę/)).toBeInTheDocument();
    expect(within(todo).getByRole("button", { name: "Przyjmij z M365" })).toBeInTheDocument();
    expect(within(todo).getByRole("button", { name: "Przyjmij: Kamil T." })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("Lista: zaznaczenie, „Ustaw pion”, „Zmień koordynatora” i „Headowie pionów” bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-structure");
    render(<HrStructurePreviewPage />);
    await user.click(await screen.findByRole("button", { name: "Headowie pionów" }));
    expect(await screen.findByRole("dialog", { name: "Headowie pionów" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Anuluj" }));

    await user.click(screen.getByRole("button", { name: "Lista" }));
    await user.click(await screen.findByRole("checkbox", { name: "Zaznacz: Ola Przykładowa" }));
    await user.click(screen.getByRole("checkbox", { name: "Zaznacz: Ewa Makietowa" }));
    // Obie na B2B — „koordynator”, nie „przełożony”.
    await user.click(screen.getByRole("button", { name: "Zmień koordynatora (2)" }));
    const dialog = await screen.findByRole("dialog", { name: "Zmień koordynatora (2)" });
    expect(within(dialog).getByText(/Zmiana działa od razu/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Anuluj" }));

    await user.click(screen.getByRole("button", { name: "Ustaw pion (2)" }));
    expect(await screen.findByRole("dialog", { name: "Ustaw pion (2)" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("Kadry bez Płac: drzewo bez formy umowy, kartoteka z konta „do uzupełnienia”", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-structure?state=hr-only");
    render(<HrStructurePreviewPage />);
    expect(await screen.findByTestId("org-card-105")).toBeInTheDocument();
    expect(screen.queryByText(/Zlecenie/)).not.toBeInTheDocument();
    expect(screen.queryByText(/składki od/)).not.toBeInTheDocument();
    // Kacper (kartoteka z konta) w „Liście”: forma i koordynator do uzupełnienia.
    await user.click(screen.getByRole("button", { name: "Lista" }));
    const kacper = (await screen.findByText("Kacper Nowicjusz")).closest("tr") as HTMLElement;
    expect(within(kacper).getByText("uzupełnij")).toBeInTheDocument();
    expect(within(kacper).getByText("koordynator do uzupełnienia")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("Płace: studentka na zleceniu z plakietką „składki od …”", async () => {
    window.history.replaceState({}, "", "/preview/hr-structure");
    render(<HrStructurePreviewPage />);
    expect(await screen.findByText("składki od 07.2027")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("bez kartotek: spokojny pusty stan", async () => {
    window.history.replaceState({}, "", "/preview/hr-structure?state=empty");
    render(<HrStructurePreviewPage />);
    expect(await screen.findByText(/Nikt nie ma jeszcze kartoteki — struktura/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
