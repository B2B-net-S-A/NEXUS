import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { B2BGeneratedContractRow } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  generated: vi.fn(),
  confirmFullySigned: vi.fn(),
  updateGenerated: vi.fn(),
  deleteGenerated: vi.fn(),
  downloadGenerated: vi.fn(),
  showActionToast: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showActionToast: mocks.showActionToast,
    showSuccess: mocks.showSuccess,
    showError: mocks.showError,
  }),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  b2bGeneratorApi: {
    generated: (...args: unknown[]) => mocks.generated(...args),
    confirmFullySigned: (...args: unknown[]) =>
      mocks.confirmFullySigned(...args),
    updateGenerated: (...args: unknown[]) => mocks.updateGenerated(...args),
    deleteGenerated: (...args: unknown[]) => mocks.deleteGenerated(...args),
    downloadGenerated: (...args: unknown[]) => mocks.downloadGenerated(...args),
  },
  extractErrorMsg: (error: unknown) =>
    error instanceof Error ? error.message : "Błąd",
  signingApi: {},
}));

import {
  GeneratedContractsTab,
  RecruitmentOptionsNotice,
} from "@/components/v2/pages/B2BContractGeneratorV2";

beforeAll(() => {
  // Radix Select potrzebuje tych API, których jsdom nie implementuje.
  for (const [name, value] of [
    ["hasPointerCapture", () => false],
    ["setPointerCapture", () => undefined],
    ["releasePointerCapture", () => undefined],
    ["scrollIntoView", () => undefined],
  ] as const) {
    if (!(name in Element.prototype)) {
      Object.defineProperty(Element.prototype, name, {
        configurable: true,
        value,
      });
    }
  }
});

function generatedRow(
  overrides: Partial<B2BGeneratedContractRow> = {},
): B2BGeneratedContractRow {
  return {
    id: 1,
    contract_number: "1471/2026",
    // `partner_name` to OSOBA; nazwa firmy jest w `partner_display_name`.
    // Celowo różne wartości, żeby test kolumny „Partner" nie przechodził
    // przypadkiem na tym, że oba pola trzymają ten sam string.
    partner_name: "Jan Kowalski",
    partner_display_name: "JK Software Jan Kowalski",
    partner_secondary_line: null,
    partner_nip: "1234563218",
    start_date: "2026-08-25",
    client_name: "Nordea Bank",
    language: "pl",
    signing_date: "2026-07-24",
    created_at: "2026-07-24T10:30:00Z",
    created_by_name: "Marta Rekruter",
    signature_status: "unsigned",
    signature_source: null,
    // Świeżo wygenerowana umowa jest „W trakcie" — `active` znaczy teraz
    // „podpisana obustronnie" i ustawia je wyłącznie potwierdzenie podpisu.
    contract_status: "in_progress",
    closure_reason: null,
    closure_reason_other: null,
    closure_date: null,
    can_change_status: true,
    candidate_id: null,
    job_id: null,
    client_id: null,
    contract_id: null,
    candidate_name: null,
    job_title: null,
    canonical_client_name: null,
    signed_at: null,
    signed_by_name: null,
    can_confirm_signed: false,
    blocked_reason: null,
    can_delete: true,
    can_edit: true,
    can_download: false,
    ...overrides,
  };
}

function renderTab(rows: B2BGeneratedContractRow[]) {
  mocks.generated.mockResolvedValue(rows);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <GeneratedContractsTab />
    </QueryClientProvider>,
  );
}

/**
 * `delay: null` wyłącza sztuczną pauzę między klawiszami. Domyślne opóźnienie
 * przy pełnym przebiegu suite'a (85 plików równolegle) potrafi przekroczyć
 * 5-sekundowy timeout i zamienić te testy w migoczące.
 */
const setupUser = () => userEvent.setup({ delay: null });

/** Wybierz opcję w Radix Select otwartym przez trigger o danej etykiecie. */
async function pickOption(
  user: ReturnType<typeof userEvent.setup>,
  triggerName: RegExp | string,
  optionName: RegExp | string,
) {
  await user.click(screen.getByRole("combobox", { name: triggerName }));
  await user.click(await screen.findByRole("option", { name: optionName }));
}

/**
 * `<input type="date">` ustawiamy jednym `change`, a nie 10 znakami przez
 * `user.type` — każdy znak to osobny re-render, a jsdom i tak nie odtwarza
 * natywnego parsowania segmentów daty.
 */
function setDate(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("GeneratedContractsTab — status umowy", () => {
  it("świeżo wygenerowana umowa pokazuje „W trakcie”, nie „Aktywna”", async () => {
    // Do 0223 rejestr twierdził „Aktywna" o umowie, która dopiero poszła do
    // podpisu — bo status brał się z defaultu kolumny.
    renderTab([generatedRow()]);
    expect(await screen.findByText("W trakcie")).toBeInTheDocument();
    expect(screen.queryByText("Aktywna")).not.toBeInTheDocument();
    expect(screen.queryByText("Zakończona")).not.toBeInTheDocument();
  });

  it("„Aktywna” to stan po potwierdzeniu podpisu, nie po wygenerowaniu", async () => {
    renderTab([generatedRow({ contract_status: "active" })]);
    expect(await screen.findByText("Aktywna")).toBeInTheDocument();
    expect(screen.queryByText("W trakcie")).not.toBeInTheDocument();
  });

  it("pokazuje powód i datę zakończenia zakończonej umowy", async () => {
    renderTab([
      generatedRow({
        contract_status: "closed",
        closure_reason: "project_completed",
        closure_date: "2026-08-31",
      }),
    ]);

    expect(await screen.findByText("Zakończona")).toBeInTheDocument();
    expect(
      screen.getByText(/Zakończenie projektu · 31\.08\.2026/),
    ).toBeInTheDocument();
  });

  it("powód sprzed migracji 0226 nadal ma etykietę, nie surowy klucz", async () => {
    // Produkcja ma zamknięte umowy z katalogiem sprzed zmiany. Usunięcie tych
    // etykiet zamieniłoby historyczny powód w puste miejsce albo w `termination`.
    renderTab([
      generatedRow({
        contract_status: "closed",
        closure_reason: "termination",
        closure_date: "2026-08-31",
      }),
    ]);

    expect(
      await screen.findByText(/Wypowiedzenie · 31\.08\.2026/),
    ).toBeInTheDocument();
  });

  it("dla powodu „Inne” pokazuje własny tekst, nie etykietę katalogową", async () => {
    renderTab([
      generatedRow({
        contract_status: "closed",
        closure_reason: "other",
        closure_reason_other: "Zmiana modelu współpracy",
        closure_date: "2026-09-01",
      }),
    ]);

    expect(
      await screen.findByText(/Zmiana modelu współpracy/),
    ).toBeInTheDocument();
  });

  it("„Zakończona” odsłania powód i datę, i wysyła komplet pól", async () => {
    const user = setupUser();
    mocks.updateGenerated.mockResolvedValue(
      generatedRow({ contract_status: "closed" }),
    );
    renderTab([generatedRow()]);

    await user.click(
      await screen.findByRole("button", { name: /Zmień status/ }),
    );
    // Póki umowa jest Aktywna, pola zamknięcia nie istnieją.
    expect(screen.queryByLabelText("Data zakończenia umowy")).toBeNull();

    await pickOption(user, /Status umowy/, "Zakończona");
    await pickOption(user, /Powód zakończenia umowy/, "Zakończenie projektu");
    setDate("Data zakończenia umowy", "2026-08-31");
    await user.click(screen.getByRole("button", { name: /Zapisz status/ }));

    await waitFor(() =>
      expect(mocks.updateGenerated).toHaveBeenCalledWith(1, {
        contract_status: "closed",
        closure_reason: "project_completed",
        closure_reason_other: null,
        closure_date: "2026-08-31",
      }),
    );
  });

  it("wybór „Inne” dokłada pole na własny powód", async () => {
    const user = setupUser();
    mocks.updateGenerated.mockResolvedValue(
      generatedRow({ contract_status: "closed" }),
    );
    renderTab([generatedRow()]);

    await user.click(
      await screen.findByRole("button", { name: /Zmień status/ }),
    );
    await pickOption(user, /Status umowy/, "Zakończona");
    expect(screen.queryByLabelText("Własny powód")).toBeNull();

    await pickOption(user, /Powód zakończenia umowy/, "Inny");
    fireEvent.change(screen.getByLabelText("Własny powód"), {
      target: { value: "Zmiana modelu współpracy" },
    });
    setDate("Data zakończenia umowy", "2026-09-01");
    await user.click(screen.getByRole("button", { name: /Zapisz status/ }));

    await waitFor(() =>
      expect(mocks.updateGenerated).toHaveBeenCalledWith(1, {
        contract_status: "closed",
        closure_reason: "other",
        closure_reason_other: "Zmiana modelu współpracy",
        closure_date: "2026-09-01",
      }),
    );
  });

  it("nie zapisuje „Zakończonej” bez daty zakończenia", async () => {
    const user = setupUser();
    renderTab([generatedRow()]);

    await user.click(
      await screen.findByRole("button", { name: /Zmień status/ }),
    );
    await pickOption(user, /Status umowy/, "Zakończona");
    await pickOption(user, /Powód zakończenia umowy/, "Zakończenie projektu");
    await user.click(screen.getByRole("button", { name: /Zapisz status/ }));

    expect(mocks.updateGenerated).not.toHaveBeenCalled();
    expect(mocks.showError).toHaveBeenCalledWith(
      "Podaj datę zakończenia umowy.",
    );
  });

  it("powrót na „Aktywna” czyści pola zamknięcia", async () => {
    const user = setupUser();
    mocks.updateGenerated.mockResolvedValue(generatedRow());
    renderTab([
      generatedRow({
        contract_status: "closed",
        closure_reason: "termination",
        closure_date: "2026-08-31",
      }),
    ]);

    await user.click(
      await screen.findByRole("button", { name: /Zmień status/ }),
    );
    await pickOption(user, /Status umowy/, "Aktywna");
    await user.click(screen.getByRole("button", { name: /Zapisz status/ }));

    await waitFor(() =>
      expect(mocks.updateGenerated).toHaveBeenCalledWith(1, {
        contract_status: "active",
      }),
    );
  });

  it("„Anulowana” zapisuje się jednym kliknięciem — bez powodu i daty", async () => {
    // Umowa, która NIE DOSZŁA DO SKUTKU, nie ma czego ani kiedy kończyć.
    // Formularz powodu byłby pytaniem o zakończenie czegoś, co się nie zaczęło,
    // i zamieniłby cofnięcie statusu w kilkuetapową procedurę.
    const user = setupUser();
    mocks.updateGenerated.mockResolvedValue(
      generatedRow({ contract_status: "cancelled" }),
    );
    renderTab([generatedRow({ contract_status: "in_progress" })]);

    await user.click(
      await screen.findByRole("button", { name: /Zmień status/ }),
    );
    await pickOption(user, /Status umowy/, "Anulowana");

    expect(screen.queryByLabelText("Data zakończenia umowy")).toBeNull();
    expect(screen.queryByLabelText(/Powód zakończenia/)).toBeNull();

    await user.click(screen.getByRole("button", { name: /Zapisz status/ }));
    await waitFor(() =>
      expect(mocks.updateGenerated).toHaveBeenCalledWith(1, {
        contract_status: "cancelled",
      }),
    );
  });

  it("„W trakcie” da się wybrać TYLKO dla umowy anulowanej", async () => {
    // Trzeci punkt ticketu. Poza tym jednym przypadkiem status ustawia system,
    // więc pozycja zostaje widoczna (inaczej Radix pokazałby pusty trigger dla
    // umowy, która właśnie w tym stanie jest), ale niewybieralna.
    const user = setupUser();
    mocks.updateGenerated.mockResolvedValue(
      generatedRow({ contract_status: "in_progress" }),
    );
    renderTab([generatedRow({ contract_status: "cancelled" })]);

    await user.click(
      await screen.findByRole("button", { name: /Zmień status/ }),
    );
    await user.click(screen.getByRole("combobox", { name: /Status umowy/ }));
    // Anulowana umowa jest niepodpisana, więc „Aktywna” nie jest tu opcją —
    // ten status ustawia wyłącznie potwierdzenie podpisu.
    expect(screen.queryByRole("option", { name: "Aktywna" })).toBeNull();
    const inProgress = await screen.findByRole("option", {
      name: "W trakcie",
    });
    expect(inProgress).not.toHaveAttribute("aria-disabled", "true");

    await user.click(inProgress);
    await user.click(screen.getByRole("button", { name: /Zapisz status/ }));
    await waitFor(() =>
      expect(mocks.updateGenerated).toHaveBeenCalledWith(1, {
        contract_status: "in_progress",
      }),
    );
  });

  it("umowa podpisana obustronnie nie dostaje opcji „Anulowana”", async () => {
    // Podpisana umowa DOSZŁA do skutku — kończy ją „Zakończona”. Backend
    // odmawia 409; ukrycie opcji oszczędza wysyłki, która nie ma prawa się udać.
    const user = setupUser();
    renderTab([
      generatedRow({
        contract_status: "active",
        signature_status: "signed_both",
      }),
    ]);

    await user.click(
      await screen.findByRole("button", { name: /Zmień status/ }),
    );
    await user.click(screen.getByRole("combobox", { name: /Status umowy/ }));
    expect(
      await screen.findByRole("option", { name: "Zakończona" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Anulowana" })).toBeNull();
  });

  it("bez uprawnień nie pokazuje przycisku zmiany statusu", async () => {
    renderTab([generatedRow({ can_change_status: false })]);
    // Wiersz jest wyrenderowany — asercja po numerze umowy, nie po etykiecie
    // statusu: ten test dotyczy uprawnień, więc nie może się psuć przy każdej
    // zmianie domyślnego statusu w fabryce.
    expect(await screen.findByText("1471/2026")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zmień status/ })).toBeNull();
  });
});

describe("GeneratedContractsTab — wyszukiwarka", () => {
  it("wysyła frazę na backend, a nie filtruje pobranej strony", async () => {
    const user = setupUser();
    renderTab([generatedRow()]);
    await screen.findByText("1471/2026");

    await user.type(
      screen.getByLabelText("Szukaj wygenerowanych umów"),
      "Kowalski",
    );

    await waitFor(
      () =>
        expect(mocks.generated).toHaveBeenCalledWith(100, {
          q: "Kowalski",
          // Zakładka pyta o TRZY statusy naraz — „Wszystkie" znaczy tu
          // „bieżące" (aktywne, w trakcie podpisu i anulowane), nie „wszystkie
          // umowy w systemie": zakończone i zawieszone mają własne zakładki.
          contractStatus: ["active", "in_progress", "cancelled"],
        }),
      { timeout: 2000 },
    );
  });

  it("filtr statusu trafia do zapytania", async () => {
    const user = setupUser();
    renderTab([generatedRow()]);
    await screen.findByText("1471/2026");

    await pickOption(user, /Filtr statusu umowy/, "Aktywna");

    await waitFor(() =>
      expect(mocks.generated).toHaveBeenCalledWith(100, {
        q: "",
        contractStatus: ["active"],
      }),
    );
  });

  it("filtr statusu nie oferuje zakładek obok — zakończonej ani zawieszonej", async () => {
    // Zostawienie ich tutaj pokazywałoby tę samą umowę w dwóch zakładkach
    // naraz i psuło obietnicę nazwy tej zakładki.
    const user = setupUser();
    renderTab([generatedRow()]);
    await screen.findByText("1471/2026");

    await user.click(
      screen.getByRole("combobox", { name: /Filtr statusu umowy/ }),
    );
    expect(
      await screen.findByRole("option", { name: "Aktywna" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Zakończona" })).toBeNull();
    expect(screen.queryByRole("option", { name: "Zawieszona" })).toBeNull();
    // „Anulowana" JEST tutaj — w odróżnieniu od tamtych dwóch nie ma własnej
    // zakładki, więc bez tej pozycji nie dałoby się jej odfiltrować.
    expect(
      await screen.findByRole("option", { name: "Anulowana" }),
    ).toBeInTheDocument();
  });

  it("pusty wynik wyszukiwania nie udaje braku umów w systemie", async () => {
    const user = setupUser();
    renderTab([generatedRow()]);
    await screen.findByText("1471/2026");

    mocks.generated.mockResolvedValue([]);
    await user.type(
      screen.getByLabelText("Szukaj wygenerowanych umów"),
      "nieistniejaca",
    );

    expect(
      await screen.findByText(
        "Brak umów pasujących do wyszukiwania.",
        {},
        { timeout: 2000 },
      ),
    ).toBeInTheDocument();
  });
});

describe("GeneratedContractsTab — kolumny rejestru", () => {
  it("ma docelową kolejność kolumn i nie ma kolumny Język", async () => {
    renderTab([generatedRow()]);
    await screen.findByText("1471/2026");

    const headers = screen
      .getAllByRole("columnheader")
      .map((th) => th.textContent?.trim());

    expect(headers).toEqual([
      "Numer",
      "Partner",
      "NIP",
      "Data rozpoczęcia",
      "Klient",
      "Status umowy",
      "Status podpisu",
      "Wygenerowano",
      "Akcje",
    ]);
    expect(screen.queryByRole("columnheader", { name: "Język" })).toBeNull();
  });

  it("pokazuje NIP i datę rozpoczęcia usług", async () => {
    renderTab([generatedRow()]);
    expect(await screen.findByText("1234563218")).toBeInTheDocument();
    // DD.MM.RRRR bez godziny — w odróżnieniu od kolumny „Wygenerowano" (UAT M08-B06).
    expect(screen.getByText("25.08.2026")).toBeInTheDocument();
    expect(screen.queryByText("2026-08-25")).toBeNull();
  });

  it("pokazuje autora pod datą w kolumnie Wygenerowano zamiast osobnej kolumny", async () => {
    renderTab([generatedRow()]);
    const author = await screen.findByText("Marta Rekruter");
    const cell = author.closest("td");
    expect(cell).not.toBeNull();
    // Godzina w czasie lokalnym — nie przypinamy jej do strefy maszyny testowej.
    expect(cell?.textContent).toMatch(/24\.07\.2026 \d{2}:\d{2}/);
    expect(cell?.textContent).not.toContain("2026-07-24");
    expect(
      screen.queryByRole("columnheader", { name: "Wygenerował" }),
    ).toBeNull();
  });

  it("akcje w przyklejonej kolumnie są ikonowe, ale nazwane dla czytników ekranu", async () => {
    renderTab([generatedRow({ can_download: true })]);
    await screen.findByText("1471/2026");
    for (const name of [
      "Edytuj nazwę Klienta",
      "Pobierz DOCX ponownie",
      "Usuń umowę z listy",
      // UAT M08-B09: jedyna ikona, która miała sam `title` bez `aria-label`.
      "Historia statusów",
    ]) {
      const button = screen.getByRole("button", { name });
      expect(button).toHaveAttribute("title", name);
      expect(button).toHaveAttribute("aria-label", name);
      // Sama ikona — tekst w przycisku zjadał szerokość, którą przyklejona
      // kolumna zasłaniała pod sobą.
      expect(button.textContent?.trim()).toBe("");
    }
  });

  it("dla spółki pokazuje nazwę firmy i osobę w drugiej linii", async () => {
    renderTab([
      generatedRow({
        partner_display_name: "ZW Software Sp. z o.o.",
        partner_secondary_line: "Zofia Wiśniewska",
      }),
    ]);
    expect(await screen.findByText("ZW Software Sp. z o.o.")).toBeInTheDocument();
    expect(screen.getByText("Zofia Wiśniewska")).toBeInTheDocument();
  });

  it("dla JDG nie pokazuje nazwiska w kolumnie Partner", async () => {
    // Dowód, że kolumna przestała pokazywać `partner_name`: fabryka ma tam
    // „Jan Kowalski", a nazwa działalności zawiera go już w sobie.
    renderTab([
      generatedRow({
        partner_display_name: "JK Software Jan Kowalski",
        partner_secondary_line: null,
      }),
    ]);
    expect(
      await screen.findByText("JK Software Jan Kowalski"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Jan Kowalski")).toBeNull();
  });

  it("wiersz historyczny bez nazwy firmy pokazuje osobę, nie „—”", async () => {
    renderTab([
      generatedRow({
        partner_display_name: "Historyczny Partner",
        partner_secondary_line: null,
        partner_nip: null,
        start_date: null,
      }),
    ]);
    expect(await screen.findByText("Historyczny Partner")).toBeInTheDocument();
  });
});

describe("GeneratedContractsTab — filtr daty rozpoczęcia", () => {
  it("wysyła zakres na backend i trzyma go w kluczu zapytania", async () => {
    const user = setupUser();
    renderTab([generatedRow()]);
    await screen.findByText("1471/2026");
    mocks.generated.mockClear();

    await user.click(
      screen.getByRole("button", { name: /Filtruj po dacie rozpoczęcia/ }),
    );
    await screen.findByLabelText("Data rozpoczęcia — od");
    setDate("Data rozpoczęcia — od", "2026-08-01");

    await waitFor(() =>
      expect(mocks.generated).toHaveBeenCalledWith(
        100,
        expect.objectContaining({ startFrom: "2026-08-01" }),
      ),
    );
  });

  it("cały miesiąc rozwija się na pierwszy i ostatni dzień", async () => {
    const user = setupUser();
    renderTab([generatedRow()]);
    await screen.findByText("1471/2026");
    mocks.generated.mockClear();

    await user.click(
      screen.getByRole("button", { name: /Filtruj po dacie rozpoczęcia/ }),
    );
    await screen.findByLabelText("Data rozpoczęcia — cały miesiąc");
    // Luty 2026 — 28 dni; sztywne „30" byłoby błędem.
    setDate("Data rozpoczęcia — cały miesiąc", "2026-02");

    await waitFor(() =>
      expect(mocks.generated).toHaveBeenCalledWith(
        100,
        expect.objectContaining({
          startFrom: "2026-02-01",
          startTo: "2026-02-28",
        }),
      ),
    );
  });

  it("odfiltrowana lista mówi o filtrze, nie o braku umów w systemie", async () => {
    const user = setupUser();
    renderTab([generatedRow()]);
    await screen.findByText("1471/2026");

    mocks.generated.mockResolvedValue([]);
    await user.click(
      screen.getByRole("button", { name: /Filtruj po dacie rozpoczęcia/ }),
    );
    await screen.findByLabelText("Data rozpoczęcia — od");
    setDate("Data rozpoczęcia — od", "2030-01-01");

    // „Brak wygenerowanych umów" przy aktywnym filtrze czytałoby się jako
    // utrata danych — to ten sam błąd, co renderowanie 403 jako pustki.
    expect(
      await screen.findByText("Brak umów pasujących do wyszukiwania."),
    ).toBeInTheDocument();
  });
});

describe("GeneratedContractsTab — akcje niezależne od podpisu", () => {
  it("„Pobierz” jest dostępny także dla umowy podpisanej obustronnie", async () => {
    // Regresja: oba istniejące pliki testowe mają w fabryce
    // `can_download: false`, więc ponowne dodanie guardu `!signed` przy
    // „Pobierz" przeszłoby CI niezauważone.
    renderTab([
      generatedRow({
        signature_status: "signed_both",
        contract_status: "active",
        can_download: true,
        can_edit: true,
      }),
    ]);
    expect(
      await screen.findByRole("button", { name: /Pobierz/ }),
    ).toBeInTheDocument();
    // „Edytuj" przeciwnie — po podpisaniu znika.
    expect(screen.queryByRole("button", { name: /Edytuj/ })).toBeNull();
  });
});

describe("RecruitmentOptionsNotice — lista rekrutacji w generatorze (UAT M08-B07)", () => {
  it("pusta lista mówi, że kandydat nie jest w żadnej rekrutacji", () => {
    render(
      <RecruitmentOptionsNotice
        hasCandidate
        isError={false}
        isEmpty
        onRetry={() => undefined}
      />,
    );
    expect(
      screen.getByText(/Kandydat nie jest w żadnej rekrutacji/),
    ).toBeInTheDocument();
  });

  it("awaria ma własny komunikat z ponowieniem, nie udaje pustki", async () => {
    const onRetry = vi.fn();
    render(
      <RecruitmentOptionsNotice
        hasCandidate
        isError
        isEmpty={false}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      /Nie udało się wczytać rekrutacji/,
    );
    expect(screen.queryByText(/nie jest w żadnej rekrutacji/)).toBeNull();
    await setupUser().click(screen.getByRole("button", { name: "Ponów" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("bez kandydata i przy wczytywaniu nic nie pokazuje", () => {
    const { container } = render(
      <RecruitmentOptionsNotice
        hasCandidate={false}
        isError
        isEmpty
        onRetry={() => undefined}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
