/**
 * Zakładka „Aneksy” kontraktu w wariancie A (19.11.2026): oś zmian po dniu
 * wejścia w życie, aneks z Generatora aneksów widać od wygenerowania („czeka
 * na podpis”), po podpisie wiadomo, skąd jest i jaki ma plik, a skan da się
 * dołączyć z kontraktu. Identyczne zapisy są zwinięte z ostrzeżeniem, a nad
 * osią stoi karta „Obowiązuje teraz” z jedną akcją „Dodaj aneks”.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  canViewFinance: vi.fn(),
  openDocument: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  },
  CONTRACT_FIELD_LABELS: { rate_candidate: "Stawka kandydata", project_name: "Projekt" },
  CONTRACT_TERMINATION_REASONS: [],
}));

vi.mock("@/lib/contract-documents", () => ({
  openContractDocument: (...a: unknown[]) => mocks.openDocument(...a),
}));

vi.mock("@/store/auth", async () => {
  const actual =
    await vi.importActual<typeof import("@/store/auth")>("@/store/auth");
  const state = { user: { id: 1, role: "admin", roles: ["admin"] } };
  return {
    ...actual,
    useAuthStore: (selector: (s: typeof state) => unknown) => selector(state),
    canManageCandidateFinance: () => true,
    canViewClientFinance: () => mocks.canViewFinance(),
  };
});

import { ContractAmendmentsTab } from "@/components/ContractAmendmentsTab";
import { documentsHref } from "@/lib/b2b-documents";

const WAITING = {
  document_id: 21,
  document_type: "annex_rate_change",
  type_label: "Aneks — zmiana stawki",
  state: "waiting",
  effective_date: "2026-11-01",
  change: {
    kind: "rate",
    hidden: false,
    currency: "PLN",
    items: [{ rate: 150, from: null, to: null }],
    before: [{ rate: 140, from: null, to: null }],
  },
  cancelled_reason: null,
  created_at: "2026-10-10T09:40:00Z",
  created_by_name: "Kamil Dudek",
};

const CANCELLED = {
  ...WAITING,
  document_id: 22,
  document_type: "annex_subcontractor",
  type_label: "Aneks — osoba skierowana",
  state: "cancelled",
  effective_date: "2026-06-15",
  change: { kind: "delegate", name: "Paweł Przykładowy" },
  cancelled_reason: "Partner nie podpisał",
};

const SIGNED = {
  id: 7,
  contract_id: 5,
  amendment_type: "start_date_change",
  old_values: { start_date: "2026-07-01" },
  new_values: { start_date: "2026-07-06" },
  effective_date: "2026-07-06",
  reason: "Aneks — zmiana daty startu z dnia 28.06.2026 (dokument #3)",
  document_id: 90,
  created_by: 2,
  created_by_email: "joanna@example.com",
  created_by_name: "Joanna Wilk",
  created_at: "2026-06-28T10:00:00Z",
  source: "generator",
  b2b_document_id: 3,
  state: "in_force",
  document: { id: 90, filename: "Aneks start.docx", is_signed_scan: false },
};

const MANUAL = {
  ...SIGNED,
  id: 8,
  amendment_type: "scope_change",
  old_values: { project_name: "Migracja" },
  new_values: { project_name: "Hurtownia danych" },
  effective_date: "2026-08-01",
  reason: "Zmiana projektu",
  document_id: null,
  source: "manual",
  b2b_document_id: null,
  document: null,
};

/** Ta sama zmiana stawek zapisana trzy razy (dwa razy 29.06, raz 05.07). */
const RATE = {
  ...MANUAL,
  id: 31,
  amendment_type: "rate_change",
  old_values: { rate_client: 180, rate_candidate: 140, rate_unit: "hourly" },
  new_values: { rate_client: 170, rate_candidate: 130 },
  effective_date: "2026-07-01",
  reason: "Klient obniżył stawkę od lipca.",
  created_by_email: null,
  created_by_name: "Anna Przykładowa",
  created_at: "2026-06-29T13:11:28Z",
};
const RATE_AGAIN = { ...RATE, id: 32, reason: null, created_at: "2026-06-29T13:21:26Z" };
const RATE_THIRD = { ...RATE, id: 33, reason: null, created_at: "2026-07-05T12:05:13Z" };
const EXTENSION = {
  ...RATE,
  id: 34,
  amendment_type: "extension",
  old_values: { status: "active", end_date: "2026-06-30" },
  new_values: { status: "active", end_date: "2026-12-31" },
  reason: null,
  created_at: "2026-06-29T13:11:58Z",
};

const CONTRACT = {
  contract_type: "b2b",
  end_date: null,
  client_order_end_date: "2026-12-31",
  rate_client: 170,
  rate_candidate: 130,
  currency: "PLN",
  rate_unit: "hourly",
  client_rate_schedule: [
    { rate: 180, effective_from: "2026-04-01", source_order_id: null },
    { rate: 170, effective_from: "2026-07-01", source_order_id: null },
  ],
  candidate_rate_schedule: [
    { rate: 140, effective_from: "2026-04-01" },
    { rate: 130, effective_from: "2026-07-01" },
  ],
};

/** Odpowiedzi obu tras zakładki; `undefined` = awaria tej trasy. */
function serve(amendments: unknown[] | undefined, annexDocuments: unknown[] | undefined) {
  mocks.get.mockImplementation((url: string) => {
    const data = url.endsWith("/annex-documents") ? annexDocuments : amendments;
    return data === undefined
      ? Promise.reject(Object.assign(new Error("HTTP 500"), { response: { status: 500, data: {} } }))
      : Promise.resolve({ data });
  });
}

function renderTab(
  props: Partial<React.ComponentProps<typeof ContractAmendmentsTab>> = {},
  seed?: (client: QueryClient) => void,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  seed?.(client);
  render(
    <QueryClientProvider client={client}>
      <ContractAmendmentsTab
        contractId={5}
        clientId={2}
        personName="Piotr Zając"
        {...props}
      />
    </QueryClientProvider>,
  );
}

/** Wpis osi (element listy) po tytule. */
async function entryTitled(title: string) {
  return (await screen.findByText(title)).closest("li") as HTMLElement;
}

/** Tekst elementu ze zwykłymi spacjami (kwoty mają twardą spację przed walutą). */
const textOf = (el: HTMLElement) => (el.textContent ?? "").replace(/\u00a0/g, " ");

beforeEach(() => {
  Object.values(mocks).forEach((m) => m.mockReset());
  mocks.canViewFinance.mockReturnValue(true);
  // Tylko zegar dat — timery zostają prawdziwe (findBy, react-query).
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-20T10:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("Zakładka Aneksy kontraktu — oś zmian", () => {
  it("dni od najnowszego: czekający aneks z tym, co zmieni, i linkiem do rejestru na górze", async () => {
    serve([SIGNED, MANUAL], [WAITING]);
    renderTab();

    const timeline = await screen.findByRole("list", { name: "Zmiany według daty wejścia w życie" });
    const days = within(timeline).getAllByRole("listitem").filter((li) => li.parentElement === timeline);
    expect(days.map((day) => day.textContent?.slice(0, 10))).toEqual(["01.11.2026", "01.08.2026", "06.07.2026"]);
    // Przyszły dzień mówi „za ile”, a ostatni dzień ze zmianą w mocy — „obowiązuje”.
    expect(within(days[0]).getByText("za 12 dni")).toBeInTheDocument();
    expect(within(days[1]).getByText("obowiązuje")).toBeInTheDocument();

    const waiting = await entryTitled("Zmiana stawki");
    expect(within(waiting).getByText("Czeka na podpis")).toBeInTheDocument();
    expect(textOf(waiting)).toContain("kandydat 140,00 → 150,00 zł/h");
    expect(textOf(waiting)).toContain("z Generatora aneksów · zmieni kontrakt po oznaczeniu jako podpisany");
    expect(textOf(waiting)).toContain("Kamil Dudek, 10.10.2026");
    expect(within(waiting).getByRole("link", { name: "Otwórz w rejestrze aneksów" })).toHaveAttribute(
      "href",
      "/contracts/b2b-generator?tab=annexes&q=Piotr+Zaj%C4%85c",
    );
    expect(screen.getByText("2 zmiany · 1 aneks czeka na podpis")).toBeInTheDocument();
  });

  it("wpis z generatora: plik, brak podpisów i „Dołącz skan”; ręczny: bez dokumentu, uzasadnienie jako cytat", async () => {
    serve([SIGNED, MANUAL], []);
    renderTab();

    const generated = await entryTitled("Zmiana daty startu");
    expect(textOf(generated)).toMatch(/^Zmiana daty startu/);
    expect(textOf(generated)).toContain("z Generatora aneksów");
    expect(within(generated).getByRole("button", { name: "Aneks start.docx" })).toBeInTheDocument();
    expect(within(generated).getByText("bez podpisów")).toBeInTheDocument();
    expect(within(generated).getByRole("button", { name: "Dołącz skan" })).toBeInTheDocument();
    expect(textOf(generated)).toContain("Joanna Wilk, 28.06.2026");
    // Powód aneksu z generatora składa serwer — nie jest uzasadnieniem.
    expect(within(generated).queryByText(/dokument #3/)).toBeNull();

    const manual = await entryTitled("Zmiana zakresu");
    expect(textOf(manual)).toContain("projekt Migracja → Hurtownia danych");
    expect(textOf(manual)).toContain("ręcznie · bez dokumentu · Joanna Wilk, 28.06.2026");
    expect(within(manual).getByText("„Zmiana projektu”")).toBeInTheDocument();
    // Skan dołącza się tylko do aneksu z generatora.
    expect(within(manual).queryByRole("button", { name: "Dołącz skan" })).toBeNull();
    // Nic z dawnej tabeli: kolumn „Źródło” i „Dokument” nie ma.
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("anulowany aneks z generatora: stan, powód i to, że zmiana nie weszła w życie", async () => {
    serve([MANUAL], [CANCELLED]);
    renderTab();
    const cancelled = await entryTitled("Osoba skierowana");
    expect(within(cancelled).getByText("Anulowany")).toBeInTheDocument();
    expect(textOf(cancelled)).toContain("zmiana nie weszła w życie — Partner nie podpisał");
    expect(within(cancelled).queryByRole("link", { name: "Otwórz w rejestrze aneksów" })).toBeNull();
  });

  it("podpisany aneks z dniem w przyszłości: stan „Podpisany” z tym, kiedy wejdzie w życie", async () => {
    serve([{ ...SIGNED, id: 9, effective_date: "2026-11-02", state: "signed_pending" }, MANUAL], []);
    renderTab();
    const signed = await entryTitled("Zmiana daty startu");
    expect(within(signed).getByText("Podpisany · wejdzie w życie za 13 dni")).toBeInTheDocument();
    // „Obowiązuje” dostaje ostatni dzień ≤ dziś, nie przyszły.
    const days = within(screen.getByRole("list", { name: "Zmiany według daty wejścia w życie" }))
      .getAllByText(/^\d{2}\.\d{2}\.\d{4}$/)
      .map((el) => el.parentElement?.textContent);
    expect(days).toEqual(["02.11.2026za 13 dni", "01.08.2026obowiązuje"]);
  });

  it("identyczne zapisy zwinięte z cichym ostrzeżeniem; „Pokaż wpisy” rozwija każdy zapis", async () => {
    serve([RATE_THIRD, RATE_AGAIN, EXTENSION, RATE], []);
    renderTab();

    const rates = await entryTitled("Zmiana stawek");
    expect(textOf(rates)).toContain("klient 180,00 → 170,00 zł/h · kandydat 140,00 → 130,00 zł/h");
    expect(textOf(rates)).toContain("ręcznie · bez dokumentu · Anna Przykładowa, 29.06.2026");
    expect(within(rates).getByText("„Klient obniżył stawkę od lipca.”")).toBeInTheDocument();
    expect(within(rates).getByText("zapisano 3 razy (05.07, 29.06, 29.06) — możliwy duplikat")).toBeInTheDocument();
    expect(screen.getAllByText("Zmiana stawek")).toHaveLength(1);
    expect(screen.getByText("2 zmiany · 2 powtórzone wpisy")).toBeInTheDocument();

    const toggle = within(rates).getByRole("button", { name: "Pokaż wpisy" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(within(rates).getByRole("button", { name: "Ukryj wpisy" })).toHaveAttribute("aria-expanded", "true");
    expect(textOf(rates)).toContain("05.07.2026, 14:05 · Anna Przykładowa · bez uzasadnienia");
    expect(textOf(rates)).toContain("29.06.2026, 15:11 · Anna Przykładowa · z uzasadnieniem · pierwszy zapis");
  });

  it("„Brak aneksów” dopiero, gdy oba odczyty są puste; sam czekający aneks to nie pustka", async () => {
    serve([], [WAITING]);
    renderTab({ readOnly: true });
    expect(await screen.findByText("Czeka na podpis")).toBeInTheDocument();
    expect(screen.queryByText(/Brak aneksów/)).not.toBeInTheDocument();
  });

  it("awaria listy czekających aneksów nie chowa zmian kontraktu i nie udaje pustki", async () => {
    serve([MANUAL], undefined);
    renderTab();
    expect(await screen.findByText("Zmiana zakresu")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Nie udało się wczytać aneksów czekających na podpis",
    );

    // Pusta historia + awaria drugiej trasy to nadal nie „Brak aneksów”.
    serve([], undefined);
    renderTab({ contractId: 6 });
    await waitFor(() => expect(screen.getAllByRole("alert").length).toBeGreaterThan(1));
    expect(screen.queryByText(/Brak aneksów/)).not.toBeInTheDocument();
  });

  it("bez wglądu w stawki aneks stawki nie pokazuje się w kontrakcie", async () => {
    mocks.canViewFinance.mockReturnValue(false);
    serve([MANUAL, RATE], [WAITING]);
    renderTab({ contract: CONTRACT });
    expect(await screen.findByText("Zmiana zakresu")).toBeInTheDocument();
    expect(screen.queryByText("Czeka na podpis")).not.toBeInTheDocument();
    expect(screen.queryByText("Zmiana stawek")).not.toBeInTheDocument();
    // Karta „Obowiązuje teraz” bez kwot — tylko okres.
    const now = screen.getByRole("region", { name: "Obowiązuje teraz" });
    expect(textOf(now)).not.toMatch(/zł/);
    expect(textOf(now)).toContain("zamówienie do 31.12.2026");
  });

  it("„Dołącz skan” wysyła plik do aneksu z generatora, a plik aneksu otwiera się z Dokumentów", async () => {
    serve([SIGNED], []);
    mocks.post.mockResolvedValue({ data: {} });
    renderTab();

    await screen.findByRole("button", { name: "Dołącz skan" });
    const file = new File(["%PDF-1.4"], "aneks.pdf", { type: "application/pdf" });
    fireEvent.click(screen.getByRole("button", { name: "Dołącz skan" }));
    fireEvent.change(screen.getByLabelText("Skan podpisanego aneksu"), {
      target: { files: [file] },
    });

    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const [url, body, config] = mocks.post.mock.calls[0];
    expect(url).toBe("/api/contracts/5/amendments/7/document");
    expect((body as FormData).get("file")).toBe(file);
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });

    fireEvent.click(screen.getByRole("button", { name: "Aneks start.docx" }));
    expect(mocks.openDocument).toHaveBeenCalledWith(5, SIGNED.document);
  });

  it("nieudany skan mówi o tym przy wpisie", async () => {
    serve([SIGNED], []);
    mocks.post.mockRejectedValue(
      Object.assign(new Error("HTTP 422"), { response: { status: 422, data: { detail: "Plik nie jest PDF-em." } } }),
    );
    renderTab();
    fireEvent.click(await screen.findByRole("button", { name: "Dołącz skan" }));
    fireEvent.change(screen.getByLabelText("Skan podpisanego aneksu"), {
      target: { files: [new File(["x"], "skan.pdf", { type: "application/pdf" })] },
    });
    const entry = await entryTitled("Zmiana daty startu");
    expect(await within(entry).findByRole("alert")).toHaveTextContent("Plik nie jest PDF-em.");
  });

  it("aneks ze skanem nie prosi o skan drugi raz, a tryb podglądu nie ma przycisku", async () => {
    serve(
      [{ ...SIGNED, document: { id: 91, filename: "Aneks podpisany.pdf", is_signed_scan: true } }],
      [],
    );
    renderTab();
    expect(await screen.findByText("skan podpisany")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dołącz skan" })).toBeNull();

    serve([SIGNED], []);
    renderTab({ contractId: 6, readOnly: true });
    await waitFor(() => expect(screen.getAllByText("Zmiana daty startu")).toHaveLength(2));
    expect(screen.queryByRole("button", { name: "Dołącz skan" })).toBeNull();
  });
});

describe("Zakładka Aneksy kontraktu — „Obowiązuje teraz” i „Dodaj aneks”", () => {
  it("karta z kontraktu: obie stawki od jednego dnia, zamówienie i umowa bezterminowa", async () => {
    serve([RATE, EXTENSION], []);
    renderTab({ contract: CONTRACT });
    const now = await screen.findByRole("region", { name: "Obowiązuje teraz" });
    expect(textOf(now)).toContain(
      "Od 01.07.2026: klient 170,00 zł/h · kandydat 130,00 zł/h · zamówienie do 31.12.2026",
    );
    expect(textOf(now)).toContain("umowa B2B bezterminowa");
    expect(within(now).getByRole("button", { name: /Dodaj aneks/ })).toBeInTheDocument();
  });

  it("bez propsa karta bierze kontrakt wczytany przez stronę — bez własnego zapytania", async () => {
    serve([RATE], []);
    renderTab({}, (client) => client.setQueryData(["contract", 5], { ...CONTRACT, client_order_end_date: "2027-01-31" }));
    const now = await screen.findByRole("region", { name: "Obowiązuje teraz" });
    expect(textOf(now)).toContain("zamówienie do 31.01.2027");
    expect(mocks.get.mock.calls.map(([url]) => url)).not.toContain("/api/contracts/5");
  });

  it("menu: zmiana stawki otwiera okno z ostrzeżeniem, gdy aneks stawki czeka na podpis", async () => {
    const user = userEvent.setup();
    serve([], [WAITING]);
    renderTab();
    await user.click(await screen.findByRole("button", { name: /Dodaj aneks/ }));
    await user.click(await screen.findByRole("menuitem", { name: "Zmiana stawki" }));
    const dialog = await screen.findByRole("dialog", { name: "Zmiana stawki" });
    expect(
      within(dialog).getByText(/Aneks zmiany stawki z Generatora aneksów czeka na podpis/),
    ).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Nowa stawka kandydata")).toBeInTheDocument();
  });

  it("menu: przedłużenie wyłączone z powodem, zakończenie przez okno strony, dokument w generatorze", async () => {
    const user = userEvent.setup();
    const terminate = vi.fn();
    serve([MANUAL], []);
    renderTab({ extensionLocked: true, onRequestTermination: terminate });
    await user.click(await screen.findByRole("button", { name: /Dodaj aneks/ }));
    const menu = await screen.findByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "Przedłużenie" })).toHaveAttribute("aria-disabled", "true");
    expect(within(menu).getByText(/nie ma czego przedłużać/)).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: /Wygeneruj dokument aneksu/ })).toHaveAttribute(
      "href",
      documentsHref({ newType: "annex_rate_change", contractId: 5 }),
    );
    await user.click(within(menu).getByRole("menuitem", { name: "Zakończenie wcześniej…" }));
    expect(terminate).toHaveBeenCalledTimes(1);
  });

  it("zapis z okna wysyła aneks i zamyka okno", async () => {
    const user = userEvent.setup();
    serve([MANUAL], []);
    mocks.post.mockResolvedValue({ data: {} });
    renderTab();
    await user.click(await screen.findByRole("button", { name: /Dodaj aneks/ }));
    await user.click(await screen.findByRole("menuitem", { name: "Zmiana zakresu" }));
    const dialog = await screen.findByRole("dialog", { name: "Zmiana zakresu" });
    await user.type(within(dialog).getByLabelText("Nowy projekt"), "Platforma danych");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz aneks" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/contracts/5/amendments", {
        amendment_type: "scope_change",
        effective_date: "2026-10-20",
        reason: null,
        new_project_name: "Platforma danych",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("odmowa serwera zostaje w oknie jako komunikat", async () => {
    const user = userEvent.setup();
    serve([MANUAL], []);
    mocks.post.mockRejectedValue(
      Object.assign(new Error("HTTP 422"), { response: { status: 422, data: { detail: "Data przed startem kontraktu." } } }),
    );
    renderTab();
    await user.click(await screen.findByRole("button", { name: /Dodaj aneks/ }));
    await user.click(await screen.findByRole("menuitem", { name: "Zmiana zakresu" }));
    const dialog = await screen.findByRole("dialog", { name: "Zmiana zakresu" });
    await user.click(within(dialog).getByRole("button", { name: "Zapisz aneks" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Data przed startem kontraktu.");
  });
});
