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

import {
  areaPrefillDescription,
  partnerNameAfterLookup,
} from "@/components/v2/pages/B2BContractGeneratorV2";

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

  it("nie nadpisuje opisu dotkniętego (z rekrutacji lub ręcznie)", () => {
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
    expect(out).toContain("Partner świadczy usługi w obszarze: Data Engineering");
    expect(out).toContain("Projektowanie potoków przetwarzania danych.");
    expect((out ?? "").trim().length).toBeGreaterThan(0);
  });

  // Nazewnictwo strony świadczącej usługi musi być spójne z treścią umowy
  // (Załącznik nr 3 zna Partnera, nie Wykonawcę/Konsultanta).
  it("nazywa stronę świadczącą usługi Partnerem (PL i EN), nigdy Wykonawcą/Konsultantem", () => {
    for (const language of ["pl", "en"] as const) {
      const out =
        areaPrefillDescription({
          role: role(),
          language,
          clientName: "Nordea Bank Abp",
          descTouched: false,
        }) ?? "";
      expect(out).toContain("Partner");
      expect(out).not.toMatch(/Wykonawc|Konsultant/i);
    }
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
    expect(out).toContain(
      "The Partner provides services in the area of Data Engineering",
    );
    expect(out).toContain("for the Client Nordea Bank Abp");
  });

  // Regresja: wybór OFERTY (rekrutacji) nie jest już parametrem tej decyzji —
  // gdy opis nie został dotknięty, wybór obszaru wypełnia pole niezależnie od
  // tego, czy wskazano ofertę. Wcześniej warunek na ofercie zostawiał je puste.
  it("wypełnia opis nawet w scenariuszu z wybraną rekrutacją bez opisu", () => {
    const out = areaPrefillDescription({
      role: role(),
      language: "pl",
      clientName: "",
      descTouched: false, // rekrutacja bez opisu → flaga nietknięta
    });
    expect(out).not.toBeNull();
    expect((out ?? "").length).toBeGreaterThan(0);
  });
});

describe("partnerNameAfterLookup", () => {
  // Sedno zgłoszenia: wybrany „Rafał Korecki", a lookup NIP-u firmy (JDG) zwraca
  // „RAFAŁ WASILEWSKI" — rejestr NIE może nadpisać nazwiska kandydata.
  it("nie nadpisuje nazwiska kandydata właścicielem JDG z rejestru", () => {
    expect(partnerNameAfterLookup("Rafał Korecki", "RAFAŁ WASILEWSKI")).toBe(
      "Rafał Korecki",
    );
  });

  it("nie nadpisuje ręcznie wpisanego nazwiska", () => {
    expect(partnerNameAfterLookup("Jan Kowalski", "ANNA NOWAK")).toBe(
      "Jan Kowalski",
    );
  });

  // Fallback: gdy pole jest puste (np. brak nazwiska kandydata), rejestr może je
  // uzupełnić właścicielem JDG.
  it("uzupełnia puste pole właścicielem z rejestru", () => {
    expect(partnerNameAfterLookup("", "RAFAŁ WASILEWSKI")).toBe(
      "RAFAŁ WASILEWSKI",
    );
  });

  it("traktuje same białe znaki jak pole puste", () => {
    expect(partnerNameAfterLookup("   ", "RAFAŁ WASILEWSKI")).toBe(
      "RAFAŁ WASILEWSKI",
    );
  });

  // Spółka → rejestr zwraca `person = null`; pole zostaje takie, jakie było
  // (nazwisko kandydata albo puste), nigdy nie ląduje tam „null"/"undefined".
  it("dla spółki (person = null) zostawia bieżącą wartość", () => {
    expect(partnerNameAfterLookup("Rafał Korecki", null)).toBe("Rafał Korecki");
    expect(partnerNameAfterLookup("", null)).toBe("");
    expect(partnerNameAfterLookup("", undefined)).toBe("");
  });
});
