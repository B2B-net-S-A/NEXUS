import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: { extractOrderPdf: vi.fn() },
}));

import { dlPortalApi } from "@/lib/api/dlPortal";
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
  status: "active",
  status_label: "Aktywne",
  closure_date: null,
  closure_reason: null,
  is_cost_based: false,
  budget_amount: null,
  budget_used: null,
  budget_remaining: null,
  budget_manual_adjustment: null,
  predecessor_group_id: null,
  can_add_consultant: true,
  lines: [],
  active_consultants: 0,
  event_count: 0,
};

function renderModal(onSubmit = vi.fn(), group: OrderGroupRead = GROUP) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ConsultantLineModal
        open
        onOpenChange={vi.fn()}
        clientId={7}
        group={group}
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


// ── PDF + odczyt danych (ticket §4-5) ────────────────────────────────────────

function extraction(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      title: "445",
      start_date: "2026-04-01",
      end_date: "2026-09-30",
      rate_client: 1300,
      rate_unit: "day",
      total_value: null,
      currency: "PLN",
      md_total: 60,
      uncertain: false,
      uncertain_reasons: [],
      fields_confidence: {},
      source: "claude",
      ...overrides,
    },
  };
}

function addPdf() {
  const input = screen.getByLabelText(/Dodaj PDF do zamówienia/i);
  const file = new File(["x"], "zamowienie.pdf", { type: "application/pdf" });
  fireEvent.change(input, { target: { files: [file] } });
  return file;
}

describe("ConsultantLineModal — odczyt PDF", () => {
  beforeEach(() => {
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: { options: [], total: 0 },
    } as never);
  });

  it("dodanie pliku NIE uruchamia odczytu — przycisk włącza się dopiero po pliku", async () => {
    renderModal();
    const button = screen.getByRole("button", {
      name: /Zczytaj dane z dokumentu/i,
    });
    expect(button).toBeDisabled();
    addPdf();
    expect(button).toBeEnabled();
    expect(dlPortalApi.extractOrderPdf).not.toHaveBeenCalled();
  });

  it("odczyt wypełnia puste pola bez pytania (nie ma czego nadpisać)", async () => {
    // `start_date` zgodne z okresem zamówienia: modal prefilluje je z grupy,
    // więc inna data byłaby PRAWDZIWĄ rozbieżnością i słusznie otwierała
    // dialog — ten test sprawdza ścieżkę bez konfliktu.
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction({ start_date: "2026-03-01", end_date: null }) as never,
    );
    renderModal();
    addPdf();
    await userEvent.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );

    await waitFor(() =>
      expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("1300"),
    );
    // „Liczba MD" jest też etykietą radia trybu budżetu — bierzemy POLE.
    expect(screen.getByRole("textbox", { name: "Liczba MD" })).toHaveValue("60");
    expect(
      screen.queryByText(/Odczytane dane różnią się od wpisanych/i),
    ).not.toBeInTheDocument();
  });

  it("rozbieżność z ręcznym wpisem PYTA i nic nie zmienia przed odpowiedzią", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction() as never,
    );
    renderModal();

    const revenue = screen.getByLabelText(/Stawka przychodowa/i);
    await userEvent.type(revenue, "1200");
    addPdf();
    await userEvent.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );

    expect(
      await screen.findByText(/Odczytane dane różnią się od wpisanych/i),
    ).toBeInTheDocument();
    // Nic nie zostało jeszcze nadpisane — to cała treść obietnicy dialogu.
    expect(revenue).toHaveValue("1200");

    await userEvent.click(
      screen.getByRole("button", { name: /Tak — zapisz dane z dokumentu/i }),
    );
    await waitFor(() => expect(revenue).toHaveValue("1300"));
  });

  it("odmowa zostawia dane wpisane ręcznie", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction() as never,
    );
    renderModal();

    const revenue = screen.getByLabelText(/Stawka przychodowa/i);
    await userEvent.type(revenue, "1200");
    addPdf();
    await userEvent.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: /Nie — zostaw wpisane ręcznie/i }),
    );

    expect(revenue).toHaveValue("1200");
  });

  it("baner „Sprawdź dane!\" pojawia się przy niepewnym odczycie", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction({
        uncertain: true,
        uncertain_reasons: ["Nie znaleziono jednoznacznej daty końca"],
      }) as never,
    );
    renderModal();
    addPdf();
    await userEvent.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );

    expect(await screen.findByText("Sprawdź dane!")).toBeInTheDocument();
    expect(
      screen.getByText(/Nie znaleziono jednoznacznej daty końca/),
    ).toBeInTheDocument();
  });

  it("zamówienie KOSZTOWE nie pyta o budżet MD przy konsultancie", async () => {
    renderModal(vi.fn(), { ...GROUP, is_cost_based: true });
    expect(
      screen.getByText(/rozliczane kwotą wspólną dla wszystkich konsultantów/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "Liczba MD" }),
    ).not.toBeInTheDocument();
  });
});
