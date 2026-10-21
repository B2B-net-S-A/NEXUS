/**
 * Kartoteka osoby → zakładka „Płace i premie” (audyt 21.10.2026).
 *
 * - Dane do rozliczeń (`BillingDetailsSection`) stoją w tej zakładce, więc
 *   zakładka powstaje także wtedy, gdy płace są odmówione (Kadry bez Płac
 *   w cudzej kartotece) albo moduł płac jest wyłączony — o ile patrzący
 *   widzi dane do rozliczeń.
 * - Awaria zapytania o płace (500) to nie brak dostępu: zakładka zostaje,
 *   a karta mówi o błędzie z „Spróbuj ponownie”.
 * Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HrConfig } from "@/lib/api/hr";

const mocks = vi.hoisted(() => ({
  person: null as unknown,
  payrollStatus: 200 as number,
  payrollCalls: 0,
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: async (url: string) => {
      if (url === "/api/hr/people") return { data: { items: [], total: 0 } };
      if (url === "/api/hr/people/101") return { data: mocks.person };
      if (url === "/api/hr/payroll/people/101") {
        mocks.payrollCalls += 1;
        if (mocks.payrollStatus === 200) {
          return {
            data: {
              scope: "bonuses",
              rates: [],
              current_rate: null,
              bonuses: [],
              can_edit_rates: false,
              can_add_bonus: false,
            },
          };
        }
        throw Object.assign(new Error(url), { response: { status: mocks.payrollStatus } });
      }
      // Pozostałe sekcje: odmowa, żeby nie dokładały własnych komunikatów.
      throw Object.assign(new Error(url), { response: { status: 404 } });
    },
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
  },
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));
vi.mock("@/components/hr/payroll/PayrollProfileSection", () => ({
  PayrollProfileSection: () => <div>sekcja-plac</div>,
}));
vi.mock("@/components/hr/people/BillingDetailsSection", () => ({
  BillingDetailsSection: ({ enabled }: { enabled: boolean }) =>
    enabled ? <div>sekcja-danych-do-rozliczen</div> : null,
}));
vi.mock("@/components/hr/people/documents/PersonDocumentsSection", () => ({
  PersonDocumentsSection: () => null,
}));
vi.mock("@/components/hr/people/agreements/PersonAgreementsSection", () => ({
  PersonAgreementsSection: () => null,
}));
vi.mock("@/components/equipment/PersonEquipmentPanel", () => ({
  PersonEquipmentPanel: () => null,
}));

import { hrConfig } from "@/app/preview/hr-fixtures";
import { olaFull } from "@/app/preview/hr-person/fixtures";

import { PersonProfile } from "../PersonProfile";

function withModules(config: HrConfig, modules: Partial<HrConfig["open_modules"]>): HrConfig {
  return { ...config, open_modules: { ...config.open_modules, ...modules } };
}

async function renderProfile(config: HrConfig, hash = "") {
  mocks.person = olaFull("b2b");
  window.history.replaceState(null, "", hash ? `#${hash}` : window.location.pathname);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PersonProfile userId={101} config={config} />
    </QueryClientProvider>,
  );
  await screen.findByRole("heading", { level: 1, name: /Ola Przykładowa/ });
}

// Osoba bez formy w odpowiedzi: słowa neutralne jak B2B (21.10.2026).
const payrollTab = () => screen.queryByRole("tab", { name: /Płace i wynagrodzenie dodatkowe/ });

describe("PersonProfile — zakładka „Płace i premie”", () => {
  beforeEach(() => {
    mocks.person = null;
    mocks.payrollStatus = 200;
    mocks.payrollCalls = 0;
  });

  it("Kadry bez Płac, płace 404: zakładka zostaje z danymi do rozliczeń", async () => {
    mocks.payrollStatus = 404;
    await renderProfile(
      withModules(hrConfig({ people_admin: true }), { settlements: true }),
      "place",
    );
    expect(await screen.findByText("sekcja-danych-do-rozliczen")).toBeInTheDocument();
    expect(payrollTab()).not.toBeNull();
  });

  it("Kadry bez Płac, płace 403: przegląd mówi o braku dostępu", async () => {
    mocks.payrollStatus = 403;
    await renderProfile(withModules(hrConfig({ people_admin: true }), { settlements: true }));
    expect(await screen.findByText("Płace niedostępne dla Ciebie.")).toBeInTheDocument();
    expect(payrollTab()).not.toBeNull();
  });

  it("moduł płac wyłączony: zakładka z danymi do rozliczeń, bez pytania o płace", async () => {
    await renderProfile(
      withModules(hrConfig({ people_admin: true }), { settlements: true, payroll: false }),
      "place",
    );
    expect(await screen.findByText("sekcja-danych-do-rozliczen")).toBeInTheDocument();
    expect(screen.queryByText("sekcja-plac")).toBeNull();
    expect(mocks.payrollCalls).toBe(0);
  });

  it("awaria płac (500): zakładka zostaje, karta z błędem i „Spróbuj ponownie”", async () => {
    mocks.payrollStatus = 500;
    await renderProfile(hrConfig({ people_admin: true }));
    expect(await screen.findByText("Nie udało się wczytać płac.")).toBeInTheDocument();
    expect(screen.queryByText("Płace niedostępne dla Ciebie.")).toBeNull();
    expect(payrollTab()).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
    await vi.waitFor(() => expect(mocks.payrollCalls).toBe(2));
  });

  it("przełożony, płace 403, bez danych do rozliczeń: zakładki nie ma", async () => {
    mocks.payrollStatus = 403;
    await renderProfile(
      withModules(hrConfig({ is_manager: true, direct_reports: 1 }), { settlements: true }),
    );
    await screen.findByText("Płace niedostępne dla Ciebie.");
    expect(payrollTab()).toBeNull();
  });
});
