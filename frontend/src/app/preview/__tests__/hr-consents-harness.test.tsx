/**
 * `/preview/hr-consents` (zgody na wydatki i premie poza umową, 20.10.2026):
 * prawdziwe komponenty na danych fikcyjnych, ZERO prób żądania — także po
 * otwarciu okna decyzji z linku maila i formularza „Poproś o zgodę”.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    expect(screen.getByText(/Wynagrodzenie dodatkowe trafi do Płac jako przyznane/)).toBeInTheDocument();
    // Premia dla B2B ma podstawę w umowie (0491).
    expect(screen.getByText("§ 6 ust. 2 umowy z 01.03.2025")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Zatwierdź inną kwotę/ })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("„Wszystko”: zgody i urlop w jednej liście, „Zdecydowane” — rozstrzygnięte zgody, bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-consents?state=inbox");
    render(<HrConsentsPreviewPage />);
    const decide = await screen.findByRole("list", { name: "Do decyzji" });
    expect(within(decide).getByRole("button", { name: /^Kamil Testowy/ })).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "Co akceptujesz" })).toBeNull();
    expect(screen.getByRole("region", { name: "Raporty godzin" })).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Zdecydowane" }));
    const decided = screen.getByRole("table", { name: "Zgody — zdecydowane" });
    expect(within(decided).getByText("Kurs negocjacji")).toBeInTheDocument();
    expect(within(decided).getByText("Odrzucona")).toBeInTheDocument();
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

  it("zatwierdzający: dopłata do decyzji nad skrzynką (faktura +18%)", async () => {
    window.history.replaceState({}, "", "/preview/hr-consents?state=inbox&tab=consents");
    render(<HrConsentsPreviewPage />);
    const panel = await screen.findByRole("region", { name: "Dopłaty do decyzji" });
    expect(within(panel).getByText(/Konferencja rekruterów IT/)).toBeInTheDocument();
    expect(within(panel).getByText("216 zł")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Zatwierdź dopłatę" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("moje zgody: rozliczenie — faktura ponad 10% i „Poproś o dopłatę”", async () => {
    window.history.replaceState({}, "", "/preview/hr-consents?state=mine&request=21");
    render(<HrConsentsPreviewPage />);
    const section = await screen.findByRole("region", { name: "Rozliczenie" });
    expect(within(section).getByText("+18% vs zgoda")).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "Poproś o dopłatę" })).toBeInTheDocument();
    expect(within(section).getByText(/Przeciągnij fakturę albo paragon/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("moje zgody: subskrypcja roczna pyta, czy jest dalej potrzebna", async () => {
    window.history.replaceState({}, "", "/preview/hr-consents?state=mine&request=22");
    render(<HrConsentsPreviewPage />);
    const section = await screen.findByRole("region", { name: "Rozliczenie" });
    expect(within(section).getByRole("button", { name: "Dalej potrzebna" })).toBeInTheDocument();
    expect(within(section).getByText(/Odnowienie roczne/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("formularz „Poproś o zgodę” bez danych nie pyta serwera", async () => {
    window.history.replaceState({}, "", "/preview/hr-consents?state=form&new=1");
    render(<HrConsentsPreviewPage />);
    expect(await screen.findByText("Na co potrzebujesz zgody?")).toBeInTheDocument();
    expect(screen.getByText(/pokażę, kto zdecyduje/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("formularz: premia ma pole „Podstawa w umowie”", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-consents?state=form&new=1");
    render(<HrConsentsPreviewPage />);
    expect(screen.queryByLabelText(/Podstawa w umowie/)).toBeNull();
    await user.click(await screen.findByRole("button", { name: /Wynagrodzenie dodatkowe/ }));
    expect(screen.getByLabelText(/Podstawa w umowie/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
