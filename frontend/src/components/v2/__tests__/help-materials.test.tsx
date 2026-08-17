import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HelpMaterial } from "@/lib/api/help-materials";

/**
 * Testy „Materiałów" (Pomoc → Materiały).
 *
 * Moduł API jest mockowany w całości — dlatego etykiety i mapowanie ikon żyją
 * w komponencie, nie w `@/lib/api/help-materials` (stała trzymana w mockowanym
 * module wychodzi tu jako `undefined`; udokumentowana pułapka w CLAUDE.md).
 */
const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  remove: vi.fn(),
  onEdit: vi.fn(),
}));

vi.mock("@/lib/api/help-materials", () => ({
  helpMaterialsApi: {
    list: (...args: unknown[]) => mocks.list(...args),
    create: vi.fn(),
    update: vi.fn(),
    remove: (...args: unknown[]) => mocks.remove(...args),
  },
}));

import { HelpMaterialsSection } from "@/components/v2/pages/HelpMaterialsSection";

const SHAREPOINT_WORD_URL =
  "https://firma.sharepoint.com/:w:/g/personal/hr/EaBc123?e=5Hq7Xz";

function material(overrides: Partial<HelpMaterial> = {}): HelpMaterial {
  return {
    id: 1,
    slug: "szablon-do-umowy",
    category: "Szablony i wzory",
    title: "Szablon do umowy",
    url: SHAREPOINT_WORD_URL,
    description: null,
    template_subject: null,
    template_body: null,
    is_editable_template: false,
    sort_order: 0,
    is_published: true,
    created_by: 1,
    updated_by: 1,
    created_at: "2026-08-01T10:00:00Z",
    updated_at: "2026-08-01T10:00:00Z",
    ...overrides,
  };
}

function renderSection(items: HelpMaterial[], isAdmin = true) {
  mocks.list.mockResolvedValue(items);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <HelpMaterialsSection isAdmin={isAdmin} onEdit={mocks.onEdit} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Materiały — grupowanie", () => {
  it("grupuje pozycje po kategorii i porządkuje grupy wg najniższego sort_order", async () => {
    renderSection([
      material({
        id: 10,
        category: "Formularze klientów",
        title: "NORDEA — formularz",
        sort_order: 20,
      }),
      material({
        id: 11,
        category: "Formularze klientów",
        title: "BNP CARDIF — formularz",
        sort_order: 21,
      }),
      material({ id: 1, category: "Szablony i wzory", title: "Szablon do umowy", sort_order: 1 }),
      material({ id: 2, category: "Szablony i wzory", title: "Profil Championa", sort_order: 2 }),
      material({ id: 3, category: "Szablony i wzory", title: "Notatka po screeningu", sort_order: 3 }),
    ]);

    const headings = await screen.findAllByRole("heading", { level: 3 });
    expect(headings.map((h) => h.textContent)).toEqual([
      "Szablony i wzory(3)",
      "Formularze klientów(2)",
    ]);
  });

  it("wewnątrz grupy sortuje po sort_order, a przy remisie po tytule", async () => {
    renderSection([
      material({ id: 1, title: "Zebra", sort_order: 5 }),
      material({ id: 2, title: "Alfa", sort_order: 5 }),
      material({ id: 3, title: "Pierwszy", sort_order: 1 }),
    ]);

    await screen.findByRole("heading", { level: 3, name: /Szablony i wzory/ });
    const titles = screen
      .getAllByRole("link", { name: /^Otwórz:/ })
      .map((link) => link.getAttribute("aria-label"));
    expect(titles).toEqual(["Otwórz: Pierwszy", "Otwórz: Alfa", "Otwórz: Zebra"]);
  });
});

describe("Materiały — skrót do edycji w Word Online", () => {
  it("pokazuje skrót tylko dla naszych wzorów i zachowuje oryginalne query", async () => {
    renderSection([
      material({ id: 1, title: "Szablon do umowy", is_editable_template: true }),
      material({ id: 2, title: "NORDEA — formularz", is_editable_template: false }),
    ]);

    const editLinks = await screen.findAllByRole("link", {
      name: /Edytuj w Word Online/,
    });
    expect(editLinks).toHaveLength(1);
    expect(editLinks[0]).toHaveAttribute(
      "aria-label",
      "Edytuj w Word Online: Szablon do umowy",
    );

    const href = editLinks[0].getAttribute("href") ?? "";
    const parsed = new URL(href);
    // Parametr dokładany przez URLSearchParams — oryginalne `e=` musi przetrwać.
    expect(parsed.searchParams.get("e")).toBe("5Hq7Xz");
    expect(parsed.searchParams.get("action")).toBe("edit");
    expect(parsed.pathname).toBe("/:w:/g/personal/hr/EaBc123");
  });

  it("przy niepoprawnym URL-u nie rzuca wyjątkiem, tylko chowa skrót do edycji", async () => {
    renderSection([
      material({
        id: 1,
        title: "Zepsuty link",
        url: "nie-jest-urlem",
        is_editable_template: true,
      }),
    ]);

    expect(await screen.findByText("Nieprawidłowy link")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Edytuj w Word Online/ }),
    ).not.toBeInTheDocument();
  });

  it("każdy link do SharePointa otwiera się w nowej karcie z rel=noopener noreferrer", async () => {
    renderSection([material({ id: 1, is_editable_template: true })]);

    const links = await screen.findAllByRole("link");
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    }
  });
});

describe("Materiały — stored-XSS w href", () => {
  // Walidacja w Pydantic pilnuje TYLKO zapisów przez API. Seed materiałów
  // wchodzi kanałem `_DATA_STATEMENTS` w entrypoint.sh — surowym SQL-em, który
  // omija API, więc `javascript:` może realnie wylądować w bazie.
  it.each([
    ["javascript:alert(1)", "javascript"],
    ["JavaScript:alert(1)", "javascript wielkimi literami"],
    ["java\nscript:alert(1)", "javascript ze znakiem sterującym"],
    ["data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==", "data:"],
    ["vbscript:msgbox(1)", "vbscript"],
  ])("nie renderuje klikalnego linku dla %s (%s)", async (badUrl) => {
    renderSection([
      material({ id: 1, title: "Złośliwy", url: badUrl, is_editable_template: true }),
    ]);

    expect(await screen.findByText("Nieprawidłowy link")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  // Adres bez schematu przeglądarka rozwiązuje względem originu NEXUSa —
  // „Otwórz" wyrzucałby użytkownika na 404 aplikacji przy wierszu wyglądającym
  // na sprawny. Zepsuty afordans czyta się jak utrata dokumentu, więc lepiej
  // powiedzieć wprost, że wpis wymaga poprawki.
  it.each([
    ["firma.sharepoint.com/:w:/g/personal/hr/EaBc123?e=5Hq7Xz", "domena bez schematu"],
    ["/wewnetrzna/sciezka", "ścieżka względna od roota"],
    ["//firma.sharepoint.com/x", "protocol-relative"],
  ])("nie robi klikalnego „Otwórz” z %s (%s)", async (badUrl) => {
    renderSection([material({ id: 1, title: "Bez schematu", url: badUrl })]);

    expect(await screen.findByText("Nieprawidłowy link")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Otwórz:/ })).not.toBeInTheDocument();
  });

  it("poprawny adres https nadal jest zwykłym linkiem", async () => {
    renderSection([material({ id: 1, title: "Szablon do umowy" })]);

    const link = await screen.findByRole("link", { name: "Otwórz: Szablon do umowy" });
    expect(link).toHaveAttribute("href", SHAREPOINT_WORD_URL);
    expect(screen.queryByText("Nieprawidłowy link")).not.toBeInTheDocument();
  });
});

describe("Materiały — uprawnienia", () => {
  it("nie-admin nie widzi akcji edycji wpisu ani usuwania", async () => {
    renderSection(
      [material({ id: 1, title: "Szablon do umowy", is_editable_template: true })],
      false,
    );

    expect(await screen.findByRole("link", { name: /^Otwórz:/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Edytuj wpis:/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Usuń wpis:/ })).not.toBeInTheDocument();
    // Skrót do Word Online to zwykły link do SharePointa — zostaje dla wszystkich.
    expect(screen.getByRole("link", { name: /Edytuj w Word Online/ })).toBeInTheDocument();
  });

  it("admin widzi akcje wpisu, a usuwanie wymaga potwierdzenia", async () => {
    renderSection([material({ id: 42, title: "Szablon do umowy" })]);

    const deleteButton = await screen.findByRole("button", {
      name: "Usuń wpis: Szablon do umowy",
    });

    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(deleteButton);
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(mocks.remove).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    mocks.remove.mockResolvedValue(undefined);
    fireEvent.click(deleteButton);
    await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith(42));

    fireEvent.click(screen.getByRole("button", { name: "Edytuj wpis: Szablon do umowy" }));
    expect(mocks.onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: 42 }));

    confirmSpy.mockRestore();
  });
});

describe("Materiały — stany puste", () => {
  it("brak materiałów w ogóle ma inny komunikat niż pusty wynik wyszukiwania", async () => {
    renderSection([]);

    expect(
      await screen.findByText(/Brak materiałów\. Dodaj pierwszy link/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Brak materiałów pasujących do wyszukiwania."),
    ).not.toBeInTheDocument();
  });

  it("pusty wynik wyszukiwania mówi wprost, że to filtr — nie utrata danych", async () => {
    renderSection([material({ id: 1, title: "Szablon do umowy" })]);
    await screen.findByRole("link", { name: /^Otwórz:/ });

    mocks.list.mockResolvedValue([]);
    fireEvent.change(screen.getByLabelText("Szukaj materiałów"), {
      target: { value: "nieistniejące" },
    });

    expect(
      await screen.findByText("Brak materiałów pasujących do wyszukiwania.", undefined, {
        timeout: 3000,
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Dodaj pierwszy link/)).not.toBeInTheDocument();
    await waitFor(() =>
      expect(mocks.list).toHaveBeenLastCalledWith({
        q: "nieistniejące",
        published_only: false,
      }),
    );
  });
});

/**
 * Wiersz-SZABLON (migracja 0229 seeduje go na każdym środowisku).
 *
 * Regresja, którą te testy zamykają: `url` stał się NULLOWALNY w API, ale typ
 * FE dalej deklarował `string`, więc `tsc` przepuszczał `material.url
 * .toLowerCase()` — a na zaseedowanym wierszu wywalało to render CAŁEJ sekcji
 * Materiałów, dla każdego zalogowanego, od pierwszego wejścia po deployu.
 */
describe("Materiały — pozycja będąca szablonem treści", () => {
  const TEMPLATE_BODY = [
    "Dzień dobry,",
    "",
    "Zapraszam na spotkanie przygotowujące do rozmowy z (nazwa Klienta).",
    "",
    "Pozdrawiam",
  ].join("\n");

  function templateMaterial(overrides: Partial<HelpMaterial> = {}): HelpMaterial {
    return material({
      id: 99,
      slug: "zaproszenie-prep-spotkanie",
      title: "Zaproszenie na spotkanie przygotowujące (prep)",
      url: null,
      template_subject:
        "Przygotowanie do spotkania z (nazwa Klienta) – (imię i nazwisko kandydata)",
      template_body: TEMPLATE_BODY,
      ...overrides,
    });
  }

  it("renderuje się bez wyjątku mimo url = null", async () => {
    renderSection([templateMaterial()]);

    expect(
      await screen.findByText("Zaproszenie na spotkanie przygotowujące (prep)"),
    ).toBeInTheDocument();
  });

  it("daje akcje zaproszenia zamiast etykiety „Nieprawidłowy link”", async () => {
    // Brak adresu to zamierzony stan tej pozycji, nie zepsuty wiersz —
    // komunikat o błędnym linku czytałby się jak awaria.
    renderSection([templateMaterial()]);

    expect(
      await screen.findByRole("button", { name: /^Pobierz zaproszenie \(\.ics\)/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /^Otwórz w Outlook Web/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Nieprawidłowy link")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Otwórz:/ })).not.toBeInTheDocument();
  });

  it("deeplink do Outlooka łamie wiersze przez <br>, nie przez %0A", async () => {
    renderSection([templateMaterial()]);

    const link = await screen.findByRole("link", { name: /^Otwórz w Outlook Web/ });
    const href = new URL(link.getAttribute("href") ?? "");
    expect(href.searchParams.get("rru")).toBe("addevent");
    expect(href.searchParams.get("body")).toContain("<br>");
    expect(href.searchParams.get("subject")).toContain("Przygotowanie do spotkania");
  });

  it("pokazuje instrukcję o CV obok przycisku, a NIE w treści zaproszenia", async () => {
    renderSection([templateMaterial()]);

    expect(
      await screen.findByText(
        "UWAGA! Do zaproszenia załączamy CV wysłane pod dany projekt",
      ),
    ).toBeInTheDocument();

    const href =
      screen.getByRole("link", { name: /^Otwórz w Outlook Web/ }).getAttribute("href") ??
      "";
    expect(decodeURIComponent(href)).not.toContain("UWAGA");
  });

  it("pozycja z linkiem NIE dostaje akcji zaproszenia", async () => {
    renderSection([material({ id: 1 })]);

    await screen.findByRole("link", { name: /^Otwórz:/ });
    expect(
      screen.queryByRole("button", { name: /Pobierz zaproszenie/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/UWAGA! Do zaproszenia załączamy CV/),
    ).not.toBeInTheDocument();
  });

  it("wiersz z linkiem ORAZ treścią daje OBIE akcje — dokument nie znika", async () => {
    // CHECK w bazie to `url IS NOT NULL OR template_body IS NOT NULL`, a PUT
    // dopisujący treść do wiersza-linku jest legalny (pinuje to test backendu
    // `test_adding_template_body_does_not_clear_url`). Przełącznik
    // „szablon ALBO link" gubił wtedy „Otwórz": adres siedział w bazie, a
    // rekruter nie miał żadnej drogi do dokumentu i czytał to jak utratę pliku.
    renderSection([templateMaterial({ id: 77, url: SHAREPOINT_WORD_URL })]);

    const open = await screen.findByRole("link", { name: /^Otwórz:/ });
    expect(open).toHaveAttribute("href", SHAREPOINT_WORD_URL);
    expect(
      screen.getByRole("button", { name: /^Pobierz zaproszenie \(\.ics\)/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Nieprawidłowy link")).not.toBeInTheDocument();
  });

  it("szablon z WADLIWYM adresem nie przemilcza błędu", async () => {
    // Brak adresu w szablonie jest zamierzony, ale adres NIE do otwarcia to
    // literówka admina — musi być widoczna, żeby dało się ją poprawić.
    renderSection([templateMaterial({ id: 78, url: "firma.sharepoint.com/plik" })]);

    expect(await screen.findByText("Nieprawidłowy link")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Pobierz zaproszenie \(\.ics\)/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^Otwórz:/ })).not.toBeInTheDocument();
  });
});
