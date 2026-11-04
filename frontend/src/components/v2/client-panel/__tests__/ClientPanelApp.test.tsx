import { useImperativeHandle, type Ref } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const viewer = vi.hoisted(() => ({
  searches: [] as unknown[],
  onFindResult: null as null | ((result: { current: number; total: number; pending: boolean }) => void),
}));

// Prawdziwa przeglądarka to pdf.js z workerem; tu liczy się, o co ekran ją prosi.
vi.mock("next/dynamic", () => ({
  default: () =>
    function StubViewer({
      handleRef,
      onFindResult,
    }: {
      handleRef: Ref<unknown>;
      onFindResult: typeof viewer.onFindResult;
    }) {
      viewer.onFindResult = onFindResult;
      useImperativeHandle(handleRef, () => ({
        search: (query: unknown) => viewer.searches.push(query),
        step: () => undefined,
      }));
      return <div data-testid="stub-viewer" />;
    },
}));

import { ToastProvider } from "@/components/Toast";
import { fictionalPanelTransport, type FictionalPanelOptions } from "@/app/preview/client-panel/fixtures";
import type { PanelTransport } from "@/lib/api/clientPanel";

import { ClientPanelApp } from "../ClientPanelApp";

function transportWith(
  options: FictionalPanelOptions = {},
  overrides: Partial<PanelTransport> = {},
): PanelTransport {
  return {
    ...fictionalPanelTransport(options),
    sendEvent: vi.fn(),
    ...overrides,
  };
}

function renderPanel(transport: PanelTransport, initialPublicId: string | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <ClientPanelApp token="t0ken" initialPublicId={initialPublicId} transport={transport} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function failingWith(status: number): Partial<PanelTransport> {
  return {
    fetchPanel: () => Promise.reject(Object.assign(new Error("x"), { response: { status } })),
  };
}

beforeEach(() => {
  viewer.searches.length = 0;
  viewer.onFindResult = null;
  window.localStorage.clear();
  window.history.replaceState(null, "", "/k/t0ken");
});

describe("ekrany błędów", () => {
  it.each([404, 410])("%i: link nieaktualny po polsku, bez listy i bez „Ponów”", async (status) => {
    renderPanel(transportWith({}, failingWith(status)));
    expect(
      await screen.findByText("Ten link jest nieaktualny, napisz do opiekuna procesu"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("client-panel-matrix")).toBeNull();
    expect(screen.queryByRole("button", { name: "Ponów" })).toBeNull();
  });

  it("zamknięta rekrutacja: powód to koniec rekrutacji, nie termin ważności", async () => {
    renderPanel(
      transportWith(
        {},
        {
          fetchPanel: () =>
            Promise.reject(
              Object.assign(new Error("x"), {
                response: { status: 410, data: { detail: "Ta rekrutacja jest już zamknięta." } },
              }),
            ),
        },
      ),
    );
    expect(await screen.findByText(/Ta rekrutacja jest już zakończona/)).toBeInTheDocument();
    expect(screen.queryByText(/Minął termin/)).toBeNull();
    expect(screen.queryByTestId("client-panel-matrix")).toBeNull();
  });

  it("wygasły link dalej mówi o terminie ważności", async () => {
    renderPanel(transportWith({}, failingWith(410)));
    expect(await screen.findByText(/Minął termin ważności linku/)).toBeInTheDocument();
    expect(screen.queryByText(/zakończona/)).toBeNull();
  });

  it("awaria serwera to nie „link nieaktualny” ani pusta lista; „Ponów” wczytuje panel", async () => {
    const good = fictionalPanelTransport();
    const fetchPanel = vi
      .fn()
      .mockRejectedValueOnce(Object.assign(new Error("x"), { response: { status: 503 } }))
      .mockImplementation(good.fetchPanel);
    renderPanel(transportWith({}, { fetchPanel }));
    expect(await screen.findByText("Nie udało się otworzyć panelu")).toBeInTheDocument();
    expect(screen.queryByText(/nieaktualny/)).toBeNull();
    expect(screen.queryByText(/Nie ma tu jeszcze kandydatów/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Ponów" }));
    expect(await screen.findByTestId("client-panel-matrix")).toBeInTheDocument();
  });

  it("awaria danych osoby to komunikat z „Ponów”, nie puste wymagania", async () => {
    renderPanel(
      transportWith({}, { fetchCandidate: () => Promise.reject(new Error("sieć")) }),
      "fikc-anna",
    );
    expect(await screen.findByText(/Nie udało się wczytać danych tej osoby/)).toBeInTheDocument();
    expect(screen.queryByTestId("requirements-list")).toBeNull();
  });
});

describe("lista i wejście", () => {
  it("bez `?c=` lista; `?c=` otwiera tę osobę od razu; nieznany `?c=` wraca na listę", async () => {
    const first = renderPanel(transportWith());
    expect(await screen.findByTestId("client-panel-matrix")).toBeInTheDocument();
    first.unmount();

    const second = renderPanel(transportWith(), "fikc-jan");
    expect(await screen.findByRole("heading", { name: "Jan Testowy" })).toBeInTheDocument();
    second.unmount();

    renderPanel(transportWith(), "nie-ma-takiego");
    expect(await screen.findByTestId("client-panel-matrix")).toBeInTheDocument();
  });

  it("stany osób pokazują się po polsku", async () => {
    renderPanel(transportWith());
    expect(await screen.findByText("Pytanie u opiekuna")).toBeInTheDocument();
    expect(screen.getByText("Rozmowa: terminy wysłane")).toBeInTheDocument();
    expect(screen.getByText("Nie pasuje")).toBeInTheDocument();
    expect(screen.getByText("bez decyzji")).toBeInTheDocument();
  });

  it("`show_other_candidates=false`: jedna osoba i bez porównania", async () => {
    renderPanel(transportWith({ showOthers: false }), "fikc-anna");
    expect(await screen.findByRole("heading", { name: "Anna Przykładowa" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Wszyscy \(1\)/ }));
    expect(await screen.findByTestId("client-panel-matrix")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Porównaj/ })).toBeNull();
    expect(screen.queryByText("Jan Testowy")).toBeNull();
  });

  it("porównanie: najwyżej trzy osoby, przycisk dopiero od dwóch", async () => {
    renderPanel(transportWith());
    await screen.findByTestId("client-panel-matrix");
    const button = screen.getByRole("button", { name: "Porównaj (0)" });
    expect(button).toBeDisabled();
    for (const name of ["Anna Przykładowa", "Jan Testowy", "Maria Fikcyjna"]) {
      await userEvent.click(screen.getByRole("checkbox", { name: `Porównaj: ${name}` }));
    }
    expect(screen.getByRole("checkbox", { name: "Porównaj: Piotr Demo" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Porównaj (3)" }));
    const compare = await screen.findByTestId("client-panel-compare");
    expect(within(compare).getByRole("button", { name: "Maria Fikcyjna" })).toBeInTheDocument();
    expect(within(compare).getByText("Stawka")).toBeInTheDocument();
  });
});

describe("wyłączniki z NEXUSA", () => {
  it("`show_rate=false`: bez kolumny, bez kwoty i bez powodu „Stawka”", async () => {
    renderPanel(transportWith({ showRate: false }));
    const table = await screen.findByTestId("client-panel-matrix");
    expect(within(table).queryByText("Stawka")).toBeNull();
    expect(screen.queryByText(/zł/)).toBeNull();
    expect(screen.queryByText(/faktura B2B/)).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Anna Przykładowa" }));
    await screen.findByTestId("requirements-list");
    expect(screen.queryByText(/zł/)).toBeNull();
    expect(screen.queryByText("stawka netto")).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "Warunki" }));
    expect(within(screen.getByTestId("terms-table")).queryByText("Stawka")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Nie pasuje" }));
    expect(screen.queryByRole("button", { name: "Stawka" })).toBeNull();
    expect(screen.getByRole("button", { name: "Dostępność" })).toBeInTheDocument();
  });

  it("`allow_actions=false`: ani jednego przycisku akcji", async () => {
    renderPanel(transportWith({ allowActions: false }), "fikc-anna");
    await screen.findByTestId("requirements-list");
    for (const name of ["Nie pasuje", "Zapytaj o kandydata", "Poproś o rozmowę"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    await userEvent.click(screen.getByRole("button", { name: /Gerrit/ }));
    expect(screen.queryByRole("button", { name: "Zapytaj o to" })).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: /Pytania i rozmowa/ }));
    expect(screen.queryByRole("button", { name: "Zadaj pytanie" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Poproś o rozmowę" })).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "Pliki" }));
    expect(screen.queryByRole("button", { name: "Poproś o dokument" })).toBeNull();
  });
});

describe("dowody i CV", () => {
  it("klik w wymaganie szuka frazy, a gdy 0 trafień, samego słowa, tylko raz", async () => {
    renderPanel(transportWith(), "fikc-anna");
    await screen.findByTestId("stub-viewer");
    await userEvent.click(screen.getByRole("button", { name: /Technika DDD/ }));
    const quote = "Rozwijala kod wedlug DDD i architektury heksagonalnej w istniejacej bazie kodu";
    await waitFor(() => expect(viewer.searches.at(-1)).toBe(quote));

    // Trwa szukanie: bez drugiej próby.
    act(() => viewer.onFindResult?.({ current: 0, total: 0, pending: true }));
    expect(viewer.searches.at(-1)).toBe(quote);

    act(() => viewer.onFindResult?.({ current: 0, total: 0, pending: false }));
    expect(viewer.searches.at(-1)).toBe("DDD");

    const count = viewer.searches.length;
    act(() => viewer.onFindResult?.({ current: 0, total: 0, pending: false }));
    expect(viewer.searches).toHaveLength(count);
    expect(screen.getByTestId("cv-find-result")).toHaveTextContent("Nie ma tej frazy w podglądzie");
  });

  it("trafienie frazy zostaje przy frazie i pokazuje liczbę", async () => {
    renderPanel(transportWith(), "fikc-anna");
    await screen.findByTestId("stub-viewer");
    await userEvent.click(screen.getByRole("button", { name: /FastAPI/ }));
    act(() => viewer.onFindResult?.({ current: 1, total: 2, pending: false }));
    expect(screen.getByTestId("cv-find-result")).toHaveTextContent("Znaleziono: 2");
  });

  it("brak CV: wymagania i cytaty działają, po prawej komunikat, plik się nie pobiera", async () => {
    const fetchCv = vi.fn();
    renderPanel(transportWith({ withCv: false }, { fetchCv }), "fikc-anna");
    expect(await screen.findByTestId("cv-unavailable")).toBeInTheDocument();
    expect(fetchCv).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Technika DDD/ }));
    expect(screen.getByText(/Rozwijala kod wedlug DDD/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Pobierz plik/ })).toBeNull();
  });

  it("awaria pobrania CV nie zabiera wymagań", async () => {
    renderPanel(
      transportWith({}, { fetchCv: () => Promise.reject(new Error("sieć")) }),
      "fikc-anna",
    );
    expect(await screen.findByText(/Nie udało się wczytać podglądu CV/)).toBeInTheDocument();
    expect(screen.getByTestId("requirements-list")).toBeInTheDocument();
  });
});

describe("zdarzenia", () => {
  it("wymaganie i zakładka idą jako zdarzenia z polską nazwą; osoby i plików nie dublujemy", async () => {
    const sendEvent = vi.fn();
    renderPanel(transportWith({}, { sendEvent }), "fikc-anna");
    await screen.findByTestId("requirements-list");
    await userEvent.click(screen.getByRole("button", { name: /Gerrit/ }));
    expect(sendEvent).toHaveBeenCalledWith({
      public_id: "fikc-anna",
      action: "requirement",
      detail: "Gerrit",
    });
    await userEvent.click(screen.getByRole("tab", { name: "Pliki" }));
    expect(sendEvent).toHaveBeenCalledWith({
      public_id: "fikc-anna",
      action: "tab",
      detail: "Pliki",
    });
    const actions = sendEvent.mock.calls.map(([event]) => event.action);
    expect(actions).not.toContain("candidate");
    expect(actions).not.toContain("file");
  });

  it("link do pliku nie przekazuje adresu z tokenem", async () => {
    renderPanel(transportWith(), "fikc-anna");
    await screen.findByTestId("requirements-list");
    await userEvent.click(screen.getByRole("tab", { name: "Pliki" }));
    for (const link of screen.getAllByRole("link", { name: "Pobierz" })) {
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    }
  });
});

describe("okna", () => {
  async function openAsk(transport: PanelTransport) {
    renderPanel(transport, "fikc-anna");
    await screen.findByTestId("requirements-list");
    await userEvent.click(screen.getByRole("button", { name: "Zapytaj o kandydata" }));
    return screen.findByRole("dialog");
  }

  it("pytanie: walidacja przed wysyłką, podpowiedź z braków, autor zapamiętany", async () => {
    const sendQuestion = vi.fn().mockResolvedValue(undefined);
    const dialog = await openAsk(transportWith({}, { sendQuestion }));

    await userEvent.click(within(dialog).getByRole("button", { name: "Wyślij pytanie" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Wpisz treść pytania.");

    await userEvent.click(within(dialog).getByRole("button", { name: "Gerrit" }));
    expect(within(dialog).getByLabelText("Twoje pytanie")).toHaveValue(
      "Czy kandydat pracował z: Gerrit? W jakim projekcie?",
    );
    await userEvent.type(within(dialog).getByLabelText("Twoje imię"), "Kasia");
    await userEvent.type(within(dialog).getByLabelText("Twój e-mail"), "kasia@bank");
    await userEvent.click(within(dialog).getByRole("button", { name: "Wyślij pytanie" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Podaj poprawny adres e-mail.");
    expect(sendQuestion).not.toHaveBeenCalled();

    await userEvent.type(within(dialog).getByLabelText("Twój e-mail"), ".example");
    await userEvent.click(within(dialog).getByRole("button", { name: "Wyślij pytanie" }));
    await waitFor(() =>
      expect(sendQuestion).toHaveBeenCalledWith("fikc-anna", {
        author_name: "Kasia",
        author_email: "kasia@bank.example",
        body: "Czy kandydat pracował z: Gerrit? W jakim projekcie?",
      }),
    );
    expect(JSON.parse(window.localStorage.getItem("nexus.client-panel.author") ?? "{}")).toEqual({
      name: "Kasia",
      email: "kasia@bank.example",
    });
  });

  it("zapamiętany autor wypełnia kolejne okno", async () => {
    window.localStorage.setItem(
      "nexus.client-panel.author",
      JSON.stringify({ name: "Kasia", email: "kasia@bank.example" }),
    );
    const dialog = await openAsk(transportWith());
    expect(within(dialog).getByLabelText("Twoje imię")).toHaveValue("Kasia");
    expect(within(dialog).getByLabelText("Twój e-mail")).toHaveValue("kasia@bank.example");
  });

  it("błąd serwera wraca w oknie po polsku, okno i treść zostają", async () => {
    window.localStorage.setItem(
      "nexus.client-panel.author",
      JSON.stringify({ name: "Kasia", email: "kasia@bank.example" }),
    );
    const sendQuestion = vi.fn().mockRejectedValue({
      isAxiosError: true,
      response: { status: 429, data: { detail: "Dziś z tego panelu wysłano już dużo wiadomości." } },
    });
    const dialog = await openAsk(transportWith({}, { sendQuestion }));
    await userEvent.type(within(dialog).getByLabelText("Twoje pytanie"), "Czy zna Gerrit?");
    await userEvent.click(within(dialog).getByRole("button", { name: "Wyślij pytanie" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Dziś z tego panelu wysłano już dużo wiadomości.",
    );
    expect(within(dialog).getByLabelText("Twoje pytanie")).toHaveValue("Czy zna Gerrit?");
  });

  it("nie pasuje: bez powodu nie wysyła; lista powodów idzie do serwera", async () => {
    window.localStorage.setItem(
      "nexus.client-panel.author",
      JSON.stringify({ name: "Kasia", email: "kasia@bank.example" }),
    );
    const sendNotFit = vi.fn().mockResolvedValue(undefined);
    renderPanel(transportWith({}, { sendNotFit }), "fikc-anna");
    await screen.findByTestId("requirements-list");
    await userEvent.click(screen.getByRole("button", { name: "Nie pasuje" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Wybierz co najmniej jeden powód.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Lokalizacja" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(sendNotFit).toHaveBeenCalledWith("fikc-anna", {
        author_name: "Kasia",
        author_email: "kasia@bank.example",
        reasons: ["Lokalizacja"],
      }),
    );
  });

  it("terminy: wysyła ISO z przesunięciem i długość, limit 6, sześć wyłącza dalsze", async () => {
    window.localStorage.setItem(
      "nexus.client-panel.author",
      JSON.stringify({ name: "Kasia", email: "kasia@bank.example" }),
    );
    const sendInterview = vi.fn().mockResolvedValue(undefined);
    renderPanel(transportWith({}, { sendInterview }), "fikc-anna");
    await screen.findByTestId("requirements-list");
    await userEvent.click(screen.getByRole("button", { name: "Poproś o rozmowę" }));
    const grid = await screen.findByTestId("slots-grid");
    expect(screen.getByRole("button", { name: "Wyślij terminy" })).toBeDisabled();

    const cells = within(grid).getAllByRole("button");
    for (const cell of cells.slice(0, 7)) await userEvent.click(cell);
    expect(screen.getByTestId("slots-count")).toHaveTextContent("Wybrane (6 z 6)");
    await userEvent.selectOptions(screen.getByLabelText("Długość"), "45");

    await userEvent.click(screen.getByRole("button", { name: "Wyślij terminy" }));
    await waitFor(() => expect(sendInterview).toHaveBeenCalledTimes(1));
    const body = sendInterview.mock.calls[0][1];
    expect(body.duration_minutes).toBe(45);
    expect(body.slots).toHaveLength(6);
    for (const slot of body.slots) {
      expect(slot.start).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00\+0[12]:00$/);
    }
  });

  it("rozmowa i „nie pasuje” z `thread` nie udają pytań czekających na opiekuna", async () => {
    const base = fictionalPanelTransport();
    renderPanel(
      transportWith(
        {},
        {
          fetchCandidate: async (publicId) => ({
            ...(await base.fetchCandidate(publicId)),
            thread: [
              { id: 1, kind: "not_fit", author: "Kasia", at: "2026-10-28T14:00:00Z", body: null, answer: null, answered_at: null },
              { id: 2, kind: "interview", author: "Kasia", at: "2026-10-28T14:00:00Z", body: "przegląd kodu", answer: null, answered_at: null },
            ],
          }),
        },
      ),
      "fikc-anna",
    );
    await screen.findByTestId("requirements-list");
    const tab = screen.getByRole("tab", { name: "Pytania i rozmowa" });
    await userEvent.click(tab);
    expect(screen.getByText("Jeszcze nie ma pytań.")).toBeInTheDocument();
    expect(screen.queryByText("Czeka u opiekuna")).toBeNull();
  });

  it("otwarty wniosek: drugi przycisk prośby jest wyłączony", async () => {
    renderPanel(transportWith(), "fikc-maria");
    await screen.findByTestId("requirements-list");
    expect(screen.getByRole("button", { name: "Poproś o rozmowę" })).toBeDisabled();
    await userEvent.click(screen.getByRole("tab", { name: /Pytania i rozmowa/ }));
    expect(screen.getByText("Kandydat wybiera")).toBeInTheDocument();
    expect(screen.getByText("Wt 10.11, 10:00")).toBeInTheDocument();
  });
});
