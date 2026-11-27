/**
 * „Nowa umowa” w układzie kroków (etap 3b przebudowy modułu Kontrakty):
 * lista kroków ze stanem, jeden krok formularza, „kartka” z pierwszym
 * akapitem i przyklejony pasek braków.
 *
 * Sedno: pola, walidacja i pobranie są te same co w układzie jednej kolumny
 * (`B2BContractGeneratorForm.test.tsx`). Pasek wyłącza „Pobierz” dokładnie
 * wtedy, gdy dawniej klik kończył się komunikatem „Uzupełnij wymagane pola”,
 * a błędy formatu (numer umowy) nadal zgłasza dopiero pobranie.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { B2BRole } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  roles: vi.fn(),
  nextNumber: vi.fn(),
  clientsLookup: vi.fn(),
  generated: vi.fn(),
  generatedForm: vi.fn(),
  companyLookup: vi.fn(),
  companyVerification: vi.fn(),
  renderDocx: vi.fn(),
  rerenderGenerated: vi.fn(),
  renderHtml: vi.fn(),
  checkUop: vi.fn(),
  prefill: vi.fn(),
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
    companyVerification: (...a: unknown[]) => mocks.companyVerification(...a),
    renderDocx: (...a: unknown[]) => mocks.renderDocx(...a),
    rerenderGenerated: (...a: unknown[]) => mocks.rerenderGenerated(...a),
    renderHtml: (...a: unknown[]) => mocks.renderHtml(...a),
    checkUop: (...a: unknown[]) => mocks.checkUop(...a),
    prefill: (...a: unknown[]) => mocks.prefill(...a),
  },
  extractErrorMsg: (error: unknown) =>
    error instanceof Error ? error.message : "Błąd",
}));

import { GeneratorForm } from "@/components/v2/pages/B2BContractGeneratorV2";

vi.setConfig({ testTimeout: 60_000 });
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

beforeEach(() => {
  vi.clearAllMocks();
  mocks.apiGet.mockImplementation((url: string) => {
    const cand = /^\/api\/candidates\/(\d+)$/.exec(url);
    if (cand)
      return Promise.resolve({ data: CANDIDATES[Number(cand[1])] ?? {} });
    if (url.endsWith("/recruitments")) {
      return Promise.resolve({
        data: [
          { stage_id: 11, job_id: 10, job_title: "Java Dev", stage: "offer" },
        ],
      });
    }
    if (url === "/api/jobs/10") {
      return Promise.resolve({
        data: {
          id: 10,
          title: "Java Dev",
          client_id: 3,
          description: "Rozwój systemu bankowego.",
          external_source: "traffit",
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
  mocks.prefill.mockRejectedValue(new Error("brak"));
  mocks.companyLookup.mockRejectedValue(new Error("brak"));
  mocks.companyVerification.mockResolvedValue({
    status: "verified",
    registry: "ceidg",
    checked_at: "2026-09-28T10:00:00Z",
    company: null,
    warnings: [],
    message: null,
  });
});

type FormProps = React.ComponentProps<typeof GeneratorForm>;

function renderWizard(props: FormProps = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const utils = render(
    <QueryClientProvider client={client}>
      <GeneratorForm layout="wizard" {...props} />
    </QueryClientProvider>,
  );
  return {
    ...utils,
    rerenderWizard: (next: FormProps) =>
      utils.rerender(
        <QueryClientProvider client={client}>
          <GeneratorForm layout="wizard" {...next} />
        </QueryClientProvider>,
      ),
  };
}

const setupUser = () => userEvent.setup({ delay: null });
const steps = () => within(screen.getByRole("navigation", { name: "Kroki umowy" }));
const bar = () => within(screen.getByRole("region", { name: "Gotowość umowy" }));
const currentStepTitle = () =>
  screen.getByRole("heading", { level: 2 }).textContent;

/** Para z adresu (42/10) wczytana: dane firmy, klient i numer na miejscu. */
async function waitForPrefill() {
  await waitFor(
    () =>
      expect(
        (screen.getByLabelText("Miasto Klienta *") as HTMLInputElement).value,
      ).toBe("Warszawa"),
    { timeout: PREFILL_WAIT },
  );
  await waitFor(() =>
    expect(
      (screen.getByLabelText("Numer umowy (auto) *") as HTMLInputElement).value,
    ).toBe("1500/2026"),
  );
}

async function pickRole(user: ReturnType<typeof setupUser>) {
  await user.click(steps().getByRole("button", { name: /Obszar usług/ }));
  await user.click(screen.getByRole("combobox", { name: /Obszar/ }));
  await user.click(await screen.findByRole("option", { name: "Programista Java" }));
}

describe("GeneratorForm w układzie kroków", () => {
  it("siedem kroków, jeden widoczny; Dalej i Wstecz przechodzą i zgłaszają krok", async () => {
    const user = setupUser();
    const onStepChange = vi.fn();
    renderWizard({ onStepChange });

    expect(steps().getAllByRole("button")).toHaveLength(7);
    expect(currentStepTitle()).toBe("Źródło danych");
    expect(steps().getByRole("button", { current: "step" })).toHaveTextContent(
      "Źródło danych",
    );
    // Pola innych kroków są zamontowane, ale niewidoczne.
    expect(screen.queryByRole("combobox", { name: /Obszar/ })).toBeNull();

    await user.click(
      screen.getByRole("button", { name: /Dalej: Szczegóły administracyjne/ }),
    );
    expect(currentStepTitle()).toBe("Szczegóły administracyjne");
    expect(onStepChange).toHaveBeenLastCalledWith("admin");

    await user.click(screen.getByRole("button", { name: "Wstecz" }));
    expect(currentStepTitle()).toBe("Źródło danych");
    expect(onStepChange).toHaveBeenLastCalledWith("zrodlo");
  });

  it("pusty formularz: pasek liczy braki i wyłącza pobieranie, ale „Podgląd” działa jak dawniej", async () => {
    const user = setupUser();
    renderWizard();
    await waitFor(() =>
      expect(bar().getByText(/^Brakuje \d+ pól:$/)).toBeInTheDocument(),
    );
    const download = bar().getByRole("button", { name: "Pobierz DOCX (PL)" });
    expect(download).toBeDisabled();
    expect(download.getAttribute("title")).toMatch(/^Brakuje \d+ pól: Kandydat, Rekrutacja/);
    // Szczegóły administracyjne czekają na rekrutację — bez ✓.
    expect(
      within(steps().getByRole("button", { name: /Szczegóły administracyjne/ })).queryByLabelText(
        "komplet",
      ),
    ).toBeNull();

    // „Podgląd” jak dawniej: walidacja, a z brakami — komunikat, bez zapytania.
    await user.click(bar().getByRole("button", { name: /Podgląd/ }));
    expect(mocks.showError).toHaveBeenCalledWith(
      expect.stringMatching(/^Uzupełnij wymagane pola: Kandydat, Rekrutacja, Obszar usług, /),
    );
    expect(mocks.renderHtml).not.toHaveBeenCalled();
  });

  it("klik w brak na pasku przenosi do kroku i pola", async () => {
    const user = setupUser();
    renderWizard({ prefillCandidateId: 42, prefillJobId: 10 });
    await waitForPrefill();
    fireEvent.change(screen.getByLabelText("Stawka godz. (netto) *"), {
      target: { value: "150" },
    });
    await waitFor(() =>
      expect(bar().getByText("Brakuje 1 pola:")).toBeInTheDocument(),
    );

    await user.click(bar().getByRole("button", { name: "Obszar usług" }));
    expect(currentStepTitle()).toBe("Obszar usług");
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("combobox", { name: /Obszar/ }),
      ),
    );
  });

  it("komplet włącza pobieranie; pobranie i poprawka idą tą samą drogą co dziś", async () => {
    const user = setupUser();
    mocks.renderDocx.mockResolvedValue({
      data: new Blob(["docx"]),
      headers: { "x-generated-contract-id": "77" },
    });
    renderWizard({ prefillCandidateId: 42, prefillJobId: 10 });
    await waitForPrefill();
    await pickRole(user);
    fireEvent.change(screen.getByLabelText("Stawka godz. (netto) *"), {
      target: { value: "150" },
    });
    // KRZ w kroku „Partner” (0800): bez wyniku pobranie najpierw przypomina o KRZ.
    fireEvent.click(screen.getByRole("radio", { name: "Brak wpisów", hidden: true }));

    expect(
      await bar().findByText("Wszystko uzupełnione — umowę nr 1500/2026 można pobrać."),
    ).toBeInTheDocument();
    await user.click(bar().getByRole("button", { name: "Pobierz DOCX (PL)" }));

    await waitFor(() => expect(mocks.renderDocx).toHaveBeenCalledTimes(1));
    expect(mocks.companyVerification).toHaveBeenCalledTimes(1);
    expect(mocks.renderDocx.mock.calls[0][0]).toMatchObject({
      candidate_id: 42,
      job_id: 10,
      role_id: 3,
      language: "pl",
      partner_nip: "1234563218",
      partner_phone: "+48 600100200",
      client_name: "Nordea Bank",
      contract_number: "1500/2026",
      rate_candidate: 150,
      is_replacement: false,
      fte: "1",
    });
    expect(
      await screen.findByText("Umowa 1500/2026 zapisana w rejestrze (W trakcie)"),
    ).toBeInTheDocument();
    // Poprawka z paska — ten sam wiersz, ten sam numer.
    expect(
      bar().getByRole("button", { name: "Popraw i pobierz ponownie" }),
    ).toBeEnabled();
  });

  it("zły format numeru nie jest brakiem — zgłasza go dopiero pobranie, jak dawniej", async () => {
    const user = setupUser();
    renderWizard({ prefillCandidateId: 42, prefillJobId: 10 });
    await waitForPrefill();
    await pickRole(user);
    fireEvent.change(screen.getByLabelText("Stawka godz. (netto) *"), {
      target: { value: "150" },
    });
    fireEvent.change(screen.getByLabelText("Numer umowy (auto) *"), {
      target: { value: "1500-2026" },
    });

    const download = bar().getByRole("button", { name: "Pobierz DOCX (PL)" });
    await waitFor(() => expect(download).toBeEnabled());
    await user.click(download);
    expect(mocks.showError).toHaveBeenCalledWith(
      expect.stringContaining("Numer umowy musi być w formacie liczba/rok"),
    );
    expect(mocks.renderDocx).not.toHaveBeenCalled();
  });

  it("kartka pokazuje braki w tekście, a klik w brak prowadzi do pola", async () => {
    const user = setupUser();
    renderWizard({ prefillCandidateId: 43, prefillJobId: 10 });
    const paper = within(screen.getByTestId("agreement-paper"));
    await waitFor(() =>
      expect(paper.getByText(/Anną Nowak/)).toBeInTheDocument(),
    );
    expect(paper.getByRole("button", { name: "[nazwa firmy]" })).toBeInTheDocument();
    expect(paper.getByRole("button", { name: "[REGON]" })).toBeInTheDocument();

    await user.click(paper.getByRole("button", { name: "[NIP]" }));
    expect(currentStepTitle()).toBe("Partner");
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByLabelText("NIP (auto z rejestru) *"),
      ),
    );
  });

  it("krok z adresu otwiera formularz na nim, także przy miękkiej nawigacji", async () => {
    const { rerenderWizard } = renderWizard({ stepParam: "warunki" });
    expect(currentStepTitle()).toBe("Warunki umowy");
    rerenderWizard({ stepParam: "admin" });
    await waitFor(() => expect(currentStepTitle()).toBe("Szczegóły administracyjne"));
  });

  it("„Podgląd” przy komplecie otwiera całą umowę w oknie z wydrukiem", async () => {
    const user = setupUser();
    mocks.renderHtml.mockResolvedValue({ html: "<p>Treść</p>", contract_number: null });
    renderWizard({ prefillCandidateId: 42, prefillJobId: 10 });
    await waitForPrefill();
    await pickRole(user);
    fireEvent.change(screen.getByLabelText("Stawka godz. (netto) *"), {
      target: { value: "150" },
    });
    await user.click(bar().getByRole("button", { name: /Podgląd/ }));

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("Podgląd umowy (bez numeru w rejestrze)"),
    ).toBeInTheDocument();
    expect(within(dialog).getByTitle("Podgląd umowy")).toHaveAttribute("sandbox", "");
    expect(
      within(dialog).getByRole("button", { name: /Drukuj podgląd/ }),
    ).toBeInTheDocument();
  });
});
