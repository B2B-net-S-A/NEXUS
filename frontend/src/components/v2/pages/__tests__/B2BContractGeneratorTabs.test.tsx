/**
 * Generator umów: pięć zakładek zamiast siedmiu (etap 3b, 20.11.2026).
 *
 * Trzy rejestry umów to jedna zakładka „Umowy” z fazą, a klucze `?tab=`
 * zostały te same — linki z kontraktu, rekrutacji, powiadomień i Nowości
 * (`?tab=generated|no-project|closed|annexes|documents`, aliasy `current`…)
 * muszą dalej trafiać w to samo miejsce.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  params: new URLSearchParams(),
  canGenerate: true,
  isAdmin: true,
  replaceUrl: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/contracts/b2b-generator",
  useSearchParams: () => state.params,
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

vi.mock("@/lib/url-selection", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/url-selection")>()),
  useUrlWriter: () => ({ replaceUrl: state.replaceUrl, pushUrl: vi.fn() }),
}));

vi.mock("@/store/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/store/auth")>();
  const auth = { user: { id: 1, roles: ["admin"] } };
  return {
    ...actual,
    useAuthStore: (selector?: (s: typeof auth) => unknown) =>
      selector ? selector(auth) : auth,
    hasRole: (_user: unknown, ...roles: string[]) =>
      roles.includes("admin") ? state.isAdmin : false,
  };
});

vi.mock("@/lib/action-access", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/action-access")>()),
  hasActionAccess: (_user: unknown, _action: string, level: string) =>
    level === "view" ? true : state.canGenerate,
}));

vi.mock("@/lib/section-access", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/section-access")>()),
  hasSectionAccess: () => state.canGenerate,
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showActionToast: vi.fn(),
    showSuccess: vi.fn(),
    showError: vi.fn(),
  }),
}));

// Zakładki z własnymi testami — tu wystarczy wiedzieć, która stoi na ekranie.
vi.mock("@/components/v2/b2b-generator/documents/DocumentsTab", () => ({
  DocumentsTab: () => <p>Zakładka dokumentów</p>,
}));
vi.mock("@/components/v2/b2b-generator/documents/AnnexGeneratorTab", () => ({
  AnnexGeneratorTab: ({ canGenerate }: { canGenerate: boolean }) => (
    <p>Zakładka aneksów {canGenerate ? "z kreatorem" : "bez kreatora"}</p>
  ),
}));
vi.mock("@/components/v2/b2b-generator/MandateAgreementForm", () => ({
  MandateAgreementForm: () => <p>Formularz zlecenia</p>,
}));
vi.mock("@/components/v2/b2b-generator/esign/CompanySignaturesPanel", () => ({
  CompanySignaturesPanel: () => null,
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: () => Promise.resolve({ data: [] }) },
  b2bGeneratorApi: {
    generated: () => Promise.resolve([]),
    roles: () => Promise.resolve([]),
    nextNumber: () =>
      Promise.resolve({ contract_number: "1500/2026", year: 2026, seq: 1500 }),
    clientsLookup: () => Promise.resolve([]),
    prefill: () => Promise.reject(new Error("brak")),
    companyLookup: () => Promise.reject(new Error("brak")),
  },
  extractErrorMsg: (error: unknown) =>
    error instanceof Error ? error.message : "Błąd",
}));

import { B2BContractGeneratorV2 } from "@/components/v2/pages/B2BContractGeneratorV2";

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

beforeEach(() => {
  state.params = new URLSearchParams();
  state.canGenerate = true;
  state.isAdmin = true;
  state.replaceUrl.mockReset();
});

function renderPage(search = "") {
  state.params = new URLSearchParams(search);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <B2BContractGeneratorV2 />
    </QueryClientProvider>,
  );
}

const tabNames = () =>
  screen.getAllByRole("tab").map((t) => t.textContent?.trim());
const selectedTab = () =>
  screen.getAllByRole("tab").find((t) => t.getAttribute("aria-selected") === "true")
    ?.textContent;
const checkedPhase = () =>
  screen
    .getByRole("radiogroup", { name: "Faza umowy" })
    .querySelector('[aria-checked="true"]')?.textContent;

describe("Generator umów — pięć zakładek", () => {
  it("osoba z generowaniem: pięć zakładek, start na „Nowej umowie” w układzie kroków", () => {
    renderPage();
    expect(tabNames()).toEqual([
      "Nowa umowa",
      "Nowy aneks",
      "Umowy",
      "Dokumenty",
      "Zakresy ról",
    ]);
    expect(selectedTab()).toBe("Nowa umowa");
    expect(screen.getByRole("navigation", { name: "Kroki umowy" })).toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: "Rodzaj umowy" })).toBeInTheDocument();
  });

  it.each([
    ["tab=generated", "Bieżące", "Umowy bieżące"],
    ["tab=current", "Bieżące", "Umowy bieżące"],
    ["tab=no-project", "Bez projektu", "Umowy bez projektu"],
    ["tab=without-project", "Bez projektu", "Umowy bez projektu"],
    ["tab=closed", "Zakończone", "Zakończone umowy"],
    ["tab=ended", "Zakończone", "Zakończone umowy"],
  ])("stary link `?%s` otwiera „Umowy” w fazie „%s”", async (search, phase, title) => {
    renderPage(search);
    expect(selectedTab()).toBe("Umowy");
    expect(checkedPhase()).toBe(phase);
    expect(await screen.findByText(title)).toBeInTheDocument();
    // Rodzaj umowy dotyczy tylko „Nowej umowy”.
    expect(screen.queryByRole("radiogroup", { name: "Rodzaj umowy" })).toBeNull();
  });

  it.each([
    ["tab=annexes", "Nowy aneks", "Zakładka aneksów z kreatorem"],
    ["tab=aneksy", "Nowy aneks", "Zakładka aneksów z kreatorem"],
    ["tab=documents&new=preliminary_b2b", "Dokumenty", "Zakładka dokumentów"],
    ["tab=roles", "Zakresy ról", "Zakresy ról"],
  ])("`?%s` otwiera zakładkę „%s”", (search, tab, content) => {
    renderPage(search);
    expect(selectedTab()).toBe(tab);
    expect(screen.getAllByText(content).length).toBeGreaterThan(0);
  });

  it("faza i zakładka zapisują się w adresie dawnym kluczem, bez frazy i kroku", async () => {
    const user = userEvent.setup({ delay: null });
    renderPage("tab=generated&q=1500&krok=partner");
    await user.click(screen.getByRole("radio", { name: "Zakończone" }));
    expect(state.replaceUrl).toHaveBeenLastCalledWith(
      "/contracts/b2b-generator?tab=closed",
    );
    expect(await screen.findByText("Zakończone umowy")).toBeInTheDocument();

    // „Umowy” po powrocie wraca do ostatniej fazy.
    await user.click(screen.getByRole("tab", { name: "Dokumenty" }));
    expect(state.replaceUrl).toHaveBeenLastCalledWith(
      "/contracts/b2b-generator?tab=documents",
    );
    await user.click(screen.getByRole("tab", { name: "Umowy" }));
    expect(state.replaceUrl).toHaveBeenLastCalledWith(
      "/contracts/b2b-generator?tab=closed",
    );
  });

  it("bez generowania: bez „Nowej umowy”, „Aneksy” zamiast „Nowy aneks”, start na „Umowach”", async () => {
    state.canGenerate = false;
    state.isAdmin = false;
    renderPage();
    expect(tabNames()).toEqual(["Aneksy", "Umowy", "Dokumenty"]);
    expect(selectedTab()).toBe("Umowy");
    expect(checkedPhase()).toBe("Bieżące");
    expect(screen.getByText("Dostęp tylko do rejestru")).toBeInTheDocument();
    // Link do „Nowej umowy” bez prawa generowania zostaje na rejestrze.
    await waitFor(() => expect(screen.getByText("Umowy bieżące")).toBeInTheDocument());
  });

  it("sam `?q=<numer>` (podsumowanie dnia, pulpit) szuka umowy w „Umowach”, nie otwiera formularza", async () => {
    renderPage("q=1520%2F2026");
    expect(selectedTab()).toBe("Umowy");
    expect(checkedPhase()).toBe("Bieżące");
    expect(
      await screen.findByRole("textbox", { name: "Szukaj wygenerowanych umów" }),
    ).toHaveValue("1520/2026");
  });

  it("bez generowania link `?tab=generator` nie otwiera formularza", () => {
    state.canGenerate = false;
    renderPage("tab=generator");
    expect(selectedTab()).toBe("Umowy");
    expect(screen.queryByRole("navigation", { name: "Kroki umowy" })).toBeNull();
  });
});
