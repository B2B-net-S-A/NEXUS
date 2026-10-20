/**
 * `/preview/hr-consents` (zgody na wydatki i premie poza umową, 20.10.2026):
 * prawdziwe komponenty na danych fikcyjnych, ZERO prób żądania — także po
 * otwarciu okna decyzji z linku maila i formularza „Poproś o zgodę”.
 */
import { render, screen, within } from "@testing-library/react";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-consents",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrConsentsPreviewPage from "../hr-consents/page";

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

describe("/preview/hr-consents", () => {
  it("zatwierdzający: premia z liczbami „NEXUS sprawdził” i zdanie o Płacach", async () => {
    window.history.replaceState({}, "", "/preview/hr-consents?state=inbox&tab=consents");
    render(<HrConsentsPreviewPage />);
    expect(await screen.findByText(/z umowy i reguł 9400 zł/)).toBeInTheDocument();
    expect(screen.getByText(/trafi do Płac jako przyznana/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Zatwierdź inną kwotę/ })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("link z maila otwiera okno decyzji wskazanej zgody", async () => {
    window.history.replaceState(
      {},
      "",
      "/preview/hr-consents?state=inbox&tab=consents&request=2&decide=approve",
    );
    render(<HrConsentsPreviewPage />);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Zatwierdzić zgodę?")).toBeInTheDocument();
    expect(within(dialog).getByText(/Gdańsk/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("przełożona ponad próg: „Popieram” i zdanie o przekazaniu", async () => {
    window.history.replaceState({}, "", "/preview/hr-consents?state=supervisor&tab=consents");
    render(<HrConsentsPreviewPage />);
    expect(await screen.findByRole("button", { name: "Popieram" })).toBeInTheDocument();
    expect(screen.getByText(/Po poparciu/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("moje zgody: pytanie od decydującego i przebieg", async () => {
    window.history.replaceState({}, "", "/preview/hr-consents?state=mine");
    render(<HrConsentsPreviewPage />);
    expect(await screen.findByRole("list", { name: "Przebieg zgody" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Popraw i wyślij" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("formularz „Poproś o zgodę” bez danych nie pyta serwera", async () => {
    window.history.replaceState({}, "", "/preview/hr-consents?state=form&new=1");
    render(<HrConsentsPreviewPage />);
    expect(await screen.findByText("Na co potrzebujesz zgody?")).toBeInTheDocument();
    expect(screen.getByText(/pokażę, kto zdecyduje/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
