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
      "tablica otwartych rekrutacji",
      "tablica bez rekrutacji",
      "tablica — awaria API",
      "rekrutacja otwarta",
      "formularz z błędami",
      "podziękowanie",
      "rekrutacja zamknięta",
      "zamknięta, bez stałego linku",
      "stały link rekrutera",
      "rekruter bez opisu i rekrutacji",
    ]) {
      expect(screen.getByRole("region", { name })).toBeInTheDocument();
    }
    for (const button of screen.getAllByRole("button", { name: /wyślij|dołącz do bazy/ })) {
      fireEvent.click(button);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  }, 20_000);

  it("tablica: karty na /kariera/r/<slug>, pusty stan i awaria osobno", () => {
    render(<CareerPreviewPage />);
    const board = screen.getByRole("region", { name: "tablica otwartych rekrutacji" });
    expect(within(board).getAllByRole("link", { name: /Senior Java Developer/ })[0]).toHaveAttribute(
      "href",
      "/kariera/r/senior-java-developer-7kq2",
    );
    const empty = screen.getByRole("region", { name: "tablica bez rekrutacji" });
    expect(within(empty).getByText("Brak otwartych rekrutacji.")).toBeInTheDocument();
    const down = screen.getByRole("region", { name: "tablica — awaria API" });
    expect(within(down).getByRole("alert")).toBeInTheDocument();
    expect(within(down).queryByText("Brak otwartych rekrutacji.")).toBeNull();
  });

  it("strona rekrutacji: tytuł, parametry, wymagania, proces, bez klienta i stawki", () => {
    render(<CareerPreviewPage />);
    const open = screen.getByRole("region", { name: "rekrutacja otwarta" });
    // Domyślny szablon (Grafit, 28.10.2026): tytuł w jedynym <h1>, fakty w <dl>.
    expect(within(open).getByRole("heading", { level: 1 })).toHaveTextContent("Senior Java Developer");
    const facts = open.querySelector("dl");
    expect(facts).toHaveTextContent("Hybryda");
    expect(facts).toHaveTextContent("2 dni w biurze w tygodniu");
    const requirements = within(open).getByRole("region", { name: "Wymagania" });
    expect(within(requirements).getByText("Java Spring Boot")).toBeInTheDocument();
    const steps = within(open).getByRole("region", { name: "Proces rekrutacji" });
    expect(within(steps).getByText("Rozmowa z Martą")).toBeInTheDocument();
    expect(within(open).getByRole("link", { name: /Nie ten projekt/ })).toHaveAttribute(
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

  it("zamknięta bez stałego linku: lista innych rekrutacji osoby, bez ślepego zaułka", () => {
    render(<CareerPreviewPage />);
    const closed = screen.getByRole("region", { name: "zamknięta, bez stałego linku" });
    expect(within(closed).getByText(/Marta prowadzi teraz inne rekrutacje/)).toBeInTheDocument();
    const list = within(closed).getByRole("region", { name: "Inne otwarte rekrutacje" });
    expect(within(list).getByRole("link", { name: /analityk-biznesowy/ })).toHaveAttribute(
      "href",
      "/kariera/r/analityk-biznesowy-q8m1",
    );
    expect(within(closed).queryByRole("link", { name: /zostaw CV w bazie/ })).toBeNull();
    expect(closed.textContent).not.toMatch(/LinkedIn/);
  });

  it("kroki procesu są w treści na każdej szerokości (bez .kr-desktop-only)", () => {
    render(<CareerPreviewPage />);
    const open = screen.getByRole("region", { name: "rekrutacja otwarta" });
    const steps = within(open).getByRole("region", { name: "Proces rekrutacji" });
    expect(steps.closest(".kr-desktop-only")).toBeNull();
    expect(within(steps).getAllByRole("listitem")).toHaveLength(4);
  });

  it("formularz ma dwie zgody: obowiązkową i dobrowolną", () => {
    render(<CareerPreviewPage />);
    const open = screen.getByRole("region", { name: "rekrutacja otwarta" });
    const required = open.querySelector<HTMLInputElement>('input[name="consent"]');
    const optional = open.querySelector<HTMLInputElement>('input[name="consent_future"]');
    expect(required?.required).toBe(true);
    expect(optional?.required).toBe(false);
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
    expect(within(general).getByRole("link", { name: /DevOps Engineer Azure/ })).toHaveAttribute(
      "href",
      "/kariera/r/devops-engineer-azure-p3x9",
    );
  });

  it("strona rekrutera (makieta 6d): imię bez nazwiska, „O mnie”, kategorie, tablica", () => {
    render(<CareerPreviewPage />);
    const page = screen.getByRole("region", { name: "stały link rekrutera" });
    expect(within(page).getByRole("heading", { level: 1 })).toHaveTextContent(
      "Marta.Rekrutuję w IT.",
    );
    expect(within(page).getByText(/Szukam ludzi do projektów w bankowości/)).toBeInTheDocument();
    const chips = within(page).getByRole("list", { name: "Rekrutuję w obszarach" });
    expect(within(chips).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "development",
      "infra & data",
      "management & delivery",
    ]);
    const job = within(page).getByRole("link", { name: /DevOps Engineer Azure/ });
    // Etykiety sceny przy rekrutacji nie ma od 28.10.2026 (trzy szablony zamiast 12 scen).
    expect(job).not.toHaveTextContent("scena:");
    expect(within(page).getByRole("heading", { level: 2 })).toHaveTextContent(
      "Nic nie pasuje? Zostaw CV u Marty.",
    );
    expect(within(page).getByRole("link", { name: "cd ~/rekrutacje" })).toHaveAttribute(
      "href",
      "/kariera",
    );
    // Formularz do bazy: jedna obowiązkowa zgoda na przyszłe procesy (bez zmian reguł).
    expect(page.querySelector('input[name="consent"]')).not.toBeNull();
    expect(page.querySelector('input[name="consent_future"]')).toBeNull();
  });

  it("strona rekrutera bez opisu i rekrutacji: zdanie zamiast pustej listy", () => {
    render(<CareerPreviewPage />);
    const page = screen.getByRole("region", { name: "rekruter bez opisu i rekrutacji" });
    expect(within(page).getByText(/teraz nie mam otwartych rekrutacji/)).toBeInTheDocument();
    expect(within(page).queryByRole("list", { name: "Rekrutuję w obszarach" })).toBeNull();
    expect(within(page).getByRole("heading", { level: 2 })).toHaveTextContent(
      "Zostaw CV u Oli.",
    );
  });

  it("harness nie używa react-query ani API (strażnik źródła)", () => {
    const src = readFileSync(join(process.cwd(), "src/app/preview/kariera/page.tsx"), "utf8");
    expect(src).not.toMatch(/useQuery|@\/lib\/api["']|fetch\(/);
  });
});
