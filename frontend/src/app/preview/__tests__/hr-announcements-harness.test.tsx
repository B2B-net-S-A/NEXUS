/**
 * `/preview/hr-announcements` (makiety M7–M8, O12): prawdziwa zakładka
 * „Komunikaty” na danych fikcyjnych, ZERO prób żądania — także po „Pokaż
 * listę” i przy edytorze nowego komunikatu.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-announcements",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrAnnouncementsPreviewPage from "../hr-announcements/page";
import { PENDING_ID, SENT_ID } from "../hr-announcements/fixtures";

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

describe("/preview/hr-announcements", () => {
  it("head back office: komunikat czeka na jego zatwierdzenie", async () => {
    window.history.replaceState({}, "", `/preview/hr-announcements?state=head&announcement=${PENDING_ID}`);
    render(<HrAnnouncementsPreviewPage />);

    const card = await screen.findByRole("region", { name: "Od listopada faktury do 5. dnia miesiąca" });
    expect(within(card).getByText("czeka na Twoje zatwierdzenie")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("czeka na Twoje zatwierdzenie")).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Zatwierdź" })).toBeEnabled();
    expect(within(card).getByRole("button", { name: "Zwróć do poprawy" })).toBeInTheDocument();
    expect(screen.getByText(/Czeka na Ciebie: 1 komunikat/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("raport wysłanego: wysłane, odbite, wypisy i odpowiedzi; lista bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", `/preview/hr-announcements?state=report&announcement=${SENT_ID}`);
    render(<HrAnnouncementsPreviewPage />);

    const card = await screen.findByRole("region", { name: "Spotkanie konsultantów 28.11" });
    expect(within(card).getByText(/symulacja, nic nie wyszło/)).toBeInTheDocument();
    expect(within(card).getByText(/opiekun dostał powiadomienie: popraw e-mail/)).toBeInTheDocument();
    expect(within(card).getByText("5 · nie dostali")).toBeInTheDocument();
    expect(within(card).getByText("23 sprawy w administracja@")).toBeInTheDocument();
    expect(within(card).getByText(/NEXUS nie śledzi otwarć maili/)).toBeInTheDocument();

    await user.click(within(card).getByRole("button", { name: "Pokaż listę" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Michał Konsultantowy");
    expect(attempted()).toEqual([]);
  });

  it("nowy komunikat: 124 dostanie, powyżej 20 osób idzie do zatwierdzenia", async () => {
    window.history.replaceState({}, "", "/preview/hr-announcements?state=new&announcement=new");
    render(<HrAnnouncementsPreviewPage />);

    expect(await screen.findByRole("heading", { name: "Nowy komunikat" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Wszyscy aktywni konsultanci · 126/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("124")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wyślij do zatwierdzenia" })).toBeDisabled();
    const checks = screen.getByRole("region", { name: "Przed wysyłką" });
    expect(within(checks).getByText(/powyżej 20 osób/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("wysyłka wyłączona: zakładka mówi to wprost", async () => {
    window.history.replaceState({}, "", "/preview/hr-announcements?state=off");
    render(<HrAnnouncementsPreviewPage />);
    expect(
      await screen.findByText(/Wysyłka do konsultantów jest wyłączona\. Szkice, podgląd/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Nowy komunikat" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
