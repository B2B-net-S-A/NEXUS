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
      "podziękowanie",
      "rekrutacja zamknięta",
      "zamknięta, bez tablicy",
      "oferta — formularz z błędami",
      "grafika posta",
      "stały link rekrutera",
      "rekruter bez opisu i rekrutacji",
      "ładowanie strony",
    ]) {
      expect(screen.getByRole("region", { name })).toBeInTheDocument();
    }
    for (const button of screen.getAllByRole("button", { name: /wyślij|dołącz do bazy/i })) {
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
    expect(within(empty).getByText("Brak otwartych rekrutacji")).toBeInTheDocument();
    const down = screen.getByRole("region", { name: "tablica — awaria API" });
    expect(within(down).getByRole("alert")).toBeInTheDocument();
    expect(within(down).queryByText("Brak otwartych rekrutacji")).toBeNull();
  });

  it("strona rekrutacji: tytuł, parametry, wymagania, proces, bez klienta i stawki", () => {
    render(<CareerPreviewPage />);
    const open = screen.getByRole("region", { name: "rekrutacja otwarta" });
    // Jeden szablon nowej strony (23–24.11.2026): tytuł w jedynym <h1>, fakty w <dl>.
    expect(within(open).getByRole("heading", { level: 1 })).toHaveTextContent("Senior Java Developer");
    const facts = open.querySelector("dl");
    expect(facts).toHaveTextContent("Hybryda");
    expect(facts).toHaveTextContent("2 dni w biurze w tygodniu");
    const requirements = within(open).getByRole("complementary", { name: "Wymagania" });
    expect(within(requirements).getByText("Java Spring Boot")).toBeInTheDocument();
    const steps = within(open).getByRole("region", { name: "Proces rekrutacji" });
    expect(within(steps).getByText("Rozmowa z Martą")).toBeInTheDocument();
    expect(within(open).getByRole("form", { name: "Szybka aplikacja: samo CV" })).toBeInTheDocument();
    for (const link of within(open).getAllByRole("link", { name: "Klauzula informacyjna" })) {
      expect(link).toHaveAttribute("href", "/kariera/rodo");
    }
    expect(open.textContent).not.toMatch(/zł\/h\s*\d|PLN\s*\d/);
  });

  it("zamknięta rekrutacja: tytuł z plakietką, podobne z tablicy, prośba o CV, bez formularza", () => {
    render(<CareerPreviewPage />);
    const closed = screen.getByRole("region", { name: "rekrutacja zamknięta" });
    expect(within(closed).getByRole("heading", { level: 1 })).toHaveTextContent("Senior Java Developer");
    expect(within(closed).getByText(/Ta rekrutacja już nie przyjmuje zgłoszeń\./)).toBeInTheDocument();
    const similar = within(closed).getAllByRole("link", { name: /^Zobacz: / });
    expect(similar.length).toBeGreaterThan(0);
    expect(similar.map((a) => a.getAttribute("href"))).not.toContain("/kariera/r/senior-java-developer-7kq2");
    expect(within(closed).getByRole("link", { name: "Zostaw CV na następny projekt" })).toHaveAttribute("href", "/kariera#zostaw-cv");
    expect(closed.querySelector("form")).toBeNull();
  });

  it("zamknięta bez tablicy: inne rekrutacje tej osoby, bez ślepego zaułka", () => {
    render(<CareerPreviewPage />);
    const closed = screen.getByRole("region", { name: "zamknięta, bez tablicy" });
    expect(within(closed).getByRole("link", { name: "Zobacz: Analityk biznesowy" })).toHaveAttribute(
      "href",
      "/kariera/r/analityk-biznesowy-q8m1",
    );
    // Bez zachęty do udostępnienia na LinkedInie; stopka strony (od 25.11.2026
    // jak na stronie głównej) ma link do profilu firmy, więc liczy się treść nad nią.
    const content = closed.cloneNode(true) as HTMLElement;
    content.querySelector("footer")?.remove();
    expect(content.textContent).not.toMatch(/LinkedIn/);
    expect(within(closed).getByRole("contentinfo")).toHaveTextContent("LinkedIn");
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

  it("stały link rekrutera linkuje do rekrutacji", () => {
    render(<CareerPreviewPage />);
    const general = screen.getByRole("region", { name: "stały link rekrutera" });
    expect(within(general).getByRole("link", { name: /DevOps Engineer Azure/ })).toHaveAttribute(
      "href",
      "/kariera/r/devops-engineer-azure-p3x9",
    );
  });

  it("strona rekrutera w ramie nowej strony: imię bez nazwiska, „O mnie”, karty bez kategorii", () => {
    render(<CareerPreviewPage />);
    const page = screen.getByRole("region", { name: "stały link rekrutera" });
    expect(within(page).getByRole("heading", { level: 1 })).toHaveTextContent("Marta. Rekrutuję w IT.");
    expect(within(page).getByText(/Szukam ludzi do projektów w bankowości/)).toBeInTheDocument();
    // Kategorii na stronie kariery nie ma (decyzja Artura 23.11.2026) — ani plakietek, ani nazw.
    expect(within(page).queryByRole("list", { name: "Rekrutuję w obszarach" })).toBeNull();
    expect(page.textContent).not.toMatch(/Development|Infra & data|Management & delivery/);
    // Karty ofert jak na liście: z tablicy podtytuł i technologie, bez „Rekruter: Marta”.
    const jobs = within(page).getByRole("region", { name: "Moje otwarte rekrutacje" });
    expect(within(jobs).getAllByRole("article")).toHaveLength(3);
    expect(within(jobs).getByRole("link", { name: "Zobacz: Senior Java Developer" })).toHaveAttribute(
      "href",
      "/kariera/r/senior-java-developer-7kq2",
    );
    expect(within(jobs).getByText("Kafka")).toBeInTheDocument();
    expect(jobs.textContent).not.toMatch(/Rekruter:/);
    expect(within(page).getByRole("heading", { level: 2, name: "Nic nie pasuje? Zostaw CV u Marty." })).toBeInTheDocument();
    expect(
      within(page).getByRole("link", { name: "Wszystkie otwarte rekrutacje B2Bnetwork →" }),
    ).toHaveAttribute("href", "/kariera");
    expect(within(page).getByRole("link", { name: "Zostaw CV" })).toHaveAttribute("href", "#aplikuj");
    // Formularz do bazy: jedna obowiązkowa zgoda na przyszłe procesy (bez zmian reguł).
    const form = within(page).getByRole("region", { name: "Zostaw CV u Marty" });
    expect(form.querySelector('input[name="consent"]')).not.toBeNull();
    expect(form.querySelector('input[name="consent_future"]')).toBeNull();
    expect(page.querySelector("footer")).toHaveTextContent("nexus.b2bnetwork.pl/kariera/p/marta-n");
  });

  it("strona rekrutera bez opisu, rekrutacji i tablicy: zdanie zamiast pustej listy", () => {
    render(<CareerPreviewPage />);
    const page = screen.getByRole("region", { name: "rekruter bez opisu i rekrutacji" });
    expect(within(page).getByText(/Teraz nie mam otwartych rekrutacji/)).toBeInTheDocument();
    expect(within(page).getByText(/Zostaw CV raz — odezwę się/)).toBeInTheDocument();
    expect(within(page).queryByRole("article")).toBeNull();
    expect(within(page).getByRole("heading", { level: 2, name: "Zostaw CV u Oli." })).toBeInTheDocument();
  });

  it("harness nie używa react-query ani API (strażnik źródła)", () => {
    const src = readFileSync(join(process.cwd(), "src/app/preview/kariera/page.tsx"), "utf8");
    expect(src).not.toMatch(/useQuery|@\/lib\/api["']|fetch\(/);
  });
});
