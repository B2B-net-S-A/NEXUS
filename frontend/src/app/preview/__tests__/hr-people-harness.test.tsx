/**
 * `/preview/hr-people` („Ludzie → Katalog” z „Porządkami”, 22.10.2026; lista
 * rozjazdów kartoteka ↔ konto z 19.10.2026): prawdziwy katalog na danych
 * fikcyjnych, ZERO prób żądania — także w panelu „Porządki”, po rozwinięciu
 * listy, w potwierdzeniu „Wyrównaj wg konta” i na schemacie.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-people",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrPeoplePreviewPage from "../hr-people/page";

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

describe("/preview/hr-people", () => {
  it("Kadry: „Porządki” ze strukturą i kontami, potwierdzenie bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-people");
    render(<HrPeoplePreviewPage />);

    // Kadry bez Płac: formy nie widać (19.10.2026) — w kolumnie tylko „uzupełnij”
    // przy kartotece z konta, bez chipów formy.
    expect(await screen.findByText("uzupełnij")).toBeInTheDocument();
    expect(screen.queryByText("B2B")).toBeNull();
    expect(screen.queryByRole("button", { name: /^UoP/ })).toBeNull();
    expect(screen.getByText("koordynator do uzupełnienia")).toBeInTheDocument();
    // Żółtego paska nad katalogiem już nie ma — jest przycisk w nagłówku.
    expect(screen.queryByText(/Do wyrównania/)).toBeNull();

    await user.click(screen.getByRole("button", { name: "Porządki · 10" }));
    const panel = await screen.findByRole("dialog", { name: "Porządki" });
    const structure = within(panel).getByRole("region", { name: "Struktura" });
    expect(within(structure).getByText(/kończy współpracę/)).toBeInTheDocument();
    expect(within(structure).getByRole("button", { name: "Przyjmij z M365" })).toBeInTheDocument();
    const accounts = within(panel).getByRole("region", { name: "Konta i kartoteki" });
    expect(
      within(accounts).getByText(/Marta Fikcyjna: konto wyłączone · 2 osoby w zespole/),
    ).toBeInTheDocument();
    expect(within(accounts).getByText("Kacper Nowicjusz: forma i koordynator")).toBeInTheDocument();
    await user.click(within(accounts).getByRole("button", { name: /Przejrzyj po kolei/ }));
    expect(within(accounts).getByText("Konto wyłączone")).toBeInTheDocument();
    expect(within(accounts).getByText("Konto bez kartoteki")).toBeInTheDocument();

    await user.click(within(accounts).getByRole("button", { name: "Wyrównaj wg konta" }));
    expect(
      await screen.findByRole("dialog", { name: "Wyrównać kartoteki według kont?" }),
    ).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("Kadry: „Schemat” z adresu, bez zapytań", async () => {
    window.history.replaceState({}, "", "/preview/hr-people?view=schemat");
    render(<HrPeoplePreviewPage />);
    expect(await screen.findByRole("button", { name: "Schemat" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByTestId("org-card-105")).toHaveTextContent("Marta Fikcyjna");
    expect(attempted()).toEqual([]);
  });

  it("Finanse: forma jako pigułka i chipy formy, kolumna „Dziś”", async () => {
    window.history.replaceState({}, "", "/preview/hr-people?as=finance");
    render(<HrPeoplePreviewPage />);
    expect(await screen.findByRole("columnheader", { name: "Forma" })).toBeInTheDocument();
    // Finanse: „Porządki” tylko z kontami (3 rozjazdy + Kacper), bez schematu.
    expect(screen.getByRole("button", { name: "Porządki · 4" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Widok katalogu" })).toBeNull();
    expect(screen.getAllByText("Zlecenie · student").length).toBe(2);
    expect(screen.getByRole("button", { name: /^UoP/ })).toBeInTheDocument();
    expect(screen.getAllByText(/^nieobecność do .* · zastępuje Ola P\.$/).length).toBe(2);
    expect(screen.getByText("wyjazd")).toBeInTheDocument();
    expect(screen.getByText("odchodzi 30.11")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("rekruterka: wizytówki bez formy i bez listy rozjazdów", async () => {
    window.history.replaceState({}, "", "/preview/hr-people?as=colleague");
    render(<HrPeoplePreviewPage />);
    expect(await screen.findByText("Ola Przykładowa")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Porządki/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Forma" })).toBeNull();
    // Zawsze „nieobecność”, nie „przerwa” ani „urlop” (decyzja Artura 21.10.2026).
    expect(screen.getAllByText(/^nieobecność do /).length).toBeGreaterThan(0);
    expect(screen.queryByText(/^przerwa do /)).toBeNull();
    expect(attempted()).toEqual([]);
  });
});
