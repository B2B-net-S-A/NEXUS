import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ConsultantLineModal,
  type LineFormValues,
} from "@/components/client-profile/orders/ConsultantLineModal";
import type {
  ConsultantOption,
  OrderGroupRead,
} from "@/lib/api/orderGroups";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: { consultantOptions: vi.fn() },
  mdConsumptionApi: {},
}));

import { orderGroupsApi } from "@/lib/api/orderGroups";

const FROM_CLIENT: ConsultantOption = {
  candidate_id: 5,
  contract_id: 100,
  full_name: "Barbara Nowak",
  first_name: "Barbara",
  last_name: "Nowak",
  source: "client_recruitment",
  source_label: "Rekrutacja u klienta",
  job_title: "Analityk danych",
};

const FROM_BASE: ConsultantOption = {
  candidate_id: 9,
  contract_id: null,
  full_name: "Adam Zielinski",
  first_name: "Adam",
  last_name: "Zielinski",
  source: "nexus_base",
  source_label: "Baza Nexus",
  job_title: null,
};

const GROUP: OrderGroupRead = {
  id: 10,
  client_id: 7,
  order_number: "445",
  start_date: "2026-03-01",
  end_date: null,
  notes: null,
  created_at: "2026-03-01T10:00:00Z",
  lines: [],
  active_consultants: 0,
  event_count: 0,
};

function renderModal(onSubmit = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ConsultantLineModal
        open
        onOpenChange={vi.fn()}
        clientId={7}
        group={GROUP}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
      />
    </QueryClientProvider>,
  );
  return onSubmit;
}

/** Radix zdejmuje `pointer-events` z body na czas modala; bez tego userEvent
 *  odmawia kliknięcia czegokolwiek wewnątrz dialogu. */
function setupUser() {
  return userEvent.setup({ pointerEventsCheck: 0 });
}

/** Wypełnia stawki i budżet — wszystko poza wyborem osoby. */
async function fillRates(user: ReturnType<typeof setupUser>) {
  await user.type(screen.getByRole("textbox", { name: /Stawka kosztowa/ }), "1000");
  await user.type(
    screen.getByRole("textbox", { name: /Stawka przychodowa/ }),
    "1200",
  );
  // `getByRole`, nie `getByLabelText`: tę samą nazwę nosi radio wyboru trybu.
  await user.type(screen.getByRole("textbox", { name: "Liczba MD" }), "50");
}

describe("ConsultantLineModal — wybór konsultanta", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: { options: [FROM_BASE, FROM_CLIENT], total: 2 },
    } as never);
  });

  it("pokazuje jedną listę z dwóch źródeł, każdą pozycję z etykietą", async () => {
    renderModal();

    expect(await screen.findByText("Adam Zielinski")).toBeInTheDocument();
    expect(screen.getByText("Barbara Nowak")).toBeInTheDocument();
    expect(screen.getByText("Baza Nexus")).toBeInTheDocument();
    expect(screen.getByText("Rekrutacja u klienta")).toBeInTheDocument();
    // Kolejność ustala serwer (alfabetycznie po imieniu) — front jej nie miesza.
    const rows = screen.getAllByRole("button", { name: /Zielinski|Nowak/ });
    expect(rows[0]).toHaveTextContent("Adam Zielinski");
  });

  it("osoba z bazy Nexus jedzie jako candidate_id, bez contract_id", async () => {
    const user = setupUser();
    const onSubmit = renderModal();

    await user.click(await screen.findByRole("button", { name: /Adam Zielinski/ }));
    await fillRates(user);
    await user.click(screen.getByRole("button", { name: "Dodaj konsultanta" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const payload = onSubmit.mock.calls[0][0] as LineFormValues;
    expect(payload.candidate_id).toBe(9);
    // Serwer odrzuca oba pola naraz — wysłanie „na wszelki wypadek" obu
    // zamieniłoby poprawny formularz w 422.
    expect(payload.contract_id).toBeUndefined();
  });

  it("osoba z rekrutacji u klienta jedzie jako contract_id", async () => {
    const user = setupUser();
    const onSubmit = renderModal();

    await user.click(await screen.findByRole("button", { name: /Barbara Nowak/ }));
    await fillRates(user);
    await user.click(screen.getByRole("button", { name: "Dodaj konsultanta" }));

    const payload = onSubmit.mock.calls[0][0] as LineFormValues;
    expect(payload.contract_id).toBe(100);
    expect(payload.candidate_id).toBeUndefined();
  });

  it("wybór osoby bez kontraktu uprzedza, że powstanie szkic kontraktu", async () => {
    const user = setupUser();
    renderModal();

    await user.click(await screen.findByRole("button", { name: /Adam Zielinski/ }));
    expect(screen.getByText(/założy go w statusie/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Zmień" }));
    await user.click(await screen.findByRole("button", { name: /Barbara Nowak/ }));
    expect(screen.queryByText(/założy go w statusie/)).not.toBeInTheDocument();
  });

  it("awaria pobrania listy renderuje błąd z ponowieniem, NIE pustkę", async () => {
    // Pusta lista czyta się jak „nie ma takiej osoby w bazie" i kończy
    // założeniem duplikatu — awaria musi mieć własną gałąź.
    vi.mocked(orderGroupsApi.consultantOptions).mockRejectedValue(new Error("boom"));
    renderModal();

    expect(
      await screen.findByText(/Nie udało się wczytać listy konsultantów/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Brak aktywnych konsultantów/),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ponów" })).toBeInTheDocument();
  });

  it("pusty wynik wyszukiwania mówi co innego niż pusta baza", async () => {
    const user = setupUser();
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: { options: [], total: 0 },
    } as never);
    renderModal();

    expect(
      await screen.findByText("Brak aktywnych konsultantów do wyboru."),
    ).toBeInTheDocument();

    await user.type(
      screen.getByRole("textbox", { name: /Szukaj konsultanta/ }),
      "Jan Kowalski",
    );
    expect(
      await screen.findByText(/Brak osób pasujących do „Jan Kowalski"/),
    ).toBeInTheDocument();
  });

  it("szuka po całym imieniu i nazwisku — zapytanie idzie na serwer", async () => {
    const user = setupUser();
    renderModal();

    await screen.findByText("Adam Zielinski");
    await user.type(screen.getByRole("textbox", { name: /Szukaj konsultanta/ }), "Adam Zielinski");

    await waitFor(() =>
      expect(orderGroupsApi.consultantOptions).toHaveBeenCalledWith(
        7,
        "Adam Zielinski",
      ),
    );
  });

  it("przycięta lista mówi, ilu jest naprawdę", async () => {
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: { options: [FROM_BASE, FROM_CLIENT], total: 137 },
    } as never);
    renderModal();

    expect(
      await screen.findByText(/Pokazano 2 z 137 — zawęź wyszukiwanie/),
    ).toBeInTheDocument();
  });

  it("bez wybranej osoby nie da się zapisać linii", async () => {
    const user = setupUser();
    renderModal();

    await screen.findByText("Adam Zielinski");
    await fillRates(user);
    expect(screen.getByRole("button", { name: "Dodaj konsultanta" })).toBeDisabled();
  });
});
