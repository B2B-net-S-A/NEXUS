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
  it("Kadry: rozjazdy z kontami, liczniki i potwierdzenie bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-people");
    render(<HrPeoplePreviewPage />);

    await user.click(
      await screen.findByRole("button", { name: "Rozjazdy z kontami NEXUSA: 3" }),
    );
    expect(screen.getByText("Konto wyłączone")).toBeInTheDocument();
    expect(screen.getByText("Konto bez kartoteki")).toBeInTheDocument();
    expect(screen.getByText(/2 osoby pod sobą/)).toBeInTheDocument();
    expect(screen.getByText("Forma do uzupełnienia: 1")).toBeInTheDocument();
    expect(screen.getAllByText("do uzupełnienia").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Wyrównaj wg konta" }));
    expect(
      await screen.findByRole("dialog", { name: "Wyrównać kartoteki według kont?" }),
    ).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("rekruterka: wizytówki, bez listy rozjazdów", async () => {
    window.history.replaceState({}, "", "/preview/hr-people?as=colleague");
    render(<HrPeoplePreviewPage />);
    expect(await screen.findByText("Ola Przykładowa")).toBeInTheDocument();
    expect(screen.queryByText(/Rozjazdy z kontami NEXUSA/)).not.toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
