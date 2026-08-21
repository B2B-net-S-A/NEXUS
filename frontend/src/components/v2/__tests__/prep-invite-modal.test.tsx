import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HelpMaterial } from "@/lib/api/help-materials";

/**
 * Zaproszenie prep z profilu kandydata.
 *
 * Treść pochodzi z pozycji-szablonu w Materiałach (jedno źródło prawdy z
 * zakładką Pomoc), więc moduł API jest tu mockowany — a to znaczy, że żadna
 * funkcja używana w runtime nie może w nim mieszkać.
 */
const mocks = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("@/lib/api/help-materials", () => ({
  helpMaterialsApi: {
    list: (...args: unknown[]) => mocks.list(...args),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
}));

import { PrepInviteModal } from "@/components/v2/modals/PrepInviteModal";

const TEMPLATE_BODY = [
  "Dzień dobry,",
  "",
  "Zapraszam na spotkanie przygotowujące do rozmowy z (nazwa Klienta) na stanowisko (nazwa stanowiska), które odbędzie się (data interview).",
  "",
  "Link do opisu stanowiska: (link do pracuj / rocketjobs)",
  "",
  "Pozdrawiam",
].join("\n");

function templateRow(overrides: Partial<HelpMaterial> = {}): HelpMaterial {
  return {
    id: 99,
    slug: "zaproszenie-prep-spotkanie",
    category: "Szablony i wzory",
    title: "Zaproszenie na spotkanie przygotowujące (prep)",
    url: null,
    description: null,
    template_subject:
      "Przygotowanie do spotkania z (nazwa Klienta) – (imię i nazwisko kandydata)",
    template_body: TEMPLATE_BODY,
    is_editable_template: false,
    sort_order: 35,
    is_published: true,
    created_by: null,
    updated_by: null,
    created_at: "2026-08-17T10:00:00Z",
    updated_at: "2026-08-17T10:00:00Z",
    ...overrides,
  };
}

function renderModal(
  candidateName = "Jan Kowalski",
  onToast?: (message: string, type?: "success" | "error") => void,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PrepInviteModal
        open
        onOpenChange={() => {}}
        candidateName={candidateName}
        onToast={onToast}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Zaproszenie prep — profil kandydata", () => {
  it("podstawia nazwisko kandydata, resztę zostawia do uzupełnienia", async () => {
    mocks.list.mockResolvedValue([templateRow()]);
    renderModal();

    const subject = await screen.findByLabelText<HTMLInputElement>("Temat");
    expect(subject.value).toBe(
      "Przygotowanie do spotkania z (nazwa Klienta) – Jan Kowalski",
    );

    const body = screen.getByLabelText<HTMLTextAreaElement>("Treść");
    expect(body.value).toContain("(nazwa Klienta)");
    expect(body.value).toContain("(data interview)");
    // Adresy ofert w NEXUSie są generowane roboczo — automat wysłałby link
    // prowadzący donikąd, więc placeholder MUSI zostać widoczny.
    expect(body.value).toContain("(link do pracuj / rocketjobs)");
  });

  it("daje ścieżkę główną (.ics) i dodatkową (Outlook Web)", async () => {
    mocks.list.mockResolvedValue([templateRow()]);
    renderModal();

    expect(
      await screen.findByRole("button", { name: /Pobierz zaproszenie \(\.ics\)/ }),
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Outlook Web/ });
    const href = new URL(link.getAttribute("href") ?? "");
    expect(href.searchParams.get("rru")).toBe("addevent");
    expect(href.searchParams.get("body")).toContain("<br>");
  });

  it("instrukcja o CV jest w UI, ale NIE w treści zaproszenia", async () => {
    mocks.list.mockResolvedValue([templateRow()]);
    renderModal();

    expect(
      await screen.findByText(
        "UWAGA! Do zaproszenia załączamy CV wysłane pod dany projekt",
      ),
    ).toBeInTheDocument();
    const body = screen.getByLabelText<HTMLTextAreaElement>("Treść");
    expect(body.value).not.toContain("UWAGA");
  });

  it("awaria pobrania NIE renderuje się jako brak szablonu", async () => {
    // 403/500 pokazane jako pustka czyta się jak utrata danych — użytkownik
    // zgłasza „zniknął mi szablon" zamiast „nie działa".
    mocks.list.mockRejectedValue(new Error("boom"));
    renderModal();

    expect(
      await screen.findByText("Nie udało się wczytać szablonu zaproszenia."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Brak szablonu zaproszenia w Materiałach."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Pobierz zaproszenie/ }),
    ).not.toBeInTheDocument();
  });

  it("usunięty szablon mówi wprost, gdzie go odtworzyć", async () => {
    mocks.list.mockResolvedValue([]);
    renderModal();

    expect(
      await screen.findByText("Brak szablonu zaproszenia w Materiałach."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Nie udało się wczytać szablonu zaproszenia."),
    ).not.toBeInTheDocument();
  });

  it("zmiana tytułu w Pomocy NIE gasi przycisku na profilu kandydata", async () => {
    // Slug jest już niezmienny po stronie API, ale wiersz odtworzony ręcznie
    // przez admina dostanie slug wyliczony z tytułu — nigdy tej stałej. Bez
    // fallbacku pusty stan każe zrobić coś, co przycisku nie przywróci.
    mocks.list.mockResolvedValue([
      templateRow({ slug: "zaproszenie-na-spotkanie-przygotowujace-prep-2026" }),
    ]);
    renderModal();

    expect(
      await screen.findByRole("button", { name: /Pobierz zaproszenie \(\.ics\)/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Brak szablonu zaproszenia w Materiałach."),
    ).not.toBeInTheDocument();
  });

  it("nieudane kopiowanie jest widoczne, nawet gdyby toast nie był podpięty", async () => {
    // Cisza po kliknięciu czyta się jak sukces: rekruter wkleja do Outlooka
    // poprzednią zawartość schowka i wysyła nie to, co myśli.
    const onToast = vi.fn();
    mocks.list.mockResolvedValue([templateRow()]);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    renderModal("Jan Kowalski", onToast);

    const copy = await screen.findByRole("button", {
      name: /Kopiuj treść zaproszenia/,
    });
    fireEvent.click(copy);

    await waitFor(() =>
      expect(screen.getByText("Nie udało się skopiować")).toBeInTheDocument(),
    );
    expect(onToast).toHaveBeenCalledWith(
      "Nie udało się skopiować — zaznacz treść i skopiuj ręcznie",
      "error",
    );
    // Odpinamy stub, żeby kolejny test w tym pliku nie zastał schowka, który
    // zawsze odmawia.
    Reflect.deleteProperty(navigator, "clipboard");
  });

  it("pozycja o tym slugu bez treści nie udaje sprawnego szablonu", async () => {
    // CHECK w bazie tego nie dopuści, ale wiersz może przyjechać z historii
    // albo z innego środowiska — pusty szablon dałby puste zaproszenie.
    mocks.list.mockResolvedValue([templateRow({ template_body: "   " })]);
    renderModal();

    await waitFor(() =>
      expect(
        screen.getByText("Brak szablonu zaproszenia w Materiałach."),
      ).toBeInTheDocument(),
    );
  });
});
