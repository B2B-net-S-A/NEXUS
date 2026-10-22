/**
 * `/preview/hr-client-tech` (makieta 10 „Ludzi w NEXUSIE” i makieta 8 etapu 2):
 * prawdziwa zakładka „Technologie” klienta na danych fikcyjnych — działy
 * z menedżerem, „Nasi / w bazie”, „Luki do dopytania” — ZERO prób żądania,
 * także po filtrze działu i otwarciu okna „Dodaj notatkę o stacku”.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
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

const heatRows = () =>
  within(screen.getByRole("table", { name: "Technologie klienta po działach" }))
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getByRole("rowheader").textContent ?? "");

describe("/preview/hr-client-tech", () => {
  it("mapa cieplna z czterech źródeł, boczne karty i notatka o stacku bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-client-tech");
    render(<HrClientTechPreviewPage />);

    expect(await screen.findByRole("heading", { name: "Bank Przykładowy" })).toBeInTheDocument();
    expect(useAuthStore.getState().user?.role).toBe("delivery_lead");
    expect(heatRows()).toHaveLength(7);
    const table = screen.getByRole("table", { name: "Technologie klienta po działach" });
    const java = within(table).getByRole("row", { name: /Java 17/ });
    expect(within(java).getByRole("rowheader")).toHaveTextContent("„musi” w 3 rekrut.");
    expect(
      within(java).getByTitle("Kredyty · Java 17: 1 karta, 2 rekrutacje"),
    ).toHaveTextContent("TR");
    expect(
      within(java).getByTitle(
        "Płatności · Java 17: 3 karty, 4 rekrutacje, 3 konsultantów · 1 otwarta rekrutacja",
      ),
    ).toHaveClass("ring-warning");
    expect(screen.getByRole("heading", { name: "Klient zatrudnia" })).toBeInTheDocument();
    expect(screen.getByText("QA")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Kolejka przepięć →" })).toBeInTheDocument();
    const jobs = screen.getByRole("link", { name: "Java Developer" }).closest("li");
    expect(jobs).toHaveTextContent("Płatności");
    expect(screen.queryByRole("alert")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Dodaj notatkę o stacku" }));
    expect(await screen.findByRole("dialog", { name: "Notatka o stacku" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("nagłówki działów z menedżerem z drzewa, „Nasi / w bazie” z linkiem i luki do dopytania", async () => {
    window.history.replaceState({}, "", "/preview/hr-client-tech");
    render(<HrClientTechPreviewPage />);

    const table = await screen.findByRole("table", { name: "Technologie klienta po działach" });
    // CI/CD nie ma żadnego źródła — schowany, dopóki ktoś nie pokaże wszystkich (20.10.2026).
    expect(within(table).queryByText("CI/CD i chmura")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż wszystkie działy (4)" }));
    const heads = within(table).getAllByRole("columnheader");
    const [cicd, data, credits, payments] = heads.slice(1, 5);
    expect(cicd).toHaveTextContent("CI/CD i chmura");
    expect(cicd).toHaveTextContent("brak źródła 18 mies.");
    expect(cicd).toHaveTextContent("w bazie —");
    expect(data).toHaveTextContent("Piotr Menedżerski");
    expect(credits).toHaveTextContent("menedżer: —");
    expect(within(payments).getByText("Michał Rogalski-Przykładowy")).toBeInTheDocument();
    expect(payments).toHaveTextContent("nasi 3");
    const base = within(payments).getByRole("link", { name: "w bazie 212" });
    const href = new URL(base.getAttribute("href") ?? "", "http://localhost");
    expect(href.pathname).toBe("/candidates");
    expect(href.searchParams.get("skills_q")).toBe('"Java 17" AND "Spring Boot"');

    const gaps = screen.getByRole("list", { name: "Luki do dopytania" });
    const items = within(gaps)
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(items[0]).toBe("CI/CD i chmura — brak źródła od 18 miesięcy · pytanie w najbliższej rozmowieDopisz notatkę o stacku");
    expect(items[1]).toBe("Płatności — nie wiemy, komu podlega Michał R. · pytanie w najbliższej rozmowieUstaw w „Drzewie osób”");
    expect(items[2]).toMatch(/^Azure Data Factory — znane tylko z rozmowy z konsultantem z \d{2}\.\d{4} · pytanie w najbliższej rozmowieDopisz/);
    expect(attempted()).toEqual([]);
  });
});
