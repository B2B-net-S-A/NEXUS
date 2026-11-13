/**
 * Kontakty jako jedna lista (decyzje Artura 13.11.2026): osoba „nie pracuje”
 * stoi na końcu, wyszarzona, z plakietką; bez plakietek „bot” i „do weryfikacji”;
 * każdy wiersz da się edytować, a stan „nie pracuje” cofnąć w oknie kontaktu.
 * Dane fikcyjne.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AtlasMotion, SalesContact } from "@/lib/api/sales";

const link = vi.fn();
const contacts = vi.fn();

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useSalesContacts: () => contacts(),
  useCreateSalesContact: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateSalesContact: () => ({ mutate: vi.fn(), isPending: false }),
  useArchiveSalesContact: () => ({ mutate: vi.fn(), isPending: false }),
  useLinkContactCompany: () => ({ mutate: link, isPending: false }),
  useUnlinkContactCompany: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (select: (state: unknown) => unknown) =>
    select({ user: { id: 1, role: "admin", permissions: ["sales_view", "sales_edit"] } }),
}));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: () => true,
}));
vi.mock("../CompanyPicker", () => ({ CompanyPicker: () => null }));

import { ContactsSection, sortGoneLast } from "../ContactsSection";
import { SalesMotionPanel } from "../SalesMotionPanel";

const COMPANY = 7;

function person(id: number, name: string, isCurrent: boolean, title: string): SalesContact {
  return {
    id,
    company_id: COMPANY,
    company_name: "Fabryka",
    full_name: name,
    first_name: null,
    last_name: null,
    title,
    email: null,
    phone: null,
    mobile_phone: null,
    linkedin_url: null,
    seniority: null,
    department: null,
    is_executive: false,
    notes: null,
    source: "bot-kontakty",
    archived_at: null,
    created_at: "2026-11-13T09:00:00Z",
    do_not_contact_at: null,
    companies: [
      { company_id: COMPANY, company_name: "Fabryka", role: null, title, is_primary: true, is_current: isCurrent },
    ],
  } as SalesContact;
}

const items = [
  person(1, "Ewa Przykładowa", false, "Prezes Zarządu"),
  person(2, "Jan Fikcyjny", true, "CIO"),
  person(3, "Anna Testowa", true, "CTO"),
];

describe("lista Kontakty", () => {
  beforeEach(() => {
    link.mockClear();
    contacts.mockReturnValue({
      data: { items, total: items.length },
      isLoading: false,
      isSuccess: true,
      error: null,
      refetch: vi.fn(),
    });
  });

  it("stawia osoby „nie pracuje” na końcu, w kolejności z serwera", () => {
    expect(sortGoneLast(items, COMPANY).map((c) => c.id)).toEqual([2, 3, 1]);
  });

  it("wyszarza osobę, która nie pracuje, i daje jej plakietkę, bez etykiet bota", () => {
    render(<ContactsSection companyId={COMPANY} />);
    const rows = screen.getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("Jan Fikcyjny"),
      expect.stringContaining("Anna Testowa"),
      expect.stringContaining("Ewa Przykładowa"),
    ]);
    const gone = rows[2];
    expect(within(gone).getByText("nie pracuje")).toBeInTheDocument();
    expect(gone.className).toContain("opacity-60");
    expect(within(rows[0]).queryByText("nie pracuje")).toBeNull();
    expect(screen.queryByText(/bot|do weryfikacji/i)).toBeNull();
    // Każdy wiersz edytowalny, także osoba, która odeszła.
    expect(screen.getAllByRole("button", { name: "Edytuj" })).toHaveLength(3);
  });

  it("w oknie kontaktu „Pracuje tutaj” cofa stan bez gubienia stanowiska", () => {
    render(<ContactsSection companyId={COMPANY} />);
    const rows = screen.getAllByRole("listitem");
    fireEvent.click(within(rows[2]).getByRole("button", { name: "Edytuj" }));
    expect(screen.getByText("Nie pracuje w: Fabryka")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pracuje tutaj" }));
    expect(link).toHaveBeenCalledWith(
      { company_id: COMPANY, role: null, title: "Prezes Zarządu", is_current: true },
      expect.anything(),
    );
  });
});

describe("okno kontaktu bez wiersza powiązania", () => {
  it("kontakt z Atlasa bez powiązania z firmą główną też da się oznaczyć", () => {
    const bare = { ...person(4, "Beata Bezwiersza", true, "CFO"), companies: [] };
    contacts.mockReturnValue({
      data: { items: [bare], total: 1 },
      isLoading: false,
      isSuccess: true,
      error: null,
      refetch: vi.fn(),
    });
    link.mockClear();
    render(<ContactsSection companyId={COMPANY} />);
    fireEvent.click(screen.getByRole("button", { name: "Edytuj" }));
    fireEvent.click(screen.getByRole("button", { name: "Oznacz: nie pracuje" }));
    expect(link).toHaveBeenCalledWith(
      { company_id: COMPANY, role: null, title: "CFO", is_current: false },
      expect.anything(),
    );
  });
});

describe("mapa decyzyjna", () => {
  it("osoba, której kontakt nie pracuje, ma plakietkę zamiast stanowiska", () => {
    const motion = {
      it_factory: {
        decision_map: [
          { key: "k1", name: "Ewa Przykładowa", decision_level: 1, role_in_company: "Prezes Zarządu", active: false },
          { key: "k2", name: "Jan Fikcyjny", decision_level: 1, role_in_company: "CIO", active: true },
        ],
      },
      products: [],
    } as unknown as AtlasMotion;
    render(<SalesMotionPanel opportunityId={1} motion={motion} />);
    const [ewa, jan] = screen.getAllByRole("listitem");
    expect(within(ewa).getByText("nie pracuje")).toBeInTheDocument();
    expect(within(ewa).queryByText("Prezes Zarządu")).toBeNull();
    expect(within(jan).queryByText("nie pracuje")).toBeNull();
    expect(within(jan).getByText("CIO")).toBeInTheDocument();
  });
});
