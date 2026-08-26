import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ConsultantLineModal,
  type LineFormValues,
} from "@/components/client-profile/orders/ConsultantLineModal";
import type {
  ConsultantOption,
  OrderGroupRead,
  OrderLineRead,
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
  suggested_rate_cost: 560,
  has_different_client_contract_rates: false,
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
  suggested_rate_cost: null,
  has_different_client_contract_rates: false,
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
  is_md_budget_based: false,
  budget_amount: null,
  budget_used: null,
  budget_remaining: null,
  budget_manual_adjustment: null,
  md_budget_total: null,
  md_budget_used: null,
  md_budget_remaining: null,
  md_budget_manual_adjustment: null,
  predecessor_group_id: null,
  filename: null,
  has_file: false,
  content_type: null,
  size_bytes: null,
  file_uploaded_at: null,
  can_add_consultant: true,
  lines: [],
  active_consultants: 0,
  event_count: 0,
  future_orders: [],
};

const LINE: OrderLineRead = {
  id: 101,
  group_id: GROUP.id,
  contract_id: FROM_CLIENT.contract_id as number,
  candidate_id: FROM_CLIENT.candidate_id,
  consultant_name: FROM_CLIENT.full_name,
  job_id: null,
  job_title: null,
  status: "active",
  is_active: true,
  start_date: GROUP.start_date,
  end_date: null,
  rate_cost: 560,
  rate_revenue: 1200,
  input_value: 50,
  input_mode: "md",
  md_total: 50,
  md_remaining: 40,
  md_manual_adjustment: 0,
  predecessor_order_id: null,
  predecessor_consultant_name: null,
  invoiced_total: null,
  unsettled_total: null,
  missing_consumption_month: null,
};

interface RenderModalOptions {
  line?: OrderLineRead | null;
  onAdjustRemaining?: (mdRemaining: number) => void;
}

function renderModal(
  onSubmit = vi.fn(),
  group: OrderGroupRead = GROUP,
  { line = null, onAdjustRemaining }: RenderModalOptions = {},
) {
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
        line={line}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
        onAdjustRemaining={onAdjustRemaining}
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
  const cost = screen.getByRole("textbox", { name: /Stawka kosztowa/ });
  await user.clear(cost);
  await user.type(cost, "1000");
  await fillRevenueAndBudget(user);
}

async function fillRevenueAndBudget(user: ReturnType<typeof setupUser>) {
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

  it("wypełnia koszt stawką z aktywnego kontraktu bieżącego klienta", async () => {
    const user = setupUser();
    renderModal();

    await user.click(await screen.findByRole("button", { name: /Barbara Nowak/ }));

    expect(
      screen.getByRole("textbox", { name: /Stawka kosztowa/ }),
    ).toHaveValue("560");
  });

  it("pokazuje godzinową stawkę kontraktu 60 bez normalizacji 160/22 i zapisuje 480 PLN/MD", async () => {
    const user = setupUser();
    const onSubmit = vi.fn();
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: {
        options: [
          {
            ...FROM_CLIENT,
            full_name: "Katarzyna Maszewska",
            first_name: "Katarzyna",
            last_name: "Maszewska",
            // Legacy pozostaje kanoniczne PLN/MD dla starego frontendu.
            suggested_rate_cost: 480,
            suggested_contract_rate_cost: 60,
            suggested_rate_cost_unit: "hourly",
            suggested_rate_cost_currency: "PLN",
            suggested_rate_cost_rate_to_pln: 1,
          },
        ],
        total: 1,
      },
    } as never);
    renderModal(onSubmit);

    await user.click(
      await screen.findByRole("button", { name: /Katarzyna Maszewska/ }),
    );

    expect(
      screen.getByRole("textbox", { name: /Stawka kosztowa/ }),
    ).toHaveValue("60");
    const costUnits = screen.getByRole("group", {
      name: "Jednostka stawki kosztowej",
    });
    expect(
      within(costUnits).getByRole("button", { name: "godzinowa (zł/h)" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Zapis w PLN\/MD: 480 zł/)).toBeInTheDocument();

    await fillRevenueAndBudget(user);
    await user.click(screen.getByRole("button", { name: "Dodaj konsultanta" }));

    expect((onSubmit.mock.calls[0][0] as LineFormValues).rate_cost).toBe(480);
  });

  it("pokazuje miesięczną stawkę kontraktu 1:1 i dopiero przy zapisie dzieli ją przez 22 MD", async () => {
    const user = setupUser();
    const onSubmit = vi.fn();
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: {
        options: [
          {
            ...FROM_CLIENT,
            suggested_rate_cost: 46.59,
            suggested_contract_rate_cost: 1024.87,
            suggested_rate_cost_unit: "monthly",
            suggested_rate_cost_currency: "PLN",
            suggested_rate_cost_rate_to_pln: 1,
          },
        ],
        total: 1,
      },
    } as never);
    renderModal(onSubmit);

    await user.click(await screen.findByRole("button", { name: /Barbara Nowak/ }));

    expect(
      screen.getByRole("textbox", { name: /Stawka kosztowa/ }),
    ).toHaveValue("1024.87");
    const costUnits = screen.getByRole("group", {
      name: "Jednostka stawki kosztowej",
    });
    expect(
      within(costUnits).getByRole("button", { name: "miesięczna (zł/mc)" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Zapis w PLN\/MD: 46\.59 zł/)).toBeInTheDocument();

    await fillRevenueAndBudget(user);
    await user.click(screen.getByRole("button", { name: "Dodaj konsultanta" }));

    expect((onSubmit.mock.calls[0][0] as LineFormValues).rate_cost).toBe(46.59);
  });

  it("pokazuje walutę kontraktu i stosuje przekazany kurs dopiero do zapisu PLN/MD", async () => {
    const user = setupUser();
    const onSubmit = vi.fn();
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: {
        options: [
          {
            ...FROM_CLIENT,
            suggested_rate_cost: 3400,
            suggested_contract_rate_cost: 100,
            suggested_rate_cost_unit: "hourly",
            suggested_rate_cost_currency: "EUR",
            suggested_rate_cost_rate_to_pln: 4.25,
          },
        ],
        total: 1,
      },
    } as never);
    renderModal(onSubmit);

    await user.click(await screen.findByRole("button", { name: /Barbara Nowak/ }));

    expect(
      screen.getByRole("textbox", { name: "Stawka kosztowa (EUR) *" }),
    ).toHaveValue("100");
    const costUnits = screen.getByRole("group", {
      name: "Jednostka stawki kosztowej",
    });
    expect(
      within(costUnits).getByRole("button", { name: "godzinowa (EUR/h)" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByText(/Zapis w PLN\/MD: 3400 zł \(kurs EUR→PLN: 4\.25\)/),
    ).toBeInTheDocument();

    await fillRevenueAndBudget(user);
    await user.click(screen.getByRole("button", { name: "Dodaj konsultanta" }));

    expect((onSubmit.mock.calls[0][0] as LineFormValues).rate_cost).toBe(3400);
  });

  it("pozwala zmienić podpowiedzianą stawkę tylko dla tej linii", async () => {
    const user = setupUser();
    const onSubmit = renderModal();

    await user.click(await screen.findByRole("button", { name: /Barbara Nowak/ }));
    const cost = screen.getByRole("textbox", { name: /Stawka kosztowa/ });
    await user.clear(cost);
    await user.type(cost, "575");
    await user.type(
      screen.getByRole("textbox", { name: /Stawka przychodowa/ }),
      "1200",
    );
    await user.type(screen.getByRole("textbox", { name: "Liczba MD" }), "50");
    await user.click(screen.getByRole("button", { name: "Dodaj konsultanta" }));

    expect((onSubmit.mock.calls[0][0] as LineFormValues).rate_cost).toBe(575);
  });

  it("ostrzega przy różnych stawkach kontraktów, zachowując aktywną jako domyślną", async () => {
    const user = setupUser();
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: {
        options: [
          { ...FROM_CLIENT, has_different_client_contract_rates: true },
        ],
        total: 1,
      },
    } as never);
    renderModal();

    await user.click(await screen.findByRole("button", { name: /Barbara Nowak/ }));

    expect(screen.getByRole("status")).toHaveTextContent(
      /kontrakty z różnymi stawkami/i,
    );
    expect(
      screen.getByRole("textbox", { name: /Stawka kosztowa/ }),
    ).toHaveValue("560");
  });

  it("bez kontraktu u klienta zostawia koszt pusty i nie pokazuje ostrzeżenia", async () => {
    const user = setupUser();
    renderModal();

    await user.click(await screen.findByRole("button", { name: /Adam Zielinski/ }));

    expect(
      screen.getByRole("textbox", { name: /Stawka kosztowa/ }),
    ).toHaveValue("");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
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

function addPdf(name = "zamowienie.pdf") {
  const input = screen.getByLabelText(/Dodaj PDF do zamówienia/i);
  const file = new File([name], name, { type: "application/pdf" });
  fireEvent.change(input, { target: { files: [file] } });
  return file;
}

describe("ConsultantLineModal — odczyt PDF", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
      data: { options: [FROM_BASE, FROM_CLIENT], total: 2 },
    } as never);
  });

  it("bez wybranej osoby plik nie aktywuje odczytu", async () => {
    renderModal();
    const button = screen.getByRole("button", {
      name: /Zczytaj dane z dokumentu/i,
    });
    expect(button).toBeDisabled();
    addPdf();
    expect(button).toBeDisabled();
    expect(
      screen.getByText(
        /Najpierw wybierz konsultanta, którego dane mają zostać odczytane/i,
      ),
    ).toBeInTheDocument();
    expect(dlPortalApi.extractOrderPdf).not.toHaveBeenCalled();
  });

  it.each([
    {
      first_name: "",
      last_name: "Kowalska",
      missing: "imię",
      full_name: "Kowalska",
    },
    {
      first_name: "Anna",
      last_name: "",
      missing: "nazwisko",
      full_name: "Anna",
    },
  ])(
    "nie aktywuje odczytu, gdy w profilu brakuje pola $missing",
    async ({ first_name, last_name, missing, full_name }) => {
      vi.mocked(orderGroupsApi.consultantOptions).mockResolvedValue({
        data: {
          options: [
            {
              ...FROM_BASE,
              first_name,
              last_name,
              full_name,
            },
          ],
          total: 1,
        },
      } as never);
      const user = setupUser();
      renderModal();
      await user.click(
        await screen.findByRole("button", { name: new RegExp(full_name, "i") }),
      );
      addPdf();

      expect(
        screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
      ).toBeDisabled();
      expect(
        screen.getByText(
          new RegExp(
            `Uzupełnij ${missing} w profilu konsultanta, aby odczytać dane z dokumentu`,
            "i",
          ),
        ),
      ).toBeInTheDocument();
      expect(
        screen.queryByText(/Najpierw wybierz konsultanta/i),
      ).not.toBeInTheDocument();
      expect(dlPortalApi.extractOrderPdf).not.toHaveBeenCalled();
    },
  );

  it("w edycji blokuje odczyt przy jednoznacznie niepełnej nazwie konsultanta", () => {
    renderModal(vi.fn(), GROUP, {
      line: { ...LINE, consultant_name: "Kowalska" },
    });
    addPdf();

    expect(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    ).toBeDisabled();
    expect(
      screen.getByText(
        /Uzupełnij brakujące imię lub nazwisko w profilu konsultanta/i,
      ),
    ).toBeInTheDocument();
    expect(dlPortalApi.extractOrderPdf).not.toHaveBeenCalled();
  });

  it("w edycji mapuje autorytatywny błąd 422 niepełnego profilu", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockRejectedValueOnce({
      response: {
        status: 422,
        data: { detail: "Kandydat nie ma imienia i nazwiska do dopasowania" },
      },
    } as never);
    const user = setupUser();
    // Wieloczłonowe nazwisko nie pozwala frontowi ustalić, czy osobne pola
    // profilu są kompletne; rozstrzyga to endpoint na podstawie Candidate.
    renderModal(vi.fn(), GROUP, {
      line: { ...LINE, consultant_name: "Van der Berg" },
    });
    const file = addPdf();
    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );

    await waitFor(() =>
      expect(dlPortalApi.extractOrderPdf).toHaveBeenCalledWith(7, file, 5),
    );
    expect(
      await screen.findByText(
        /Uzupełnij brakujące imię lub nazwisko w profilu konsultanta/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Nie udało się odczytać danych z dokumentu/i),
    ).not.toBeInTheDocument();
  });

  it("wysyła candidate_id wybranej osoby i wypełnia jej puste pola", async () => {
    // `start_date` zgodne z okresem zamówienia: modal prefilluje je z grupy,
    // więc inna data byłaby PRAWDZIWĄ rozbieżnością i słusznie otwierała
    // dialog — ten test sprawdza ścieżkę bez konfliktu.
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction({ start_date: "2026-03-01", end_date: null }) as never,
    );
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    const file = addPdf();
    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );

    await waitFor(() =>
      expect(dlPortalApi.extractOrderPdf).toHaveBeenCalledWith(7, file, 5),
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

  it("przy edycji wysyła candidate_id istniejącej linii", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction({
        start_date: GROUP.start_date,
        end_date: null,
        rate_client: LINE.rate_revenue,
        md_total: LINE.input_value,
      }) as never,
    );
    const user = setupUser();
    renderModal(vi.fn(), GROUP, { line: LINE });
    const file = addPdf();

    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );

    await waitFor(() =>
      expect(dlPortalApi.extractOrderPdf).toHaveBeenCalledWith(7, file, 5),
    );
  });

  it("zmiana osoby czyści nadal automatyczne revenue i MD oraz zmienia target", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf)
      .mockResolvedValueOnce(
        extraction({ start_date: GROUP.start_date, end_date: null }) as never,
      )
      .mockResolvedValueOnce(
        extraction({
          start_date: GROUP.start_date,
          end_date: null,
          rate_client: 1400,
          md_total: 70,
        }) as never,
      );
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    const file = addPdf();
    const extractButton = screen.getByRole("button", {
      name: /Zczytaj dane z dokumentu/i,
    });

    await user.click(extractButton);
    await waitFor(() =>
      expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("1300"),
    );
    expect(screen.getByRole("textbox", { name: "Liczba MD" })).toHaveValue("60");

    await user.click(screen.getByRole("button", { name: "Zmień" }));
    await user.click(
      await screen.findByRole("button", { name: /Adam Zielinski/ }),
    );

    expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "Liczba MD" })).toHaveValue("");

    await user.click(extractButton);
    await waitFor(() =>
      expect(dlPortalApi.extractOrderPdf).toHaveBeenNthCalledWith(2, 7, file, 9),
    );
    await waitFor(() =>
      expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("1400"),
    );
  });

  it("respektuje godzinową jednostkę PDF i zapisuje stawkę po konwersji do MD", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction({
        start_date: GROUP.start_date,
        end_date: null,
        rate_client: 150,
        rate_unit: "hour",
      }) as never,
    );
    const user = setupUser();
    const onSubmit = renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    addPdf();

    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );

    const revenueUnits = screen.getByRole("group", {
      name: "Jednostka stawki przychodowej",
    });
    expect(
      within(revenueUnits).getByRole("button", { name: "godzinowa (zł/h)" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("150");

    await user.click(screen.getByRole("button", { name: "Dodaj konsultanta" }));
    expect((onSubmit.mock.calls[0][0] as LineFormValues).rate_revenue).toBe(1200);
  });

  it("pyta przed zmianą tej samej liczby z MD na stawkę godzinową", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction({
        start_date: GROUP.start_date,
        end_date: null,
        rate_client: 150,
        rate_unit: "hour",
        md_total: null,
      }) as never,
    );
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    await user.type(screen.getByLabelText(/Stawka przychodowa/i), "150");
    addPdf();

    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );

    const conflictDialog = await screen.findByRole("dialog", {
      name: /Odczytane dane różnią się od wpisanych/i,
    });
    expect(conflictDialog).toHaveTextContent("Jednostka stawki przychodowej");
    expect(conflictDialog).toHaveTextContent("MD 8h (zł/MD)");
    expect(conflictDialog).toHaveTextContent("godzinowa (zł/h)");
    await user.click(
      within(conflictDialog).getByRole("button", {
        name: /Nie — zostaw wpisane ręcznie/i,
      }),
    );
    const revenueUnits = screen.getByRole("group", {
      name: "Jednostka stawki przychodowej",
    });
    expect(
      within(revenueUnits).getByRole("button", { name: "MD 8h (zł/MD)" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("nowy PDF resetuje jednostkę poprzedniej stawki automatycznej", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction({
        start_date: GROUP.start_date,
        end_date: null,
        rate_client: 150,
        rate_unit: "hour",
      }) as never,
    );
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    addPdf("A-godzinowy.pdf");
    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("150"),
    );

    addPdf("B-nowy.pdf");

    expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("");
    const revenueUnits = screen.getByRole("group", {
      name: "Jednostka stawki przychodowej",
    });
    expect(
      within(revenueUnits).getByRole("button", { name: "MD 8h (zł/MD)" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("nowy PDF nie usuwa identycznych wartości istniejących przed odczytem", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction({
        start_date: GROUP.start_date,
        end_date: null,
        rate_client: 1300,
        rate_unit: "day",
        md_total: 60,
      }) as never,
    );
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    await user.type(screen.getByLabelText(/Stawka przychodowa/i), "1300");
    await user.type(screen.getByRole("textbox", { name: "Liczba MD" }), "60");
    addPdf("A-zgodny.pdf");
    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );
    await waitFor(() => expect(dlPortalApi.extractOrderPdf).toHaveBeenCalled());

    addPdf("B-nowy.pdf");

    expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("1300");
    expect(screen.getByRole("textbox", { name: "Liczba MD" })).toHaveValue(
      "60",
    );
  });

  it("ponowny odczyt zachowuje pochodzenie danych automatycznych", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction({ start_date: GROUP.start_date }) as never,
    );
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    addPdf("A-dwa-odczyty.pdf");
    const extractButton = screen.getByRole("button", {
      name: /Zczytaj dane z dokumentu/i,
    });
    await user.click(extractButton);
    await waitFor(() =>
      expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("1300"),
    );

    await user.click(extractButton);
    await waitFor(() =>
      expect(dlPortalApi.extractOrderPdf).toHaveBeenCalledTimes(2),
    );
    addPdf("B-nowy.pdf");

    expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "Liczba MD" })).toHaveValue("");
    expect(screen.getByLabelText(/Koniec \(puste = bezterminowo\)/i)).toHaveValue(
      "",
    );
  });

  it("ponowny niejednoznaczny odczyt usuwa wyłącznie poprzednie dane automatyczne", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf)
      .mockResolvedValueOnce(
        extraction({ start_date: GROUP.start_date }) as never,
      )
      .mockResolvedValueOnce(
        extraction({
          start_date: null,
          end_date: null,
          rate_client: null,
          rate_unit: null,
          md_total: null,
          uncertain: true,
          uncertain_reasons: ["Nie znaleziono jednoznacznej pozycji konsultanta"],
        }) as never,
      );
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    addPdf("ten-sam.pdf");
    const extractButton = screen.getByRole("button", {
      name: /Zczytaj dane z dokumentu/i,
    });
    await user.click(extractButton);
    await waitFor(() =>
      expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("1300"),
    );

    await user.click(extractButton);

    expect(await screen.findByText("Sprawdź dane!")).toBeInTheDocument();
    expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "Liczba MD" })).toHaveValue("");
    expect(screen.getByLabelText(/Koniec \(puste = bezterminowo\)/i)).toHaveValue(
      "",
    );
    expect(screen.getByLabelText(/Start/i)).toHaveValue(GROUP.start_date);
  });

  it("ręczna zmiana trybu budżetu chroni wartość przed czyszczeniem PDF", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction({ start_date: GROUP.start_date, end_date: null }) as never,
    );
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    addPdf("A-md.pdf");
    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Liczba MD" })).toHaveValue(
        "60",
      ),
    );

    await user.click(screen.getByRole("radio", { name: /Kwota zamówienia/i }));
    expect(screen.getByRole("textbox", { name: "Kwota zamówienia" })).toHaveValue(
      "60",
    );
    addPdf("B-nowy.pdf");

    expect(screen.getByRole("textbox", { name: "Kwota zamówienia" })).toHaveValue(
      "60",
    );
  });

  it("pyta przed zamianą ręcznej kwoty zamówienia na liczbę MD z PDF", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction({ start_date: GROUP.start_date, end_date: null }) as never,
    );
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    await user.click(screen.getByRole("radio", { name: /Kwota zamówienia/i }));
    await user.type(
      screen.getByRole("textbox", { name: "Kwota zamówienia" }),
      "60",
    );
    addPdf("kwota-vs-md.pdf");

    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );

    const conflictDialog = await screen.findByRole("dialog", {
      name: /Odczytane dane różnią się od wpisanych/i,
    });
    expect(conflictDialog).toHaveTextContent("Budżet konsultanta");
    expect(conflictDialog).toHaveTextContent("60 zł (kwota zamówienia)");
    expect(conflictDialog).toHaveTextContent("60 MD (liczba MD)");
    await user.click(
      within(conflictDialog).getByRole("button", {
        name: /Nie — zostaw wpisane ręcznie/i,
      }),
    );
    expect(screen.getByRole("textbox", { name: "Kwota zamówienia" })).toHaveValue(
      "60",
    );
  });

  it("respektuje miesięczną jednostkę PDF i zapisuje stawkę po konwersji do MD", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction({
        start_date: GROUP.start_date,
        end_date: null,
        rate_client: 12000,
        rate_unit: "month",
      }) as never,
    );
    const user = setupUser();
    const onSubmit = renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    addPdf();

    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );

    const revenueUnits = screen.getByRole("group", {
      name: "Jednostka stawki przychodowej",
    });
    expect(
      within(revenueUnits).getByRole("button", { name: "miesięczna (zł/mc)" }),
    ).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "Dodaj konsultanta" }));
    expect((onSubmit.mock.calls[0][0] as LineFormValues).rate_revenue).toBe(
      545.45,
    );
  });

  it("nowy PDF czyści niezmienione dane automatyczne poprzedniego pliku", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf)
      .mockResolvedValueOnce(
        extraction({ start_date: GROUP.start_date }) as never,
      )
      .mockResolvedValueOnce(
        extraction({
          start_date: GROUP.start_date,
          end_date: null,
          rate_client: null,
          rate_unit: null,
          md_total: null,
          uncertain: true,
          uncertain_reasons: ["Nie znaleziono konsultanta"],
        }) as never,
      );
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    addPdf("A.pdf");
    const button = screen.getByRole("button", {
      name: /Zczytaj dane z dokumentu/i,
    });
    await user.click(button);
    await waitFor(() =>
      expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("1300"),
    );
    expect(screen.getByRole("textbox", { name: "Liczba MD" })).toHaveValue("60");
    expect(screen.getByLabelText(/Koniec \(puste = bezterminowo\)/i)).toHaveValue(
      "2026-09-30",
    );

    addPdf("B.pdf");
    expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "Liczba MD" })).toHaveValue("");
    expect(screen.getByLabelText(/Koniec \(puste = bezterminowo\)/i)).toHaveValue(
      "",
    );

    await user.click(button);
    expect(await screen.findByText("Sprawdź dane!")).toBeInTheDocument();
    expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "Liczba MD" })).toHaveValue("");
  });

  it("odrzuca spóźniony wynik poprzedniego pliku tej samej osoby", async () => {
    let resolveFirst: ((value: ReturnType<typeof extraction>) => void) | undefined;
    const firstResponse = new Promise<ReturnType<typeof extraction>>((resolve) => {
      resolveFirst = resolve;
    });
    vi.mocked(dlPortalApi.extractOrderPdf).mockReturnValueOnce(
      firstResponse as never,
    );
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    addPdf("wolny-A.pdf");
    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );
    await waitFor(() => expect(dlPortalApi.extractOrderPdf).toHaveBeenCalledOnce());

    addPdf("aktualny-B.pdf");
    await act(async () => {
      resolveFirst?.(
        extraction({ start_date: GROUP.start_date, end_date: null }),
      );
      await firstResponse;
    });

    await waitFor(() =>
      expect(screen.getByLabelText(/Stawka przychodowa/i)).toHaveValue(""),
    );
    expect(screen.getByRole("textbox", { name: "Liczba MD" })).toHaveValue("");
  });

  it("porównuje odpowiedź z ręcznymi zmianami wykonanymi podczas requestu", async () => {
    let resolveExtraction:
      | ((value: ReturnType<typeof extraction>) => void)
      | undefined;
    const response = new Promise<ReturnType<typeof extraction>>((resolve) => {
      resolveExtraction = resolve;
    });
    vi.mocked(dlPortalApi.extractOrderPdf).mockReturnValue(response as never);
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    addPdf("wolny.pdf");
    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );
    await waitFor(() => expect(dlPortalApi.extractOrderPdf).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/Stawka przychodowa/i), "1200");
    await user.type(screen.getByRole("textbox", { name: "Liczba MD" }), "50");
    fireEvent.change(
      screen.getByLabelText(/Koniec \(puste = bezterminowo\)/i),
      { target: { value: "2026-10-31" } },
    );
    resolveExtraction?.(
      extraction({ start_date: GROUP.start_date, end_date: "2026-09-30" }),
    );

    const conflictDialog = await screen.findByRole("dialog", {
      name: /Odczytane dane różnią się od wpisanych/i,
    });
    expect(conflictDialog).toHaveTextContent("1200");
    expect(conflictDialog).toHaveTextContent("1300");
    expect(conflictDialog).toHaveTextContent("50");
    expect(conflictDialog).toHaveTextContent("60");
    expect(conflictDialog).toHaveTextContent("2026-10-31");
    expect(conflictDialog).toHaveTextContent("2026-09-30");
  });

  it("rozbieżność z ręcznym wpisem PYTA i nic nie zmienia przed odpowiedzią", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction() as never,
    );
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );

    const revenue = screen.getByLabelText(/Stawka przychodowa/i);
    await user.type(revenue, "1200");
    addPdf();
    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );

    expect(
      await screen.findByText(/Odczytane dane różnią się od wpisanych/i),
    ).toBeInTheDocument();
    // Nic nie zostało jeszcze nadpisane — to cała treść obietnicy dialogu.
    expect(revenue).toHaveValue("1200");

    await user.click(
      screen.getByRole("button", { name: /Tak — zapisz dane z dokumentu/i }),
    );
    await waitFor(() => expect(revenue).toHaveValue("1300"));
  });

  it("odmowa zostawia dane wpisane ręcznie", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction() as never,
    );
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );

    const revenue = screen.getByLabelText(/Stawka przychodowa/i);
    await user.type(revenue, "1200");
    addPdf();
    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );
    await user.click(
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
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    addPdf();
    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );

    expect(await screen.findByText("Sprawdź dane!")).toBeInTheDocument();
    expect(
      screen.getByText(/Nie znaleziono jednoznacznej daty końca/),
    ).toBeInTheDocument();
  });

  it("brak jednoznacznej osoby nie nadpisuje ręcznej stawki ani MD", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue(
      extraction({
        rate_client: null,
        md_total: null,
        uncertain: true,
        uncertain_reasons: [
          "Nie znaleziono jednoznacznej pozycji konsultanta",
        ],
      }) as never,
    );
    const user = setupUser();
    renderModal();
    await user.click(
      await screen.findByRole("button", { name: /Barbara Nowak/ }),
    );
    const revenue = screen.getByLabelText(/Stawka przychodowa/i);
    const md = screen.getByRole("textbox", { name: "Liczba MD" });
    await user.type(revenue, "1200");
    await user.type(md, "50");
    addPdf();

    await user.click(
      screen.getByRole("button", { name: /Zczytaj dane z dokumentu/i }),
    );

    expect(await screen.findByText("Sprawdź dane!")).toBeInTheDocument();
    expect(revenue).toHaveValue("1200");
    expect(md).toHaveValue("50");
  });

  it("edycja standardowej linii zachowuje liczbę MD w payloadzie", async () => {
    const user = setupUser();
    const onSubmit = renderModal(vi.fn(), GROUP, { line: LINE });
    const revenue = screen.getByLabelText(/Stawka przychodowa/i);
    await user.clear(revenue);
    await user.type(revenue, "1350");

    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    const payload = onSubmit.mock.calls[0][0] as LineFormValues;
    expect(payload.rate_revenue).toBe(1350);
    expect(payload.input_mode).toBe("md");
    expect(payload.input_value).toBe(50);
  });

  it.each([
    ["kosztowej", { ...GROUP, is_cost_based: true }],
    [
      "ze wspólną pulą MD",
      {
        ...GROUP,
        is_md_budget_based: true,
        md_budget_total: 100,
        md_budget_used: 20,
        md_budget_remaining: 80,
      },
    ],
  ])(
    "edycja linii %s wysyła same stawki i koniec, bez budżetu osoby",
    async (_label, group) => {
      const user = setupUser();
      const onSubmit = renderModal(vi.fn(), group, {
        line: {
          ...LINE,
          input_mode: null,
          input_value: null,
          md_total: null,
          md_remaining: null,
        },
      });
      const cost = screen.getByLabelText(/Stawka kosztowa/i);
      const revenue = screen.getByLabelText(/Stawka przychodowa/i);
      await user.clear(cost);
      await user.type(cost, "1100");
      await user.clear(revenue);
      await user.type(revenue, "1350");
      fireEvent.change(
        screen.getByLabelText(/Koniec \(puste = bezterminowo\)/i),
        { target: { value: "2026-12-31" } },
      );

      await user.click(screen.getByRole("button", { name: "Zapisz" }));

      const payload = onSubmit.mock.calls[0][0] as LineFormValues;
      expect(payload.rate_cost).toBe(1100);
      expect(payload.rate_revenue).toBe(1350);
      expect(payload.end_date).toBe("2026-12-31");
      expect(payload.input_mode).toBeUndefined();
      expect(payload.input_value).toBeUndefined();
    },
  );

  it("zamówienie KOSZTOWE nie pyta o budżet MD przy konsultancie", async () => {
    renderModal(vi.fn(), { ...GROUP, is_cost_based: true });
    expect(
      screen.getByText(/rozliczane kwotą wspólną dla wszystkich konsultantów/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "Liczba MD" }),
    ).not.toBeInTheDocument();
  });

  it("wspólna pula MD nie tworzy osobnego budżetu przy konsultancie", async () => {
    renderModal(vi.fn(), {
      ...GROUP,
      is_md_budget_based: true,
      md_budget_total: 100,
      md_budget_used: 20,
      md_budget_remaining: 80,
    });

    expect(
      screen.getByText(/wspólną pulę MD dla wszystkich konsultantów/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "Liczba MD" }),
    ).not.toBeInTheDocument();
  });

  it("standardowa linia w edycji pokazuje korektę pozostałych MD", () => {
    renderModal(vi.fn(), GROUP, {
      line: LINE,
      onAdjustRemaining: vi.fn(),
    });

    expect(screen.getByText("Korekta ręczna")).toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "Pozostałe MD" }),
    ).toBeInTheDocument();
  });

  it.each([
    ["kosztowe", { ...GROUP, is_cost_based: true }],
    [
      "ze wspólną pulą MD",
      {
        ...GROUP,
        is_md_budget_based: true,
        md_budget_total: 100,
        md_budget_used: 20,
        md_budget_remaining: 80,
      },
    ],
  ])("zamówienie %s ukrywa korektę pozostałych MD linii", (_label, group) => {
    renderModal(vi.fn(), group, {
      line: {
        ...LINE,
        input_value: null,
        md_total: null,
        md_remaining: null,
      },
      onAdjustRemaining: vi.fn(),
    });

    expect(screen.queryByText("Korekta ręczna")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "Pozostałe MD" }),
    ).not.toBeInTheDocument();
  });
});
