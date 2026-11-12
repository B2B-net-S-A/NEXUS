/**
 * „Na liście dzwonienia” na karcie firmy (decyzja Artura 12.11.2026): kto dzwoni, kampania,
 * wynik i powrót, bez numeru telefonu; nic, gdy firmy nie ma na żadnej liście.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CompanyCallRecord } from "@/lib/api/sales-calling";

let response: { isSuccess: boolean; data?: CompanyCallRecord[] } = { isSuccess: true, data: [] };

vi.mock("@/lib/api/sales-calling", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-calling")>()),
  useCompanyCallRecords: () => response,
}));

import { CompanyCallLists } from "../calling/CompanyCallLists";

const row = (overrides: Partial<CompanyCallRecord> = {}): CompanyCallRecord => ({
  record_id: 1,
  campaign: { id: 3, name: "BE Leady" },
  assignee: { id: 9, name: "Marcel Testowy" },
  person_name: "Ewa Testowa",
  state: "offer_sent",
  callback_on: "2026-11-16",
  last_outcome_at: "2026-11-11T10:00:00Z",
  ...overrides,
});

beforeEach(() => {
  response = { isSuccess: true, data: [] };
});

describe("Na liście dzwonienia", () => {
  it("pokazuje kto dzwoni, kampanię, wynik i kiedy wraca", () => {
    response = { isSuccess: true, data: [row()] };
    render(<CompanyCallLists companyId={7} />);
    const section = screen.getByRole("region", { name: "Na liście dzwonienia" });
    expect(section).toHaveTextContent("Marcel Testowy");
    expect(section).toHaveTextContent("BE Leady");
    expect(section).toHaveTextContent("Oferta ogólna wysłana");
    expect(section).toHaveTextContent("wraca 16.11");
    expect(section).toHaveTextContent("Ewa Testowa");
  });

  it("„Nie zainteresowany” bez daty nie wraca, a spotkanie nie ma daty powrotu", () => {
    response = {
      isSuccess: true,
      data: [
        row({ record_id: 1, state: "not_interested", callback_on: null }),
        row({ record_id: 2, state: "meeting_booked", callback_on: "2026-11-20" }),
      ],
    };
    render(<CompanyCallLists companyId={7} />);
    const section = screen.getByRole("region", { name: "Na liście dzwonienia" });
    expect(section).toHaveTextContent("nie wraca");
    expect(section).not.toHaveTextContent("wraca 20.11");
  });

  it("firma bez listy i błąd zapytania nie dokładają niczego do karty", () => {
    const { container, rerender } = render(<CompanyCallLists companyId={7} />);
    expect(container).toBeEmptyDOMElement();
    response = { isSuccess: false };
    rerender(<CompanyCallLists companyId={8} />);
    expect(container).toBeEmptyDOMElement();
  });
});
