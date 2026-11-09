/**
 * Mapa decyzyjna pokazuje kontakt i notatkę osoby; okno nowego kontaktu
 * nie wysyła formularza bez firmy.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AtlasMotion, Ref } from "@/lib/api/sales";

const mutate = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useCreateSalesContact: () => ({ mutate, isPending: false }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess }) }));
vi.mock("../CompanyPicker", () => ({
  CompanyPicker: ({ onChange }: { onChange: (company: Ref) => void }) => (
    <button type="button" onClick={() => onChange({ id: 7, name: "Firma" })}>
      Wybierz firmę
    </button>
  ),
}));

import { ContactCreateDialog } from "../ContactCreateDialog";
import { SalesMotionPanel } from "../SalesMotionPanel";

const motion = (entry: Record<string, unknown>): AtlasMotion =>
  ({ it_factory: { decision_map: [{ key: "k1", decision_level: 1, ...entry }] }, products: [] }) as unknown as AtlasMotion;

describe("mapa decyzyjna", () => {
  it("pokazuje telefon, mail, LinkedIn i notatkę osoby", () => {
    render(
      <SalesMotionPanel
        opportunityId={1}
        motion={motion({
          name: "Osoba",
          phone: "+48 600 100 200",
          email: "osoba@example.com",
          linkedin_url: "https://www.linkedin.com/in/osoba",
          notes: "Właściciel budżetu",
        })}
      />,
    );
    expect(screen.getByRole("link", { name: /\+48 600 100 200/ })).toHaveAttribute("href", "tel:+48600100200");
    // Karta jest zwarta: mail, LinkedIn i notatka po rozwinięciu osoby.
    fireEvent.click(screen.getByRole("button", { name: /Osoba/ }));
    expect(screen.getByRole("link", { name: /osoba@example.com/ })).toHaveAttribute("href", "mailto:osoba@example.com");
    expect(screen.getByRole("link", { name: /LinkedIn/ })).toHaveAttribute("href", "https://www.linkedin.com/in/osoba");
    expect(screen.getByText("Właściciel budżetu")).toBeInTheDocument();
  });

  it("nie robi linku z adresu LinkedIn innego niż http(s)", () => {
    render(<SalesMotionPanel opportunityId={1} motion={motion({ name: "Osoba", linkedin_url: "javascript:alert(1)" })} />);
    expect(screen.queryByRole("link", { name: /LinkedIn/ })).toBeNull();
  });
});

describe("poziom decyzyjny na mapie", () => {
  it("po rozwinięciu osoby widać poziom, także bez prawa edycji", () => {
    render(<SalesMotionPanel opportunityId={1} motion={motion({ name: "Osoba", decision_level: 1 })} />);
    expect(screen.queryByText(/Zarząd \/ C-level/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Osoba/ }));
    expect(screen.getByText(/Zarząd \/ C-level/)).toBeInTheDocument();
  });

  it("osoba bez poziomu nie dostaje poziomu z domysłu", () => {
    render(<SalesMotionPanel opportunityId={1} motion={motion({ name: "Osoba", decision_level: null })} />);
    fireEvent.click(screen.getByRole("button", { name: /Osoba/ }));
    expect(screen.queryByText(/Zespół/)).toBeNull();
  });
});

describe("nowy kontakt", () => {
  beforeEach(() => {
    mutate.mockClear();
    showError.mockClear();
  });

  const typeName = (value: string) =>
    fireEvent.change(screen.getByLabelText("Imię i nazwisko"), { target: { value } });

  it("bez nazwiska i bez firmy nic nie wysyła", () => {
    render(<ContactCreateDialog onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Dodaj kontakt" }));
    expect(showError).toHaveBeenLastCalledWith("Podaj imię i nazwisko.");
    typeName("Nowa Osoba");
    fireEvent.click(screen.getByRole("button", { name: "Dodaj kontakt" }));
    expect(showError).toHaveBeenLastCalledWith("Wybierz firmę z kartoteki sprzedaży.");
    expect(mutate).not.toHaveBeenCalled();
  });

  it("wysyła kontakt przy wybranej firmie, puste pola jako null", () => {
    render(<ContactCreateDialog onClose={() => {}} />);
    typeName("  Nowa Osoba ");
    fireEvent.click(screen.getByRole("button", { name: "Wybierz firmę" }));
    fireEvent.click(screen.getByRole("button", { name: "Dodaj kontakt" }));
    expect(mutate.mock.calls[0][0]).toMatchObject({ company_id: 7, full_name: "Nowa Osoba", email: null, title: null });
  });
});
