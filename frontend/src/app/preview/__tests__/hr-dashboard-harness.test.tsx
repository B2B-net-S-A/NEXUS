/**
 * `/preview/hr-dashboard` (makieta 1 „Ludzi w NEXUSIE”): prawdziwe kafelki
 * „Ludzi” i przycisk „Nieobecni dziś” na danych fikcyjnych, ZERO prób żądania —
 * także po otwarciu okienka z paska.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-dashboard",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrDashboardPreviewPage from "../hr-dashboard/page";

// Cała strona z prawdziwymi ekranami — na obciążonej maszynie 5 s nie wystarcza.
vi.setConfig({ testTimeout: 20_000 });

const attempts = vi.spyOn(Axios.prototype, "request");
const attempted = () =>
  attempts.mock.calls.map(([config]) => {
    const { method, url } = config as { method?: string; url?: string };
    return `${(method ?? "get").toUpperCase()} ${url}`;
  });

function open(search: string) {
  window.history.replaceState({}, "", `/preview/hr-dashboard${search}`);
  render(<HrDashboardPreviewPage />);
}

afterEach(() => {
  attempts.mockClear();
  window.history.replaceState({}, "", "/");
  useAuthStore.setState({ user: null, realUser: null });
});

describe("/preview/hr-dashboard", () => {
  it("rekruterka w zastępstwie: praca Kamila, Mój czas i okienko nieobecnych", async () => {
    const user = userEvent.setup();
    open("");

    const cover = await screen.findByRole("region", { name: "Zastępstwo: Kamil Testowy" });
    expect(cover).toHaveTextContent("3rekrutacje");
    expect(cover).toHaveTextContent("2rozmowy u klienta");
    const myTime = screen.getByRole("region", { name: "Mój czas" });
    expect(await within(myTime).findByText("zostało")).toBeInTheDocument();
    expect(within(myTime).queryByRole("alert")).toBeNull();

    const panel = screen.getByRole("dialog", { name: "Nieobecni dziś — okienko" });
    expect(panel).toHaveTextContent("zastępujesz Ty");
    expect(within(panel).getByText("zastępca nieobecny")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Nieobecni dziś: 3 osoby" }));
    expect(await screen.findAllByText("Kalendarz zespołu")).toHaveLength(2);
    expect(attempted()).toEqual([]);
  });

  it("plakietka i wzmianka: kropka przy DL, „@Kamil” podpowiada zastępcę", async () => {
    open("");

    const list = await screen.findByRole("region", { name: "Lista rekrutacji — kolumna Rekruter" });
    const dl = within(list).getAllByTestId("job-delivery-lead-absence");
    // Kamil (DL dwóch rekrutacji) i Adam są dziś nieobecni.
    expect(dl).toHaveLength(3);
    expect(dl[0]).toHaveTextContent("Kamil Testowy:");
    expect(within(list).getAllByTestId("job-recruiter-absence")).toHaveLength(1);

    const field = screen.getByLabelText("Notatka do karty") as HTMLTextAreaElement;
    fireEvent.change(field, { target: { value: "@Kam", selectionStart: 4 } });
    expect(await screen.findByTestId("mention-absence")).toHaveTextContent("nieobecność do");
    fireEvent.keyDown(field, { key: "Enter" });
    expect(await screen.findByTestId("mention-substitute-hint")).toHaveTextContent(
      "Oznaczyć też zastępcę (Ola Przykładowa)?",
    );
    expect(attempted()).toEqual([]);
  });

  it("przełożona: Do akceptacji i ostrzeżenie o nieobecnym zastępcy", async () => {
    open("?as=manager");
    const approvals = await screen.findByRole("region", { name: "Do akceptacji" });
    expect(approvals).toHaveTextContent("4wnioski lub timesheety czekają na Twoją decyzję");
    expect(
      screen.getByText(/Adam Wzorcowy — zastępca \(Kamil Testowy\) też ma dziś nieobecność/),
    ).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("recepcja: Sprzęt do zrobienia z zadaniem po terminie", async () => {
    open("?as=reception");
    const tasks = await screen.findByRole("region", { name: "Sprzęt do zrobienia" });
    expect(tasks).toHaveTextContent("5 otwartych zadań");
    expect(tasks).toHaveTextContent("1 po terminie");
    expect(within(tasks).queryByText("Brak dostępu")).toBeNull();
    expect(attempted()).toEqual([]);
  });
});
