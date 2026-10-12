import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

// Lista rekrutacji w bloku „Rekrutacje”: szukanie po stronie serwera, status,
// zaznaczanie wielu pozycji i „cały klient” jako jedna pozycja.

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, default: { get: vi.fn() } };
});

import api from "@/lib/api";
import { RecruitmentScopePicker } from "@/components/v2/filters/RecruitmentScopePicker";

const get = vi.mocked(api.get);

const OPEN_JOB = {
  id: 2143,
  title: "Java Developer",
  client_id: 3,
  client_name: "Bank Alfa",
  status: "open",
};
const CLOSED_JOB = { ...OPEN_JOB, id: 1764, status: "closed" };
const BANK = { id: 3, name: "Bank Alfa", jobs_count: 3 };

type Params = Record<string, unknown>;
const isLabels = (params: Params) => "ids" in params || "client_ids" in params;

/** Odpowiedzi nowej trasy: osobno szukanie, osobno etykiety wybranych pozycji. */
function serve(search: (params: Params) => unknown, labels: unknown = { items: [], clients: [], total: 0 }) {
  get.mockImplementation(((_url: string, config?: { params?: Params }) => {
    const params = config?.params ?? {};
    return Promise.resolve({ data: isLabels(params) ? labels : search(params) });
  }) as never);
}

function searchCalls(): Params[] {
  return get.mock.calls
    .map((call) => (call[1] as { params?: Params } | undefined)?.params ?? {})
    .filter((params) => !isLabels(params));
}

function Harness({
  onChange,
  ids = [],
  clients = [],
}: {
  onChange: (ids: number[], clients: number[]) => void;
  ids?: number[];
  clients?: number[];
}) {
  const [value, setValue] = useState({ ids, clients });
  return (
    <RecruitmentScopePicker
      recruitmentIds={value.ids}
      clientIds={value.clients}
      onChange={(nextIds, nextClients) => {
        setValue({ ids: nextIds, clients: nextClients });
        onChange(nextIds, nextClients);
      }}
    />
  );
}

function renderPicker(props: Partial<Parameters<typeof Harness>[0]> = {}) {
  const onChange = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness onChange={onChange} {...props} />
    </QueryClientProvider>,
  );
  return { onChange };
}

beforeEach(() => {
  get.mockReset();
});

describe("RecruitmentScopePicker — stany listy", () => {
  it("awaria pokazuje błąd z „Ponów”, nie pustą listę", async () => {
    const user = userEvent.setup();
    get.mockRejectedValueOnce(new Error("500"));
    renderPicker();
    await user.click(screen.getByRole("button", { name: /Wszystkie rekrutacje/ }));

    expect(await screen.findByText("Nie udało się pobrać listy rekrutacji.")).toBeInTheDocument();
    expect(screen.queryByText(/Brak rekrutacji/)).not.toBeInTheDocument();

    serve(() => ({ items: [OPEN_JOB], clients: [], total: 1 }));
    await user.click(screen.getByRole("button", { name: /Ponów/i }));
    expect(await screen.findByText("Java Developer")).toBeInTheDocument();
  });

  it("w trakcie pobierania mówi „Ładowanie”, nie „Brak rekrutacji”", async () => {
    const user = userEvent.setup();
    get.mockReturnValueOnce(new Promise(() => {}));
    renderPicker();
    await user.click(screen.getByRole("button", { name: /Wszystkie rekrutacje/ }));

    expect(await screen.findByText("Ładowanie rekrutacji…")).toBeInTheDocument();
    expect(screen.queryByText(/Brak rekrutacji/)).not.toBeInTheDocument();
  });

  it("prawdziwie pusty wynik mówi, że nic nie pasuje", async () => {
    const user = userEvent.setup();
    serve(() => ({ items: [], clients: [], total: 0 }));
    renderPicker();
    await user.click(screen.getByRole("button", { name: /Wszystkie rekrutacje/ }));
    expect(await screen.findByText("Brak rekrutacji dla tego wyszukiwania.")).toBeInTheDocument();
  });
});

describe("RecruitmentScopePicker — szukanie i wybór", () => {
  it("szuka na serwerze, domyślnie wśród otwartych, z tablicami jako powtarzanym parametrem", async () => {
    const user = userEvent.setup();
    serve(() => ({ items: [OPEN_JOB], clients: [], total: 1 }));
    renderPicker();
    await user.click(screen.getByRole("button", { name: /Wszystkie rekrutacje/ }));
    await screen.findByText("Java Developer");
    expect(searchCalls()[0]).toEqual({ q: undefined, status: "open", limit: 50 });

    await user.type(screen.getByPlaceholderText(/Szukaj po nazwie/), "bank");
    await waitFor(() => expect(searchCalls().at(-1)).toMatchObject({ q: "bank", status: "open" }));
    const lastConfig = get.mock.calls.at(-1)?.[1] as { paramsSerializer?: unknown };
    expect(lastConfig.paramsSerializer).toEqual({ indexes: null });
  });

  it("wiersz pokazuje klienta, numer i status; kliknięcie zaznacza kilka rekrutacji", async () => {
    const user = userEvent.setup();
    serve(
      () => ({ items: [OPEN_JOB, CLOSED_JOB], clients: [], total: 2 }),
      { items: [OPEN_JOB, CLOSED_JOB], clients: [], total: 2 },
    );
    const { onChange } = renderPicker();
    await user.click(screen.getByRole("button", { name: /Wszystkie rekrutacje/ }));

    const open = await screen.findByRole("option", { name: /Bank Alfa · #2143/ });
    expect(within(open).getByText("Otwarta")).toBeInTheDocument();
    const closed = screen.getByRole("option", { name: /Bank Alfa · #1764/ });
    expect(within(closed).getByText("Zamknięta")).toBeInTheDocument();
    expect(open).toHaveAttribute("aria-checked", "false");

    await user.click(open);
    expect(onChange).toHaveBeenLastCalledWith([2143], []);
    await user.click(await screen.findByRole("option", { name: /Bank Alfa · #1764/ }));
    expect(onChange).toHaveBeenLastCalledWith([2143, 1764], []);
    await waitFor(() =>
      expect(screen.getByRole("option", { name: /Bank Alfa · #2143/ })).toHaveAttribute(
        "aria-checked",
        "true",
      ),
    );
    expect(screen.getByRole("button", { name: /Wybrano: 2/ })).toBeInTheDocument();
  });

  it("„Wszystkie rekrutacje klienta” to jedna pozycja — zakres klienta, nie lista numerów", async () => {
    const user = userEvent.setup();
    serve(
      () => ({ items: [OPEN_JOB], clients: [BANK], total: 1 }),
      { items: [], clients: [BANK], total: 0 },
    );
    const { onChange } = renderPicker();
    await user.click(screen.getByRole("button", { name: /Wszystkie rekrutacje/ }));
    await user.type(screen.getByPlaceholderText(/Szukaj po nazwie/), "bank");

    const whole = await screen.findByRole("option", {
      name: /Wszystkie rekrutacje klienta Bank Alfa/,
    });
    expect(within(whole).getByText(/3 rekrutacje/)).toBeInTheDocument();
    await user.click(whole);
    expect(onChange).toHaveBeenLastCalledWith([], [3]);
  });

  it("przełącznik statusu pyta serwer o zamknięte, a Enter na nim niczego nie zaznacza", async () => {
    const user = userEvent.setup();
    serve(() => ({ items: [OPEN_JOB], clients: [], total: 1 }));
    const { onChange } = renderPicker();
    await user.click(screen.getByRole("button", { name: /Wszystkie rekrutacje/ }));
    await screen.findByText("Java Developer");

    await user.click(screen.getByRole("radio", { name: "Zamknięte" }));
    await waitFor(() => expect(searchCalls().at(-1)).toMatchObject({ status: "closed" }));
    await user.keyboard("{Enter}");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("mówi, że lista jest ucięta, i jak ją zawęzić", async () => {
    const user = userEvent.setup();
    serve(() => ({ items: [OPEN_JOB], clients: [], total: 120 }));
    renderPicker();
    await user.click(screen.getByRole("button", { name: /Wszystkie rekrutacje/ }));
    expect(await screen.findByText("Pokazano 1 z 120 — zawęź wyszukiwanie.")).toBeInTheDocument();
  });
});

describe("RecruitmentScopePicker — klawiatura w stopce", () => {
  it("Enter na „Wyczyść” czyści, a na „Gotowe” zamyka — nie zaznacza podświetlonego wiersza", async () => {
    const user = userEvent.setup();
    serve(
      () => ({ items: [OPEN_JOB], clients: [], total: 1 }),
      { items: [CLOSED_JOB], clients: [BANK], total: 1 },
    );
    // Dwie wybrane pozycje: przełączenie podświetlonego wiersza nie da pustego wyboru.
    const { onChange } = renderPicker({ ids: [1764], clients: [3] });
    await user.click(await screen.findByRole("button", { name: /Wybrano: 2/ }));
    await screen.findByRole("option", { name: /Bank Alfa · #2143/ });

    screen.getByRole("button", { name: "Wyczyść" }).focus();
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenLastCalledWith([], []);

    onChange.mockClear();
    screen.getByRole("button", { name: "Gotowe" }).focus();
    await user.keyboard("{Enter}");
    expect(onChange).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByRole("option", { name: /Bank Alfa · #2143/ })).toBeNull(),
    );
  });
});

describe("RecruitmentScopePicker — wybrane pozycje", () => {
  it("przycisk nazywa jedyną wybraną pozycję, a etykiety pyta po identyfikatorach", async () => {
    serve(
      () => ({ items: [], clients: [], total: 0 }),
      { items: [CLOSED_JOB], clients: [], total: 1 },
    );
    renderPicker({ ids: [1764] });
    expect(
      await screen.findByRole("button", { name: /Java Developer · Bank Alfa · #1764/ }),
    ).toBeInTheDocument();
    const labelCall = get.mock.calls
      .map((call) => (call[1] as { params?: Params }).params ?? {})
      .find(isLabels);
    expect(labelCall).toEqual({ ids: [1764], client_ids: [] });
  });

  it("wybrane spoza bieżącej listy stoją w grupie „Wybrane” i dają się odznaczyć", async () => {
    const user = userEvent.setup();
    serve(
      () => ({ items: [OPEN_JOB], clients: [], total: 1 }),
      { items: [CLOSED_JOB], clients: [BANK], total: 1 },
    );
    const { onChange } = renderPicker({ ids: [1764], clients: [3] });
    await user.click(await screen.findByRole("button", { name: /Wybrano: 2/ }));

    const chosen = await screen.findByRole("group", { name: "Wybrane" });
    await user.click(
      within(chosen).getByRole("option", { name: /Wszystkie rekrutacje klienta Bank Alfa/ }),
    );
    expect(onChange).toHaveBeenLastCalledWith([1764], []);

    await user.click(screen.getByRole("button", { name: "Wyczyść" }));
    expect(onChange).toHaveBeenLastCalledWith([], []);
  });
});
