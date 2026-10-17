/**
 * `/preview/hr-structure` (etap 2, „Ludzie → Struktura”): prawdziwa Struktura
 * na danych fikcyjnych, ZERO prób żądania — także po zaznaczeniu osób
 * i otwarciu okien zmiany koordynatora, pionu i headów pionów.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-structure",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrStructurePreviewPage from "../hr-structure/page";

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

describe("/preview/hr-structure", () => {
  it("Kadry: piony, odchodząca z podwładnymi, podpowiedzi i okna bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-structure");
    render(<HrStructurePreviewPage />);

    expect(await screen.findByRole("heading", { name: /^Front office/ })).toHaveTextContent(
      "head: Kamil Testowy",
    );
    expect(screen.getByRole("heading", { name: /^Back office/ })).toHaveTextContent(
      "head: Piotr Finansowy",
    );
    expect(screen.getByRole("heading", { name: /^Bez pionu/ })).toBeInTheDocument();
    expect(screen.getByText(/Marta Fikcyjna kończy pracę/)).toHaveTextContent(
      "przejmie ich Kamil Testowy",
    );
    expect(screen.getByText(/Podpowiedź: koordynator = Kamil Testowy/)).toBeInTheDocument();
    expect(screen.getByText(/Microsoft 365: Kamil Testowy/)).toBeInTheDocument();
    // Studentka na zleceniu (D8): forma i plakietka „składki od …”.
    expect(screen.getByText(/Zlecenie · student/)).toBeInTheDocument();
    expect(screen.getByText("składki od 07.2027")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Struktura" })).toHaveAttribute("aria-selected", "true");

    await user.click(screen.getByRole("button", { name: "Headowie pionów" }));
    expect(await screen.findByRole("dialog", { name: "Headowie pionów" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Anuluj" }));

    await user.click(screen.getByRole("checkbox", { name: "Zaznacz: Ola Przykładowa" }));
    await user.click(screen.getByRole("checkbox", { name: "Zaznacz: Ewa Makietowa" }));
    // Obie na B2B — „koordynator”, nie „przełożony”.
    await user.click(screen.getByRole("button", { name: "Zmień koordynatora (2)" }));
    const dialog = await screen.findByRole("dialog", { name: "Zmień koordynatora (2)" });
    expect(within(dialog).getByText(/Zmiana działa od razu/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Anuluj" }));

    await user.click(screen.getByRole("button", { name: "Ustaw pion (2)" }));
    expect(await screen.findByRole("dialog", { name: "Ustaw pion (2)" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("bez kartotek: spokojny pusty stan", async () => {
    window.history.replaceState({}, "", "/preview/hr-structure?state=empty");
    render(<HrStructurePreviewPage />);
    expect(await screen.findByText(/Nikt nie ma jeszcze kartoteki/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
