/**
 * `/preview/hr-client-people` — zakładka klienta „Ludzie i technologie”
 * (22.10.2026) na danych fikcyjnych, ZERO prób żądania: widok „Działy”
 * z paskiem „Do zatwierdzenia”, przełączenie na „Drzewo osób” z panelem
 * osoby i oknem opinii, okno popytu i konto spoza kręgu D11.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-client-people",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrClientPeoplePreviewPage from "../hr-client-people/page";

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

describe("/preview/hr-client-people", () => {
  it("działy, pasek „Do zatwierdzenia”, drzewo osób i okno opinii bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-client-people");
    render(<HrClientPeoplePreviewPage />);

    expect(await screen.findByRole("heading", { name: "Bank Przykładowy" })).toBeInTheDocument();
    expect(useAuthStore.getState().user?.role).toBe("delivery_lead");
    for (const name of ["Dział Data", "Dział Płatności", "Dział Kredyty"]) {
      expect(screen.getByRole("article", { name })).toBeInTheDocument();
    }
    const bar = screen.getByRole("region", { name: "Do zatwierdzenia" });
    expect(within(bar).getByRole("button", { name: "Zatwierdź" })).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Drzewo osób" }));
    const data = await screen.findByRole("region", { name: "Data" });
    expect(within(data).getByText("Michał Konsultantowy")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Prośby o opinię (2)" })).toBeInTheDocument();
    // Propozycje automatu stoją w pasku nad widokami, nie drugi raz nad drzewem.
    expect(screen.queryByText("Propozycje automatu")).toBeNull();

    await user.click(within(data).getByRole("button", { name: /Zenon Dyrektorski/ }));
    const panel = screen.getByRole("complementary", { name: "Osoba: Zenon Dyrektorski" });
    await user.click(within(panel).getByRole("button", { name: "Piotr Menedżerski" }));
    const head = screen.getByRole("complementary", { name: "Osoba: Piotr Menedżerski" });
    await user.click(within(head).getByRole("button", { name: "Zapisz opinię" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Opinia od: Piotr Menedżerski · Bank Przykładowy",
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Jakość pracy — Michał Konsultantowy: 4" }),
    );
    expect(attempted()).toEqual([]);
  });

  it("okno popytu: sekcja „Czego potrzebuje dział?” bez zapytań", async () => {
    window.history.replaceState({}, "", "/preview/hr-client-people?state=popyt");
    render(<HrClientPeoplePreviewPage />);
    const dialog = await screen.findByRole("dialog", {
      name: "Rozmowa z menedżerem · Bank Przykładowy",
    });
    fireEvent.click(within(dialog).getByRole("radio", { name: "Potrzeba potwierdzona" }));
    expect(within(dialog).getByRole("button", { name: "Kafka" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("Finanse: działy z mapy, bez drzewa i bez paska propozycji", async () => {
    window.history.replaceState({}, "", "/preview/hr-client-people?state=finanse");
    render(<HrClientPeoplePreviewPage />);
    expect(await screen.findByRole("article", { name: "Dział Płatności" })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Drzewo osób" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Do zatwierdzenia" })).toBeNull();
    expect(attempted()).toEqual([]);
  });
});
