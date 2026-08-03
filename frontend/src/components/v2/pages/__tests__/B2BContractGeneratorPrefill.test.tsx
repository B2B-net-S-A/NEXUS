import { describe, expect, it, vi } from "vitest";

import type { B2BRole } from "@/lib/api";

// Import Generatora pociąga za sobą next/navigation, Toast i klienta API —
// mockujemy je (jak w pozostałych testach tej strony), by dało się zaimportować
// czystą funkcję `areaPrefillDescription` bez bootstrapu axiosa/routera.
const mocks = vi.hoisted(() => ({ apiGet: vi.fn(), push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showActionToast: vi.fn(),
    showSuccess: vi.fn(),
    showError: vi.fn(),
  }),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  b2bGeneratorApi: {},
  extractErrorMsg: (error: unknown) =>
    error instanceof Error ? error.message : "Błąd",
  signingApi: {},
}));

import { areaPrefillDescription } from "@/components/v2/pages/B2BContractGeneratorV2";

function role(overrides: Partial<B2BRole> = {}): B2BRole {
  return {
    id: 3,
    category_key: "data_ai",
    category_label_pl: "Dane i AI",
    category_label_en: "Data & AI",
    slug: "data-engineering",
    name_pl: "Data Engineering",
    name_en: "Data Engineering",
    area_label_pl: "Data Engineering",
    area_label_en: "Data Engineering",
    scope_pl: [
      "Projektowanie potoków przetwarzania danych.",
      "Optymalizacja modeli i zapytań analitycznych.",
      "Wsparcie migracji do architektury chmurowej.",
    ],
    scope_en: [
      "Designing data processing pipelines.",
      "Optimising analytical models and queries.",
      "Supporting migration to a cloud architecture.",
    ],
    display_order: 0,
    is_active: true,
    ...overrides,
  };
}

describe("areaPrefillDescription", () => {
  it("zwraca null, gdy nie wybrano obszaru", () => {
    expect(
      areaPrefillDescription({
        role: null,
        language: "pl",
        clientName: "",
        descTouched: false,
      }),
    ).toBeNull();
  });

  it("nie nadpisuje opisu dotkniętego (z oferty lub ręcznie)", () => {
    expect(
      areaPrefillDescription({
        role: role(),
        language: "pl",
        clientName: "Nordea Bank Abp",
        descTouched: true,
      }),
    ).toBeNull();
  });

  it("wypełnia opis po wybraniu obszaru (PL) — obszar + zakres, nigdy pusto", () => {
    const out = areaPrefillDescription({
      role: role(),
      language: "pl",
      clientName: "",
      descTouched: false,
    });
    expect(out).not.toBeNull();
    expect(out).toContain("Świadczenie usług w obszarze: Data Engineering");
    expect(out).toContain("Projektowanie potoków przetwarzania danych.");
    expect((out ?? "").trim().length).toBeGreaterThan(0);
  });

  it("dokłada nazwę Klienta, gdy podana", () => {
    const out = areaPrefillDescription({
      role: role(),
      language: "pl",
      clientName: "Nordea Bank Abp",
      descTouched: false,
    });
    expect(out).toContain("na rzecz Klienta Nordea Bank Abp");
  });

  it("wypełnia opis po angielsku", () => {
    const out = areaPrefillDescription({
      role: role(),
      language: "en",
      clientName: "Nordea Bank Abp",
      descTouched: false,
    });
    expect(out).toContain("Provision of services in the area of Data Engineering");
    expect(out).toContain("for the Client Nordea Bank Abp");
  });

  // Regresja: wybór OFERTY (rekrutacji) nie jest już parametrem tej decyzji —
  // gdy opis nie został dotknięty, wybór obszaru wypełnia pole niezależnie od
  // tego, czy wskazano ofertę. Wcześniej warunek na ofercie zostawiał je puste.
  it("wypełnia opis nawet w scenariuszu z wybraną ofertą bez opisu", () => {
    const out = areaPrefillDescription({
      role: role(),
      language: "pl",
      clientName: "",
      descTouched: false, // oferta bez opisu → flaga nietknięta
    });
    expect(out).not.toBeNull();
    expect((out ?? "").length).toBeGreaterThan(0);
  });
});
