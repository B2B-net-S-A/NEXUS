/**
 * Kartoteka osoby: daty, które widzą tylko osoba, Kadry i Płace (koniec
 * zwolnienia ze składek, „składki od”, staż do urlopu, zaświadczenie ZUS,
 * podpowiedź wymiaru). Przełożonemu serwer ich nie przysyła — pola nie ma
 * w odpowiedzi, więc wiersza nie ma na ekranie. `null` od Kadr to „brak”.
 * Znacznik „Uczeń lub student” przełożony widzi. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PersonFull } from "@/lib/api/hr";

const mocks = vi.hoisted(() => ({ person: null as unknown }));

vi.mock("@/lib/api", () => ({
  api: {
    get: async (url: string) => {
      if (url === "/api/hr/people") return { data: { items: [], total: 0 } };
      if (url === "/api/hr/people/101") return { data: mocks.person };
      throw Object.assign(new Error(url), { response: { status: 500 } });
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
// Sekcje modułów mają własne testy — tu tylko karty kartoteki.
vi.mock("@/components/hr/lifecycle/LifecycleProfileSection", () => ({
  LifecycleProfileSection: () => null,
}));
vi.mock("@/components/hr/payroll/PayrollProfileSection", () => ({
  PayrollProfileSection: () => null,
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

/** Odpowiedź dla przełożonego: bez pól Kadr (lustro `HR_ONLY_FIELDS` backendu). */
function forManager(person: PersonFull): PersonFull {
  const {
    contribution_exempt_until: _until,
    contributions_from: _from,
    leave_seniority_years: _seniority,
    zus_certificate_received_on: _zus,
    suggested_entitlement_days: _suggested,
    ...rest
  } = person;
  return rest as PersonFull;
}

function renderProfile(person: PersonFull, asHr: boolean) {
  mocks.person = person;
  // Pola zatrudnienia stoją w zakładce „Nieobecności i godziny” (`#czas`, dawniej „Czas i przerwy”).
  window.history.replaceState(null, "", "#czas");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PersonProfile
        userId={101}
        config={hrConfig(asHr ? { people_admin: true } : { is_manager: true, direct_reports: 1 })}
      />
    </QueryClientProvider>,
  );
  return screen.findByRole("heading", { level: 1, name: /Ola Przykładowa/ });
}

describe("PersonProfile — pola Kadr", () => {
  beforeEach(() => {
    mocks.person = null;
  });

  it("Kadry, zlecenie: koniec zwolnienia i „składki od”; `null` = brak daty", async () => {
    await renderProfile(olaFull("zlecenie"), true);
    expect(screen.getByText("bez składek do 30.06.2027")).toBeInTheDocument();
    expect(screen.getByText("Składki od")).toBeInTheDocument();
  });

  it("Kadry, zlecenie bez daty końca zwolnienia: „brak daty końca zwolnienia”", async () => {
    await renderProfile(
      { ...olaFull("zlecenie"), contribution_exempt_until: null, contributions_from: null },
      true,
    );
    expect(screen.getByText("tak — brak daty końca zwolnienia")).toBeInTheDocument();
    expect(screen.queryByText("Składki od")).toBeNull();
  });

  it("przełożony, zlecenie: sam znacznik studenta, bez dat i bez „brak daty”", async () => {
    await renderProfile(forManager(olaFull("zlecenie")), false);
    expect(screen.getByText("Uczeń lub student").nextSibling).toHaveTextContent(/^tak$/);
    expect(screen.queryByText(/brak daty końca zwolnienia/)).toBeNull();
    expect(screen.queryByText(/bez składek do/)).toBeNull();
    expect(screen.queryByText("Składki od")).toBeNull();
  });

  it("Kadry, umowa o pracę: staż do urlopu, zaświadczenie ZUS i podpowiedź wymiaru", async () => {
    await renderProfile(olaFull("uop"), true);
    expect(screen.getByText("Staż do urlopu").nextSibling).toHaveTextContent("12 lat");
    expect(screen.getByText("Zaświadczenie z ZUS").nextSibling).toHaveTextContent("04.05.2026");
    expect(screen.getByText(/Wymiar według stażu \(12 lat\): 26 dni/)).toBeInTheDocument();
  });

  it("Kadry, umowa o pracę bez stażu i zaświadczenia: wiersze z „—”", async () => {
    await renderProfile(
      {
        ...olaFull("uop"),
        leave_seniority_years: null,
        zus_certificate_received_on: null,
        suggested_entitlement_days: null,
      },
      true,
    );
    expect(screen.getByText("Staż do urlopu").nextSibling).toHaveTextContent("—");
    expect(screen.getByText("Zaświadczenie z ZUS").nextSibling).toHaveTextContent("—");
  });

  it("przełożony, umowa o pracę: bez wierszy stażu i zaświadczenia ZUS", async () => {
    await renderProfile(forManager(olaFull("uop")), false);
    expect(screen.getAllByText("Forma").length).toBeGreaterThan(0);
    expect(screen.queryByText("Staż do urlopu")).toBeNull();
    expect(screen.queryByText("Zaświadczenie z ZUS")).toBeNull();
    expect(screen.queryByText(/Wymiar według stażu/)).toBeNull();
  });
});
