/**
 * Formularz Generatora Umów B2B — pobranie, poprawka pod tym samym numerem,
 * „Nowa umowa”, para (kandydat, rekrutacja) z adresu i ostrzeżenia.
 *
 * Do 23.09.2026 każde „Pobierz DOCX” zakładało nowy wiersz rejestru z kolejnym
 * numerem: poprawka literówki albo wersja EN = drugi numer (15 usunięć na ~104
 * generacje). Te testy pilnują, że po pierwszym pobraniu formularz poprawia
 * TEN SAM wiersz (`/rerender`), a nowy numer daje dopiero „Nowa umowa”.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { B2BGeneratedContractRow, B2BRole } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  roles: vi.fn(),
  nextNumber: vi.fn(),
  clientsLookup: vi.fn(),
  generated: vi.fn(),
  generatedForm: vi.fn(),
  companyLookup: vi.fn(),
  renderDocx: vi.fn(),
  rerenderGenerated: vi.fn(),
  renderHtml: vi.fn(),
  checkUop: vi.fn(),
  downloadBlob: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/contracts/b2b-generator",
  useSearchParams: () => new URLSearchParams(),
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
    showActionToast: vi.fn(),
    showSuccess: mocks.showSuccess,
    showError: mocks.showError,
  }),
}));

vi.mock("@/lib/cv-generator", () => ({
  downloadBlob: (...args: unknown[]) => mocks.downloadBlob(...args),
  parseDispositionFilename: (_header: string, fallback: string) => fallback,
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  b2bGeneratorApi: {
    roles: (...a: unknown[]) => mocks.roles(...a),
    nextNumber: (...a: unknown[]) => mocks.nextNumber(...a),
    clientsLookup: (...a: unknown[]) => mocks.clientsLookup(...a),
    generated: (...a: unknown[]) => mocks.generated(...a),
    generatedForm: (...a: unknown[]) => mocks.generatedForm(...a),
    companyLookup: (...a: unknown[]) => mocks.companyLookup(...a),
    renderDocx: (...a: unknown[]) => mocks.renderDocx(...a),
    rerenderGenerated: (...a: unknown[]) => mocks.rerenderGenerated(...a),
    renderHtml: (...a: unknown[]) => mocks.renderHtml(...a),
    checkUop: (...a: unknown[]) => mocks.checkUop(...a),
  },
  extractErrorMsg: (error: unknown) =>
    error instanceof Error ? error.message : "Błąd",
  signingApi: {},
}));

import { GeneratorForm } from "@/components/v2/pages/B2BContractGeneratorV2";

// Każdy test to pełny przepływ: łańcuch czterech zapytań prefillu, wybór
// z listy Radix i pobranie. Przy obciążonej maszynie (pełny suite, równoległe
// sesje) domyślne 5 s kończyło się fałszywym czerwonym, nie błędem produktu.
vi.setConfig({ testTimeout: 60_000 });
/** Oczekiwanie na łańcuch prefillu (kandydat → rekrutacje → oferta). */
const PREFILL_WAIT = 10_000;

beforeAll(() => {
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

const ROLE: B2BRole = {
  id: 3,
  category_key: "dev",
  category_label_pl: "Programowanie",
  category_label_en: "Development",
  slug: "java",
  name_pl: "Programista Java",
  name_en: "Java Developer",
  area_label_pl: "Java",
  area_label_en: "Java",
  scope_pl: ["Rozwój aplikacji."],
  scope_en: ["Application development."],
  display_order: 0,
  is_active: true,
};

const CANDIDATES: Record<number, Record<string, string>> = {
  42: {
    full_name: "Jan Kowalski",
    legal_name: "JK Software Jan Kowalski",
    nip: "1234563218",
    regon: "123456785",
    business_address: "ul. Prosta 1, 00-001 Warszawa",
    email: "jan@example.com",
    phone: "600100200",
  },
  43: { full_name: "Anna Nowak" },
};

function docxResponse(id: string | null) {
  return {
    data: new Blob(["docx"]),
    headers: {
      "content-disposition": 'attachment; filename="Umowa B2B.docx"',
      ...(id ? { "x-generated-contract-id": id } : {}),
    },
  };
}

function existing(
  overrides: Partial<B2BGeneratedContractRow> = {},
): Partial<B2BGeneratedContractRow> {
  return {
    id: 90,
    contract_number: "1490/2026",
    candidate_id: 42,
    job_id: 10,
    contract_status: "in_progress",
    signature_status: "unsigned",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.apiGet.mockImplementation((url: string) => {
    const cand = /^\/api\/candidates\/(\d+)$/.exec(url);
    if (cand) return Promise.resolve({ data: CANDIDATES[Number(cand[1])] ?? {} });
    if (url.endsWith("/recruitments")) {
      return Promise.resolve({
        data: [{ stage_id: 11, job_id: 10, job_title: "Java Dev", stage: "offer" }],
      });
    }
    if (url === "/api/jobs/10") {
      return Promise.resolve({
        data: {
          id: 10,
          title: "Java Dev",
          client_id: 3,
          description: "Rozwój systemu bankowego.",
          location: "Warszawa",
          client_name: "Nordea Bank",
        },
      });
    }
    return Promise.resolve({ data: [] });
  });
  mocks.roles.mockResolvedValue([ROLE]);
  mocks.nextNumber
    .mockResolvedValueOnce({ contract_number: "1500/2026", year: 2026, seq: 1500 })
    .mockResolvedValue({ contract_number: "1501/2026", year: 2026, seq: 1501 });
  mocks.clientsLookup.mockResolvedValue([]);
  mocks.generated.mockResolvedValue([]);
  mocks.companyLookup.mockRejectedValue(new Error("brak"));
});

function renderForm(props: React.ComponentProps<typeof GeneratorForm> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const utils = render(
    <QueryClientProvider client={client}>
      <GeneratorForm prefillCandidateId={42} prefillJobId={10} {...props} />
    </QueryClientProvider>,
  );
  return {
    ...utils,
    rerenderForm: (next: React.ComponentProps<typeof GeneratorForm>) =>
      utils.rerender(
        <QueryClientProvider client={client}>
          <GeneratorForm {...next} />
        </QueryClientProvider>,
      ),
  };
}

const setupUser = () => userEvent.setup({ delay: null });

/** Formularz z adresu (`?candidate=42&job=10`) + obszar i stawka. */
async function fillForm(user: ReturnType<typeof setupUser>) {
  // Para z adresu: kandydat i rekrutacja wybrane bez klikania. Łańcuch
  // kandydat → rekrutacje → rekrutacja → oferta to cztery zapytania, więc
  // przy pełnym przebiegu suite'a domyślna sekunda bywa za krótka.
  await waitFor(
    () =>
      expect(
        (screen.getByLabelText("Miasto Klienta *") as HTMLInputElement).value,
      ).toBe("Warszawa"),
    { timeout: PREFILL_WAIT },
  );
  expect(
    (screen.getByLabelText("Nazwa Firmy *") as HTMLInputElement).value,
  ).toBe("JK Software Jan Kowalski");
  await waitFor(() =>
    expect(
      (screen.getByLabelText("Numer umowy (auto) *") as HTMLInputElement).value,
    ).toBe("1500/2026"),
  );
  await user.click(screen.getByRole("combobox", { name: /Obszar/ }));
  await user.click(await screen.findByRole("option", { name: "Programista Java" }));
  fireEvent.change(screen.getByLabelText("Stawka godz. (netto) *"), {
    target: { value: "150" },
  });
}

describe("GeneratorForm — pobranie i poprawka pod tym samym numerem", () => {
  it("pierwsze pobranie zapisuje umowę, poprawka idzie do tego samego wiersza", async () => {
    const user = setupUser();
    mocks.renderDocx.mockResolvedValue(docxResponse("77"));
    mocks.rerenderGenerated.mockResolvedValue(docxResponse("77"));
    renderForm();
    await fillForm(user);

    // Jeden przycisk w języku z przełącznika — bez osobnego „DOCX (EN)”.
    expect(screen.queryByRole("button", { name: /DOCX \(EN\)/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Pobierz DOCX (PL)" }));

    expect(
      await screen.findByText("Umowa 1500/2026 zapisana w rejestrze (W trakcie)"),
    ).toBeInTheDocument();
    expect(mocks.renderDocx).toHaveBeenCalledTimes(1);
    expect(mocks.renderDocx.mock.calls[0][0]).toMatchObject({
      candidate_id: 42,
      job_id: 10,
      language: "pl",
      contract_number: "1500/2026",
      currency: "PLN",
    });
    // Numer zapisanej umowy jest zablokowany — poprawka i tak idzie pod niego.
    expect(screen.getByLabelText("Numer umowy (auto) *")).toBeDisabled();

    // Wersja angielska = ten sam numer, ten sam wiersz.
    await user.click(screen.getByRole("button", { name: "English" }));
    expect(screen.getByRole("button", { name: "English" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(
      screen.getAllByRole("button", { name: "Popraw i pobierz ponownie" })[0],
    );
    await waitFor(() => expect(mocks.rerenderGenerated).toHaveBeenCalledTimes(1));
    expect(mocks.rerenderGenerated.mock.calls[0][0]).toBe(77);
    expect(mocks.rerenderGenerated.mock.calls[0][1]).toMatchObject({
      candidate_id: 42,
      job_id: 10,
      language: "en",
    });
    expect(mocks.renderDocx).toHaveBeenCalledTimes(1);
  });

  it("„Nowa umowa” czyści formularz i daje kolejny wolny numer", async () => {
    const user = setupUser();
    const onClearPrefill = vi.fn();
    mocks.renderDocx.mockResolvedValue(docxResponse("77"));
    renderForm({ onClearPrefill });
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Pobierz DOCX (PL)" }));
    await screen.findByText("Umowa 1500/2026 zapisana w rejestrze (W trakcie)");

    await user.click(screen.getAllByRole("button", { name: /Nowa umowa/ })[0]);

    await waitFor(() =>
      expect(
        (screen.getByLabelText("Numer umowy (auto) *") as HTMLInputElement).value,
      ).toBe("1501/2026"),
    );
    expect(
      screen.queryByText(/zapisana w rejestrze \(W trakcie\)/),
    ).toBeNull();
    expect(screen.getByRole("combobox", { name: /Kandydat/ })).toHaveTextContent(
      "Wybierz kandydata…",
    );
    expect(
      (screen.getByLabelText("Nazwa Firmy *") as HTMLInputElement).value,
    ).toBe("");
    expect(onClearPrefill).toHaveBeenCalled();
  });

  it("409 przy pierwszym pobraniu mówi, jaki numer podstawiono, i nie pobiera", async () => {
    const user = setupUser();
    mocks.renderDocx.mockRejectedValue(
      Object.assign(new Error("Numer 1500/2026 jest już zajęty."), {
        response: { status: 409 },
      }),
    );
    renderForm();
    await fillForm(user);
    await user.click(screen.getByRole("button", { name: "Pobierz DOCX (PL)" }));

    await waitFor(() =>
      expect(mocks.showError).toHaveBeenCalledWith(
        expect.stringContaining("Podstawiono numer 1501/2026"),
      ),
    );
    expect(
      (screen.getByLabelText("Numer umowy (auto) *") as HTMLInputElement).value,
    ).toBe("1501/2026");
    expect(mocks.downloadBlob).not.toHaveBeenCalled();
    // Bez ponownego kliknięcia nie wychodzi nic pod podstawionym numerem.
    expect(mocks.renderDocx).toHaveBeenCalledTimes(1);
  });
});

describe("GeneratorForm — podgląd", () => {
  it("podgląd w piaskownicy znika po zmianie danych formularza", async () => {
    const user = setupUser();
    mocks.renderHtml.mockResolvedValue({ html: "<p>Treść</p>", contract_number: null });
    renderForm();
    await fillForm(user);

    await user.click(screen.getByRole("button", { name: /Podgląd/ }));
    expect(
      await screen.findByText("Podgląd (bez numeru w rejestrze)"),
    ).toBeInTheDocument();
    expect(screen.getByTitle("Podgląd umowy")).toHaveAttribute("sandbox", "");
    expect(screen.getByRole("button", { name: /Drukuj podgląd/ })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Miasto Klienta *"), {
      target: { value: "Kraków" },
    });
    await waitFor(() =>
      expect(screen.queryByText("Podgląd (bez numeru w rejestrze)")).toBeNull(),
    );
  });
});

describe("GeneratorForm — zmiana kandydata i ostrzeżenia", () => {
  it("nowy kandydat nie dziedziczy danych firmy ani ręcznej odmiany poprzedniego", async () => {
    const { rerenderForm } = renderForm();
    await waitFor(() =>
      expect(
        (screen.getByLabelText("Nazwa Firmy *") as HTMLInputElement).value,
      ).toBe("JK Software Jan Kowalski"),
      { timeout: PREFILL_WAIT },
    );
    fireEvent.change(
      screen.getByLabelText("Imię i nazwisko — narzędnik (komparycja) *"),
      { target: { value: "Janem K. (ręcznie)" } },
    );

    rerenderForm({ prefillCandidateId: 43, prefillJobId: 10 });

    await waitFor(() =>
      expect(
        (screen.getByLabelText("Imię i nazwisko *") as HTMLInputElement).value,
      ).toBe("Anna Nowak"),
      { timeout: PREFILL_WAIT },
    );
    expect(
      (screen.getByLabelText("Nazwa Firmy *") as HTMLInputElement).value,
    ).toBe("");
    expect((screen.getByLabelText("NIP (auto z rejestru) *") as HTMLInputElement).value).toBe("");
    // Flaga „dotknięcia” narzędnika wyzerowana — auto-odmiana działa znowu.
    expect(
      (
        screen.getByLabelText(
          "Imię i nazwisko — narzędnik (komparycja) *",
        ) as HTMLInputElement
      ).value,
    ).not.toContain("ręcznie");
  });

  it("żywa umowa tej osoby w tej rekrutacji — ostrzeżenie z linkiem do rejestru", async () => {
    mocks.generated.mockResolvedValue([existing()]);
    renderForm();

    expect(
      await screen.findByText(
        "Ta osoba ma już umowę 1490/2026 (W trakcie) w tej rekrutacji",
        undefined,
        { timeout: PREFILL_WAIT },
      ),
    ).toBeInTheDocument();
    expect(mocks.generated).toHaveBeenCalledWith(50, { jobId: 10 });
    // Bez prawa poprawki (`can_edit`) link prowadzi do rejestru z wyszukaniem.
    expect(
      screen.getByRole("link", { name: "Otwórz umowę 1490/2026 w rejestrze" }),
    ).toHaveAttribute("href", "/contracts/b2b-generator?tab=generated&q=1490%2F2026");
    // Ostrzeżenie nie blokuje generowania.
    expect(screen.getByRole("button", { name: "Pobierz DOCX (PL)" })).toBeEnabled();
  });

  it("anulowana umowa tej osoby nie ostrzega", async () => {
    mocks.generated.mockResolvedValue([existing({ contract_status: "cancelled" })]);
    renderForm();
    await waitFor(() => expect(mocks.generated).toHaveBeenCalled(), {
      timeout: PREFILL_WAIT,
    });
    await waitFor(() =>
      expect(
        (screen.getByLabelText("Miasto Klienta *") as HTMLInputElement).value,
      ).toBe("Warszawa"),
      { timeout: PREFILL_WAIT },
    );
    expect(screen.queryByText(/Ta osoba ma już umowę/)).toBeNull();
  });

  it("waluta to zamknięta lista", async () => {
    const user = setupUser();
    renderForm();
    await user.click(screen.getByRole("combobox", { name: "Waluta" }));
    for (const code of ["PLN", "EUR", "USD", "GBP", "CHF"]) {
      expect(await screen.findByRole("option", { name: code })).toBeInTheDocument();
    }
  });
});

describe("GeneratorForm — „Popraw umowę” (`?edit=`)", () => {
  const SAVED_FORM = {
    candidate_id: 42,
    job_id: 10,
    role_id: 3,
    language: "en",
    gender: "k",
    partner_name: "Jan Kowalski",
    partner_instrumental: "Janem Kowalskim (zapisany)",
    partner_legal_name: "JK Software (zapisana)",
    partner_business_address: "ul. Zapisana 5, Kraków",
    partner_correspondence_address: "skr. 12",
    partner_nip: "1234563218",
    partner_entity_type: "sole_trader",
    partner_regon: "999999999",
    partner_email: "zapis@example.com",
    partner_phone: "+44 7700 900123",
    client_name: "Klient z umowy",
    project_city: "Gdańsk",
    project_description: "Opis zapisany w umowie.",
    contract_number: "1490/2026",
    signing_date: "2026-09-01",
    start_date: "2026-10-01",
    start_date_mode: "not_earlier",
    rate_candidate: 140,
    rate_stages: [
      { rate: 140, effective_from: null, effective_to: "2026-12-31" },
      { rate: 160, effective_from: "2027-01-01", effective_to: null },
    ],
    currency: "EUR",
    scope_items_override: ["Punkt z umowy"],
  };

  it("wypełnia pola zapisaną umową i poprawka idzie do tego samego wiersza", async () => {
    const user = setupUser();
    const onEditConsumed = vi.fn();
    mocks.generatedForm.mockResolvedValue({
      id: 90,
      contract_number: "1490/2026",
      form: SAVED_FORM,
    });
    mocks.rerenderGenerated.mockResolvedValue(docxResponse("90"));
    renderForm({
      prefillCandidateId: null,
      prefillJobId: null,
      editGeneratedId: 90,
      onEditConsumed,
    });

    expect(
      await screen.findByText(
        "Umowa 1490/2026 zapisana w rejestrze (W trakcie)",
        undefined,
        { timeout: PREFILL_WAIT },
      ),
    ).toBeInTheDocument();
    expect(mocks.generatedForm).toHaveBeenCalledWith(90);
    expect(onEditConsumed).toHaveBeenCalled();
    const value = (label: string) =>
      (screen.getByLabelText(label) as HTMLInputElement).value;
    // Zapisane wartości wygrywają z profilem kandydata i z ofertą.
    expect(value("Nazwa Firmy *")).toBe("JK Software (zapisana)");
    expect(value("Imię i nazwisko — narzędnik (komparycja) *")).toBe(
      "Janem Kowalskim (zapisany)",
    );
    expect(value("Miasto Klienta *")).toBe("Gdańsk");
    expect(value("Opis projektu i zakres usług *")).toBe(
      "Opis zapisany w umowie.",
    );
    expect(value("Telefon *")).toBe("7700 900123");
    expect(value("Numer umowy (auto) *")).toBe("1490/2026");
    expect(screen.getByRole("button", { name: "English" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Kobieta" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("combobox", { name: /Kandydat/ })).toHaveTextContent(
      "Jan Kowalski",
    );
    expect(screen.getByRole("combobox", { name: /Waluta/ })).toHaveTextContent(
      "EUR",
    );
    // Rejestr NIP-u nie nadpisuje wczytanych danych dzisiejszym stanem.
    expect(mocks.companyLookup).not.toHaveBeenCalled();

    await user.click(
      screen.getAllByRole("button", { name: "Popraw i pobierz ponownie" })[0],
    );
    await waitFor(() => expect(mocks.rerenderGenerated).toHaveBeenCalledTimes(1));
    expect(mocks.renderDocx).not.toHaveBeenCalled();
    const [id, payload] = mocks.rerenderGenerated.mock.calls[0];
    expect(id).toBe(90);
    expect(payload).toMatchObject({
      candidate_id: 42,
      job_id: 10,
      role_id: 3,
      language: "en",
      gender: "k",
      partner_legal_name: "JK Software (zapisana)",
      partner_phone: "+44 7700 900123",
      partner_entity_type: "sole_trader",
      client_name: "Klient z umowy",
      contract_number: "1490/2026",
      start_date_mode: "not_earlier",
      currency: "EUR",
      scope_items_override: ["Punkt z umowy"],
      rate_stages: [
        { rate: 140, effective_from: null, effective_to: "2026-12-31" },
        { rate: 160, effective_from: "2027-01-01", effective_to: null },
      ],
    });
  });

  it("odmowa /form (409) → toast z komunikatem API i zdjęty parametr", async () => {
    const onEditConsumed = vi.fn();
    mocks.generatedForm.mockRejectedValue(
      Object.assign(
        new Error("Poprawić można tylko niepodpisaną umowę „W trakcie”."),
        { response: { status: 409 } },
      ),
    );
    renderForm({
      prefillCandidateId: null,
      prefillJobId: null,
      editGeneratedId: 91,
      onEditConsumed,
    });

    await waitFor(() =>
      expect(mocks.showError).toHaveBeenCalledWith(
        "Poprawić można tylko niepodpisaną umowę „W trakcie”.",
      ),
    );
    expect(onEditConsumed).toHaveBeenCalled();
    expect(screen.queryByText(/zapisana w rejestrze \(W trakcie\)/)).toBeNull();
  });

  it("ostrzeżenie o istniejącej umowie prowadzi wprost do poprawki, gdy wolno", async () => {
    mocks.generated.mockResolvedValue([
      existing({ can_edit: true, can_download: true }),
    ]);
    renderForm();
    expect(
      await screen.findByRole(
        "link",
        { name: "Popraw umowę 1490/2026" },
        { timeout: PREFILL_WAIT },
      ),
    ).toHaveAttribute("href", "/contracts/b2b-generator?tab=generator&edit=90");
  });
});

describe("GeneratorForm — awaria wyszukiwarek to nie pusta lista", () => {
  it("błąd listy klientów daje „Ponów”, nie „Brak klientów na liście.”", async () => {
    const user = setupUser();
    mocks.clientsLookup.mockRejectedValue(new Error("503"));
    renderForm({});

    await user.click(screen.getByRole("combobox", { name: /Pełna nazwa Klienta/ }));
    expect(
      await screen.findByText("Nie udało się pobrać listy klientów."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Brak klientów na liście.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Ponów/ })).toBeInTheDocument();
  });

  it("udana pusta lista klientów nadal mówi „Brak klientów na liście.”", async () => {
    const user = setupUser();
    renderForm({});

    await user.click(screen.getByRole("combobox", { name: /Pełna nazwa Klienta/ }));
    expect(await screen.findByText("Brak klientów na liście.")).toBeInTheDocument();
  });

  it("błąd wyszukiwania kandydata daje „Ponów”, nie „Brak wyników.”", async () => {
    const user = setupUser();
    mocks.apiGet.mockImplementation((url: string) =>
      url === "/api/cv-generator/candidates"
        ? Promise.reject(new Error("503"))
        : Promise.resolve({ data: [] }),
    );
    renderForm({});

    await user.click(screen.getByRole("combobox", { name: /Kandydat/ }));
    expect(
      await screen.findByText("Nie udało się wyszukać kandydatów."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Brak wyników.")).not.toBeInTheDocument();
  });
});
