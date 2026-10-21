/**
 * `/preview/hr-people` („Ludzie → Katalog” z listą rozjazdów kartoteka ↔ konto,
 * 19.10.2026): prawdziwy katalog na danych fikcyjnych, ZERO prób żądania —
 * także po rozwinięciu listy i otwarciu potwierdzenia „Wyrównaj wg konta”.
 */
import { render, screen } from "@testing-library/react";
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
  it("Kadry: pasek „Do wyrównania” z nazwanymi pozycjami i potwierdzenie bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-people");
    render(<HrPeoplePreviewPage />);

    expect(await screen.findByText(/Do wyrównania · 4/)).toBeInTheDocument();
    expect(screen.getByText(/Marta Fikcyjna: konto wyłączone · 2 osoby w zespole/)).toBeInTheDocument();
    expect(screen.getByText("Kacper Nowicjusz: forma i koordynator")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Przejrzyj po kolei/ }));
    expect(screen.getByText("Konto wyłączone")).toBeInTheDocument();
    expect(screen.getByText("Konto bez kartoteki")).toBeInTheDocument();
    // Kadry bez Płac: formy nie widać (19.10.2026) — w kolumnie tylko „uzupełnij”
    // przy kartotece z konta, bez chipów formy.
    expect(screen.getByText("uzupełnij")).toBeInTheDocument();
    expect(screen.queryByText("B2B")).toBeNull();
    expect(screen.queryByRole("button", { name: /^UoP/ })).toBeNull();
    expect(screen.getByText("koordynator do uzupełnienia")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Wyrównaj wg konta" }));
    expect(
      await screen.findByRole("dialog", { name: "Wyrównać kartoteki według kont?" }),
    ).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("Finanse: forma jako pigułka i chipy formy, kolumna „Dziś”", async () => {
    window.history.replaceState({}, "", "/preview/hr-people?as=finance");
    render(<HrPeoplePreviewPage />);
    expect(await screen.findByRole("columnheader", { name: "Forma" })).toBeInTheDocument();
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
    expect(screen.queryByText(/Do wyrównania/)).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Forma" })).toBeNull();
    // Zawsze „nieobecność”, nie „przerwa” ani „urlop” (decyzja Artura 21.10.2026).
    expect(screen.getAllByText(/^nieobecność do /).length).toBeGreaterThan(0);
    expect(screen.queryByText(/^przerwa do /)).toBeNull();
    expect(attempted()).toEqual([]);
  });
});
