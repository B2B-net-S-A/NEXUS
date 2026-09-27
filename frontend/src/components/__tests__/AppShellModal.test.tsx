import { beforeEach, describe, it, expect, vi } from "vitest";
import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  AddClientModal,
  EditCandidateModal,
} from "@/components/AppShell";
import api, { phase5Api, type ClientDirectoryCategory } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  aiWriterApi: {},
  phase5Api: { clientsLookup: vi.fn() },
  pipelineTemplatesApi: {},
  requestHistoryApi: {},
}));

beforeEach(() => {
  vi.clearAllMocks();
});

/**
 * Kontrakt dostępności shella modali z `AppShell.tsx`. `AddClientModal` jest tu
 * tylko najtańszym reprezentantem — wszystkie 8 modali dzieli ten sam `<Modal>`,
 * więc te asercje pilnują ich wszystkich naraz.
 */

/** Trigger + warunkowo montowany modal — jak u realnych konsumentów. */
function Harness({
  onClose,
  category,
}: {
  onClose?: () => void;
  category?: ClientDirectoryCategory;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Otwórz
      </button>
      {open && (
        <AddClientModal
          onClose={() => {
            setOpen(false);
            onClose?.();
          }}
          onSuccess={() => {}}
          category={category}
        />
      )}
    </>
  );
}

describe("AppShell <Modal> — a11y", () => {
  it("wystawia role=dialog + aria-modal i nazwę dostępną z nagłówka", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Otwórz" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    // aria-labelledby spięte z tytułem — wcześniej <h2> nie było z niczym powiązane.
    expect(dialog).toHaveAccessibleName("Dodaj firmę");
  });

  it("daje przyciskowi zamknięcia nazwę dostępną (nie samą ikonę)", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Otwórz" }));
    await screen.findByRole("dialog");

    expect(screen.getByRole("button", { name: "Zamknij" })).toBeInTheDocument();
  });

  it("przenosi fokus do modala i trzyma go w środku (pułapka fokusu)", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Otwórz" });
    await user.click(trigger);

    const dialog = await screen.findByRole("dialog");
    const focused = () => document.activeElement as HTMLElement | null;
    await waitFor(() => expect(dialog).toContainElement(focused()));

    // Kilkanaście tabów nie może wyprowadzić fokusu poza dialog.
    for (let i = 0; i < 15; i += 1) {
      await user.tab();
      expect(dialog).toContainElement(focused());
    }
    expect(document.activeElement).not.toBe(trigger);
  });

  it("zamyka na Escape i przywraca fokus na element wyzwalający", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    const trigger = screen.getByRole("button", { name: "Otwórz" });
    await user.click(trigger);
    await screen.findByRole("dialog");

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    // Bez przywrócenia fokusu użytkownik klawiatury lądował na <body>.
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("zamyka po kliknięciu „Zamknij”", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Otwórz" }));
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("button", { name: "Zamknij" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("zachowuje układ sprzed migracji (brak regresji wizualnej)", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Otwórz" }));

    const panel = await screen.findByRole("dialog");
    const overlay = panel.parentElement as HTMLElement;

    // Tylko klasy niosące układ — reszta wyglądu może się zmieniać bez
    // rozbijania testu. Overlay musi zostać kontenerem przewijania, bo to on
    // (a nie panel) trzyma wysokie modale w kadrze.
    for (const cls of [
      "fixed",
      "inset-0",
      "bg-black/50",
      "z-100",
      "overflow-y-auto",
      "items-end", // sheet na mobile…
      "sm:items-center", // …wyśrodkowany na desktopie
    ]) {
      expect(overlay.classList.contains(cls), `overlay: ${cls}`).toBe(true);
    }

    for (const cls of [
      "rounded-b-none", // dolne rogi tylko na mobile (sheet)
      "sm:rounded-b-2xl",
      "sm:max-w-2xl", // `wide` → szerszy panel
      // Treść radixa jest fokusowalna (tabindex=-1); bez tego przeglądarka
      // rysowałaby ring wokół całego panelu zaraz po otwarciu.
      "focus:outline-hidden",
    ]) {
      expect(panel.classList.contains(cls), `panel: ${cls}`).toBe(true);
    }
  });

  it("NIE zamyka się po kliknięciu w tło (zachowanie sprzed migracji na radix)", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Otwórz" }));

    const dialog = await screen.findByRole("dialog");
    const overlay = dialog.parentElement as HTMLElement;
    await user.click(overlay);

    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("przekazuje wybrany kafelek jako kategorię początkowego zakresu klienta", async () => {
    const user = userEvent.setup();
    const post = vi.mocked(api.post);
    post.mockClear();
    post.mockResolvedValueOnce({ data: {} } as never);
    render(<Harness category="relationship" />);

    await user.click(screen.getByRole("button", { name: "Otwórz" }));
    await user.type(
      screen.getByPlaceholderText("Acme Sp. z o.o."),
      "Klient relacyjny",
    );
    await user.click(screen.getByRole("button", { name: "Dodaj firmę" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/clients",
        expect.objectContaining({ name: "Klient relacyjny" }),
        {
          params: {
            portfolio_category: "relationship",
          },
        },
      ),
    );
  });
});

describe("EditCandidateModal — profile rate boundary", () => {
  it("does not expose or submit the OCC-managed profile rate", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({
      data: [],
    } as never);
    vi.mocked(api.patch).mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const onSuccess = vi.fn();

    render(
      <QueryClientProvider client={queryClient}>
        <EditCandidateModal
          candidate={{
            id: 7,
            name: "Jan",
            lastname: "Kowalski",
            expected_rate_hourly: "160.00",
            expected_rate_currency: "PLN",
          }}
          onClose={() => {}}
          onSuccess={onSuccess}
        />
      </QueryClientProvider>,
    );

    expect(
      screen.queryByText(/Stawka B2B.*PLN netto\/h/i),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

    // Bez zmian nie ma czego wysyłać (runda 9, R9-N8-7) — stawka ani
    // tożsamość nie jadą „przy okazji”.
    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(api.patch).not.toHaveBeenCalled();
  });

  it("sends only changed fields, never the stale status or preferences (R9-N8-7)", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({ data: [] } as never);
    vi.mocked(api.patch).mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={queryClient}>
        <EditCandidateModal
          candidate={{
            id: 13,
            name: "Jan",
            lastname: "Kowalski",
            status: "active",
            availability_date: "2026-10-01",
            max_onsite_days_per_week: 2,
            preferences: { remote_modes: ["hybrid"], industries: ["Fintech"] },
          }}
          onClose={() => {}}
          onSuccess={() => {}}
        />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(queryClient.isFetching()).toBe(0));

    await user.clear(screen.getByPlaceholderText("Fintech, E-commerce"));
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(api.patch).mock.calls[0]?.[1] as Record<string, unknown>;
    // Czarna lista ustawiona w tym czasie przez kogoś innego nie jest cofana.
    expect(payload).toEqual({ preferences: { industries: null } });
  });

  it("keeps imported object tags intact and shows only text tags in the field (UAT B60)", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({ data: [] } as never);
    vi.mocked(api.patch).mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const sourceTag = { type: "traffit_source", source_id: 3, value: "LinkedIn", domain: "linkedin.com" };

    render(
      <QueryClientProvider client={queryClient}>
        <EditCandidateModal
          candidate={{ id: 12, name: "Jan", lastname: "Kowalski", tags: ["Remote", sourceTag] }}
          onClose={() => {}}
          onSuccess={() => {}}
        />
      </QueryClientProvider>,
    );

    const field = screen.getByPlaceholderText("React, TypeScript, Remote...") as HTMLInputElement;
    expect(field.value).toBe("Remote");
    expect(screen.queryByDisplayValue(/object Object/)).not.toBeInTheDocument();
    expect(screen.getByText(/Tagi z importu zostają bez zmian: LinkedIn/)).toBeInTheDocument();

    // Zapis bez zmian nie dotyka kolumny tagów.
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Zapisz zmiany" })).toBeEnabled());
    expect(api.patch).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();

    // Edycja tekstu dodaje i usuwa POJEDYNCZE tagi — lista (z obiektem
    // importu i tagami dodanymi w tym czasie przez kolegę) nie jest nadpisywana.
    vi.mocked(api.post).mockResolvedValue({ data: {} });
    vi.mocked(api.delete).mockResolvedValue({ data: {} });
    await user.clear(field);
    await user.type(field, "Java");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post).toHaveBeenCalledWith("/api/candidates/12/tags", { tag: "Java" });
    await waitFor(() => expect(api.delete).toHaveBeenCalledTimes(1));
    expect(api.delete).toHaveBeenCalledWith("/api/candidates/12/tags", {
      params: { tag: "Remote" },
    });
    expect(api.patch).not.toHaveBeenCalled();
  });

  it("sends the office-presence rubric with explicit nulls for cleared preference keys (0278)", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({
      data: [],
    } as never);
    vi.mocked(api.patch).mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <EditCandidateModal
          candidate={{
            id: 11,
            name: "Jan",
            lastname: "Kowalski",
            preferences: { remote_modes: ["hybrid"], industries: ["Fintech"] },
          }}
          onClose={() => {}}
          onSuccess={() => {}}
        />
      </QueryClientProvider>,
    );

    // Odczekać, aż dwa `useQuery` (users/clients) się rozstrzygną, ZANIM
    // klikniemy w kontrolowany checkbox. W przeciwnym razie ich rezolucja
    // (mikrotaska z mocka) potrafi trafić DOKŁADNIE między click a commit
    // stanu z `onMulti`, a React na kolejnym renderze cofa DOM checkboxa do
    // stanu SPRZED kliknięcia — nie regresja produktu, pułapka jsdom/RTL.
    await waitFor(() => expect(queryClient.isFetching()).toBe(0));

    // Wartość checkboxa musi być "onsite", nie stara literówka "on_site"
    // (naprawiona w danych migracją 0278 — formularz nie ma prawa jej wysłać).
    await user.click(screen.getByLabelText("Stacjonarnie"));
    await user.type(screen.getByLabelText(/Maks\. dni w biurze/i), "2");
    // Odznaczenie pola niepustego wcześniej musi wysłać jawny `null`, nie
    // po prostu zniknąć z payloadu — merge po stronie backendu jest płytki
    // i klucz nieobecny w ogóle zostawia starą wartość nietkniętą.
    await user.clear(screen.getByPlaceholderText("Fintech, E-commerce"));

    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(api.patch).mock.calls[0]?.[1] as Record<
      string,
      unknown
    >;
    expect(payload.max_onsite_days_per_week).toBe(2);
    const preferences = payload.preferences as Record<string, unknown>;
    expect(preferences.remote_modes).toEqual(["hybrid", "onsite"]);
    expect(preferences.industries).toBeNull();
    // Klucz niezmieniony nie jedzie wcale (R9-N8-7).
    expect(preferences).not.toHaveProperty("office_cities");
  });

  it("submits only the identity field that the recruiter actually changed", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({
      data: [],
    } as never);
    vi.mocked(api.patch).mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <EditCandidateModal
          candidate={{ id: 8, name: "Jan", lastname: "Kowalski" }}
          onClose={() => {}}
          onSuccess={() => {}}
        />
      </QueryClientProvider>,
    );

    const lastname = screen.getByPlaceholderText("Kowalski");
    await user.clear(lastname);
    await user.type(lastname, "Nowak");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(api.patch).mock.calls[0]?.[1] as Record<
      string,
      unknown
    >;
    expect(payload).not.toHaveProperty("name");
    expect(payload).toHaveProperty("lastname", "Nowak");
  });

  it("compares identity to the opening snapshot when candidate props refresh", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({
      data: [],
    } as never);
    vi.mocked(api.patch).mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const onClose = vi.fn();
    const onSuccess = vi.fn();
    const renderModal = (candidate: Record<string, unknown>) => (
      <QueryClientProvider client={queryClient}>
        <EditCandidateModal
          candidate={candidate}
          onClose={onClose}
          onSuccess={onSuccess}
        />
      </QueryClientProvider>
    );

    const view = render(
      renderModal({ id: 9, name: "Jan", lastname: "Kowalski" }),
    );

    // Odświeżenie query zmienia props, ale otwarty formularz celowo zachowuje
    // snapshot „Kowalski”. Brak interakcji z polem nie może odesłać tej starej
    // wartości jako świadomej ręcznej korekty.
    view.rerender(
      renderModal({ id: 9, name: "Jan", lastname: "Nowak z synchronizacji" }),
    );
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(api.patch).not.toHaveBeenCalled();
  });
});
