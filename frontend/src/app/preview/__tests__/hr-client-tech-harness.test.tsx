/**
 * `/preview/hr-client-tech` (makieta 10 „Ludzi w NEXUSIE” i makieta 8 etapu 2):
 * prawdziwa zakładka „Technologie” klienta na danych fikcyjnych — działy
 * z menedżerem, „Nasi / w bazie”, „Luki do dopytania” — ZERO prób żądania,
 * także po filtrze działu i otwarciu okna „Dodaj notatkę o stacku”.
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
  within(screen.getByRole("table", { name: "Wszystkie technologie klienta" }))
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
    const java = within(
      screen.getByRole("table", { name: "Wszystkie technologie klienta" }),
    ).getByRole("row", { name: /Java 17/ });
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

  it("działy z menedżerem z drzewa, „Nasi / w bazie” z linkiem i luki do dopytania", async () => {
    window.history.replaceState({}, "", "/preview/hr-client-tech");
    render(<HrClientTechPreviewPage />);

    const departments = await screen.findByRole("table", { name: "Technologie po działach" });
    const rows = within(departments).getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByRole("cell")[0].textContent)).toEqual([
      "CI/CD i chmurabrak źródła od 18 miesięcy",
      "Data",
      "Kredyty",
      "Płatności",
    ]);
    const payments = rows[3];
    expect(within(payments).getByText("Michał Rogalski-Przykładowy")).toBeInTheDocument();
    expect(
      within(within(payments).getByRole("list", { name: "Technologie: Płatności" })).getByText(
        "Kafka",
      ),
    ).toBeInTheDocument();
    const base = within(payments).getByRole("link", { name: "212" });
    const href = new URL(base.getAttribute("href") ?? "", "http://localhost");
    expect(href.pathname).toBe("/candidates");
    expect(href.searchParams.get("skills_q")).toBe('"Java 17" AND "Spring Boot"');
    expect(within(rows[2]).getByText("nie wskazano")).toBeInTheDocument();
    // Dział bez źródła: bez technologii i bez liczby „w bazie”.
    expect(within(rows[0]).getAllByText("—")).toHaveLength(2);

    const gaps = screen.getByRole("list", { name: "Luki do dopytania" });
    const items = within(gaps)
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(items[0]).toBe("CI/CD i chmura brak źródła od 18 miesięcy");
    expect(items[1]).toBe("Płatności nie wiemy, komu podlega Michał R.");
    expect(items[2]).toMatch(/^Azure Data Factory znane tylko z rozmowy z konsultantem z \d{2}\.\d{4}$/);
    expect(attempted()).toEqual([]);
  });
});
