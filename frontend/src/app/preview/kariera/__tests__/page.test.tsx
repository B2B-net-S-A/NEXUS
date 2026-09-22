/**
 * Harness `/preview/kariera` jest publiczny i ma robić ZERO zapytań — renderuje
 * prawdziwe komponenty strony kariery na mockach. Ten sam test sprawdza, że
 * widoki pokazują to, co obiecują makiety (stan zamknięty, podziękowanie,
 * błędy formularza, lista rekrutera) i że linki idą trasami `/kariera/*`.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/career/fonts", () => ({
  careerDisplayFont: { variable: "font-display" },
  careerMonoFont: { variable: "font-mono" },
}));

import CareerPreviewPage from "@/app/preview/kariera/page";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("/preview/kariera", () => {
  it("renderuje wszystkie stany bez żadnego zapytania — także po kliknięciu „wyślij”", () => {
    render(<CareerPreviewPage />);
    for (const name of [
      "rekrutacja otwarta",
      "formularz z błędami",
      "podziękowanie",
      "rekrutacja zamknięta",
      "stały link rekrutera",
    ]) {
      expect(screen.getByRole("region", { name })).toBeInTheDocument();
    }
    for (const button of screen.getAllByRole("button", { name: /wyślij|dołącz do bazy/ })) {
      fireEvent.click(button);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  }, 20_000);

  it("strona rekrutacji: tytuł, parametry, wymagania, proces, bez klienta i stawki", () => {
    render(<CareerPreviewPage />);
    const open = screen.getByRole("region", { name: "rekrutacja otwarta" });
    expect(within(open).getByRole("heading", { level: 1 })).toHaveTextContent("Senior JavaDeveloper.");
    expect(within(open).getByText("[hybryda · 2 dni]")).toBeInTheDocument();
    expect(within(open).getByText("[10.2026 · 12+ mies.]")).toBeInTheDocument();
    expect(within(open).getByText("java_spring_boot")).toBeInTheDocument();
    expect(within(open).getByText("rozmowa z Martą")).toBeInTheDocument();
    expect(within(open).getByRole("link", { name: /cd ~\/marta-n/ })).toHaveAttribute(
      "href",
      "/kariera/p/marta-n",
    );
    expect(within(open).getByRole("link", { name: "Klauzula informacyjna" })).toHaveAttribute(
      "href",
      "/kariera/rodo",
    );
    expect(open.textContent).not.toMatch(/zł\/h\s*\d|PLN\s*\d/);
  });

  it("stan zamknięty odsyła do stałego linku rekrutera", () => {
    render(<CareerPreviewPage />);
    const closed = screen.getByRole("region", { name: "rekrutacja zamknięta" });
    expect(within(closed).getByText("ZAMKNIĘTA")).toBeInTheDocument();
    expect(within(closed).getByRole("link", { name: /zostaw CV w bazie/ })).toHaveAttribute(
      "href",
      "/kariera/p/marta-n",
    );
    expect(within(closed).queryByRole("form")).toBeNull();
  });

  it("formularz z błędami: podsumowanie role=alert i wpisane dane", () => {
    render(<CareerPreviewPage />);
    const errors = screen.getByRole("region", { name: "formularz z błędami" });
    const alert = within(errors).getByRole("alert");
    expect(alert).toHaveTextContent("popraw 3 pola:");
    expect(alert).toHaveTextContent("e-mail · cv · zgoda");
    expect(within(errors).getByDisplayValue("jan@firma-.pl")).toHaveAttribute("aria-invalid", "true");
  });

  it("stały link rekrutera linkuje do rekrutacji", () => {
    render(<CareerPreviewPage />);
    const general = screen.getByRole("region", { name: "stały link rekrutera" });
    expect(within(general).getByRole("link", { name: /devops-engineer-azure/ })).toHaveAttribute(
      "href",
      "/kariera/r/devops-engineer-azure-p3x9",
    );
  });

  it("harness nie używa react-query ani API (strażnik źródła)", () => {
    const src = readFileSync(join(process.cwd(), "src/app/preview/kariera/page.tsx"), "utf8");
    expect(src).not.toMatch(/useQuery|@\/lib\/api["']|fetch\(/);
  });
});
