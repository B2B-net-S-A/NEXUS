/**
 * `/preview/hr-person` (makieta 6 „Ludzi w NEXUSIE”): prawdziwa kartoteka
 * osoby z sekcjami Płac, wejścia/odejścia i sprzętu na danych fikcyjnych,
 * ZERO prób żądania — także po otwarciu okna „Nowa stawka od…” i „Nowa premia”.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-person",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrPersonPreviewPage from "../hr-person/page";

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

const heading = () => screen.findByRole("heading", { level: 1, name: /Ola Przykładowa/ });

describe("/preview/hr-person", () => {
  it("Kadry i Płace: pełna kartoteka, stawki, premie, odejście i sprzęt", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-person");
    render(<HrPersonPreviewPage />);

    expect(await heading()).toBeInTheDocument();
    expect(screen.getByText(/przełożony:/)).toHaveTextContent("Marta Fikcyjna");
    expect(screen.getByRole("button", { name: /Edytuj kartotekę/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zmień pulę" })).toBeInTheDocument();
    expect(screen.getByText("Aktualna stawka:")).toHaveTextContent(/120,00\szł/);
    expect(screen.getByText("od 01.07.2026", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Rozpocznij odejście" })).toHaveAttribute(
      "href",
      "/people/101/offboarding",
    );
    const equipment = screen.getByRole("region", { name: "Sprzęt" });
    expect(within(equipment).getAllByRole("listitem")).toHaveLength(4);
    expect(within(equipment).getByText(/Laptop Dell Latitude 5520 \(153\)/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();

    await user.click(screen.getByRole("button", { name: /Nowa stawka od/ }));
    expect(
      await screen.findByRole("dialog", { name: "Nowa stawka · Ola Przykładowa" }),
    ).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("przełożona: premie bez stawek, bez sprzętu i bez zakładania odejścia", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-person?as=manager");
    render(<HrPersonPreviewPage />);

    expect(await heading()).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Płace" })).toBeInTheDocument();
    expect(screen.queryByText("Aktualna stawka:")).toBeNull();
    expect(screen.queryByRole("button", { name: /Edytuj kartotekę/ })).toBeNull();
    expect(screen.queryByRole("link", { name: "Rozpocznij odejście" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Sprzęt" })).toBeNull();
    expect(screen.getByText("Bez sprawy wejścia ani odejścia.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Nowa premia/ }));
    expect(await screen.findByRole("dialog", { name: "Nowa premia" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("kolega z zespołu: wizytówka, sekcje modułów schowane po odmowie serwera", async () => {
    window.history.replaceState({}, "", "/preview/hr-person?as=colleague");
    render(<HrPersonPreviewPage />);

    expect(await heading()).toBeInTheDocument();
    expect(
      screen.getByText("Pełną kartotekę widzą ta osoba, jej przełożony i Kadry."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Płace" })).toBeNull();
    expect(screen.queryByText("Wejście i odejście")).toBeNull();
    expect(screen.queryByText(/Nie udało się/)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });
});
