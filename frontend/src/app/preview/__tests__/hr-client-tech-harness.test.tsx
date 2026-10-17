/**
 * `/preview/hr-client-tech` (makieta 10 „Ludzi w NEXUSIE”): prawdziwa zakładka
 * „Technologie” klienta na danych fikcyjnych, ZERO prób żądania — także po
 * filtrze obszaru i otwarciu okna „Dodaj notatkę o stacku”.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-client-tech",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrClientTechPreviewPage from "../hr-client-tech/page";

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

const techRows = () =>
  within(screen.getByRole("table"))
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0].textContent ?? "");

describe("/preview/hr-client-tech", () => {
  it("mapa z czterech źródeł, filtr obszaru i notatka o stacku bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-client-tech");
    render(<HrClientTechPreviewPage />);

    expect(await screen.findByRole("heading", { name: "Bank Przykładowy" })).toBeInTheDocument();
    expect(useAuthStore.getState().user?.role).toBe("delivery_lead");
    expect(techRows()).toHaveLength(7);
    const java = screen.getByRole("row", { name: /Java 17/ });
    expect(within(java).getByTitle("Rozmowy (karty technologiczne): 4")).toBeInTheDocument();
    expect(within(java).getByTitle("Rekrutacje klienta: 6")).toBeInTheDocument();
    expect(within(java).getByTitle("Nasi konsultanci: 5")).toBeInTheDocument();
    expect(within(java).getByTitle("Notatki o stacku: 1")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Klient zatrudnia" })).toBeInTheDocument();
    expect(screen.getByText("Java, QA")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Do przepięcia" }).nextSibling).toHaveTextContent("2");
    expect(screen.getByRole("link", { name: "Java Developer (Płatności)" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Kredyty" }));
    expect(techRows().map((name) => name.split("„")[0])).toEqual([
      "Java 17",
      "Spring Boot",
      "Angular",
    ]);

    await user.click(screen.getByRole("button", { name: "Dodaj notatkę o stacku" }));
    expect(await screen.findByRole("dialog", { name: "Notatka o stacku" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
