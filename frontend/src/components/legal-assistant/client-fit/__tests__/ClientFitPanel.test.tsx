import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientFitFinding, ClientFitResponse } from "@/lib/api/legalClientFit";

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { get, post } }));

import { ClientFitPanel } from "@/components/legal-assistant/client-fit/ClientFitPanel";

function finding(overrides: Partial<ClientFitFinding>): ClientFitFinding {
  return {
    id: 1,
    topic: "ict_training",
    topic_label: "Szkolenia ICT ludzi podwykonawcy",
    state: "gap",
    summary: "",
    client_quote: "Dostawca zapewni coroczne szkolenie każdej osoby.",
    client_ref: "Aneks nr 2 § 4 ust. 1",
    client_source: { kind: "amendment", id: 3, name: "Aneks nr 2" },
    our_quote: null,
    our_ref: null,
    next_step: "Dopisz w aneksie",
    annex_text: "Partner ukończy coroczne szkolenie wskazane przez Klienta B2BNET.",
    lawyer_review: [],
    affected_contracts: 6,
    clause_draft: null,
    ...overrides,
  };
}

const DONE: ClientFitResponse = {
  client_id: 5,
  client_name: "Bank Przykładowy S.A.",
  status: "done",
  status_message: null,
  checked_at: "2026-11-25T09:00:00+01:00",
  stale: false,
  sources: [{ kind: "framework_contract", id: 2, name: "Umowa ramowa", readable: true, note: null }],
  template_label: "Wzór B2B (PL)",
  active_b2b_contracts: 6,
  counts: { gap: 1, decide: 1, ok: 2 },
  findings: [
    finding({}),
    finding({
      id: 2,
      topic: "copyright",
      topic_label: "Prawa autorskie",
      state: "decide",
      client_quote: "Przeniesienie praw na polach z Załącznika nr 5.",
      client_ref: "Umowa ramowa § 14",
      our_quote: "Partner przenosi autorskie prawa majątkowe.",
      our_ref: "§ 5 ust. 1",
      annex_text: null,
      lawyer_review: ["kara umowna"],
    }),
    finding({
      id: 3,
      topic: "nda",
      topic_label: "NDA na wzorze klienta",
      state: "ok",
      client_quote: "Poufność na wzorze klienta.",
      client_ref: "Umowa ramowa § 9",
      our_ref: "§ 7",
      annex_text: null,
    }),
    finding({
      id: 4,
      topic: "data",
      topic_label: "Lokalizacja danych",
      state: "ok",
      client_quote: "Dane tylko w EOG.",
      client_ref: "Umowa ramowa § 11",
      our_ref: "§ 4",
      annex_text: null,
    }),
  ],
  can_request_clause_draft: true,
  disclaimer: "Asystent nie jest poradą prawną.",
};

function renderPanel(props: Partial<React.ComponentProps<typeof ClientFitPanel>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientFitPanel clientId={5} {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

describe("ClientFitPanel", () => {
  it("pokazuje luki i decyzje z cytatami oraz jedną zgodną pozycję", async () => {
    get.mockResolvedValue({ data: DONE });
    renderPanel();
    expect(
      await screen.findByText("Sprawdzone z umową ramową Bank Przykładowy S.A. i przepisami"),
    ).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/api/legal/client-fit/clients/5");
    expect(screen.getByText("1 luka")).toBeInTheDocument();
    expect(screen.getByText(/Dostawca zapewni coroczne szkolenie/)).toBeInTheDocument();
    expect(screen.getByText("Aneks nr 2 § 4 ust. 1")).toBeInTheDocument();
    expect(screen.getByText("brak w naszej umowie")).toBeInTheDocument();
    expect(screen.getByText("nasza umowa § 5 ust. 1")).toBeInTheDocument();
    expect(screen.getByText(/do prawnika: kara umowna/)).toBeInTheDocument();
    expect(screen.getAllByText(/dotyczy 6 aktywnych umów B2B u klienta/)).toHaveLength(2);
    // Z dwóch zgodnych panel pokazuje jedną; reszta w oknie szczegółów.
    expect(screen.getByText("NDA na wzorze klienta")).toBeInTheDocument();
    expect(screen.queryByText("Lokalizacja danych")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Szczegóły \(4 ustalenia\)/ })).toBeInTheDocument();
  });

  it("„Dodaj do treści aneksu” oddaje zdanie luki", async () => {
    get.mockResolvedValue({ data: DONE });
    const onAdd = vi.fn();
    renderPanel({ onAddToAnnex: onAdd });
    const buttons = await screen.findAllByRole("button", { name: /Dodaj do treści aneksu/ });
    // Tylko luka z gotowym zdaniem ma przycisk.
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    expect(onAdd).toHaveBeenCalledWith(
      "Partner ukończy coroczne szkolenie wskazane przez Klienta B2BNET.",
    );
  });

  it("bez callbacku nie ma przycisku, jest podpowiedź", async () => {
    get.mockResolvedValue({ data: DONE });
    renderPanel({ addHint: "Treść dopiszesz w aneksie „inna zmiana”." });
    await screen.findByText("1 luka");
    expect(screen.queryByRole("button", { name: /Dodaj do treści aneksu/ })).not.toBeInTheDocument();
    expect(screen.getByText("Treść dopiszesz w aneksie „inna zmiana”.")).toBeInTheDocument();
  });

  it("bez modelu mówi „Sprawdzenie niedostępne” i nie pokazuje nic jako zgodne", async () => {
    get.mockResolvedValue({
      data: {
        ...DONE,
        status: "unavailable",
        status_message: "Brak klucza dostawcy AI.",
        findings: DONE.findings,
      },
    });
    renderPanel();
    expect(await screen.findByText("Sprawdzenie niedostępne")).toBeInTheDocument();
    expect(screen.getByText("Brak klucza dostawcy AI.")).toBeInTheDocument();
    expect(screen.queryByText("NDA na wzorze klienta")).not.toBeInTheDocument();
    expect(screen.queryByText("1 luka")).not.toBeInTheDocument();
  });

  it("bieg w tle mówi „Sprawdzam w tle”", async () => {
    get.mockResolvedValue({ data: { ...DONE, status: "running", findings: [] } });
    renderPanel({ poll: false });
    expect(await screen.findByText(/Sprawdzam w tle/)).toBeInTheDocument();
  });

  it("nieaktualny wynik ma „Sprawdź ponownie”, które zleca bieg", async () => {
    get.mockResolvedValue({ data: { ...DONE, stale: true } });
    post.mockResolvedValue({ data: { status: "queued" } });
    renderPanel({ poll: false });
    fireEvent.click(await screen.findByRole("button", { name: /Sprawdź ponownie/ }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/legal/client-fit/clients/5/check"),
    );
  });

  it("403 (brak podglądu kwot u klienta) — panelu nie ma", async () => {
    get.mockRejectedValue({ response: { status: 403, data: { detail: "brak" } } });
    const { container } = renderPanel();
    await waitFor(() => expect(get).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("inny błąd to komunikat z „Ponów”, nie pusta lista", async () => {
    get.mockRejectedValue({ response: { status: 500, data: { detail: "Błąd serwera" } } });
    renderPanel();
    expect(
      await screen.findByText(
        "Nie udało się wczytać sprawdzenia z umową ramową klienta",
        {},
        { timeout: 4000 },
      ),
    ).toBeInTheDocument();
    get.mockResolvedValue({ data: DONE });
    fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
    expect(await screen.findByText("1 luka")).toBeInTheDocument();
  });

  it("bez klienta nic nie pyta", () => {
    const { container } = renderPanel({ clientId: null });
    expect(container).toBeEmptyDOMElement();
    expect(get).not.toHaveBeenCalled();
  });
});
