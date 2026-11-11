/**
 * „Zaloguj rozmowę” na karcie firmy (decyzja Artura 11.11.2026): wynik zapisuje rozmowę
 * i krok, przy jedynej otwartej szansie albo przy samej firmie.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const logCall = vi.fn();
const logCompanyCall = vi.fn();
const createActivity = vi.fn();
let contacts: object[] = [];
let opportunities: object[] = [];

const mutation = (mutate: ReturnType<typeof vi.fn>) => ({ mutate, isPending: false });

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useSalesContacts: () => ({ isSuccess: true, data: { items: contacts } }),
  useOpportunities: () => ({ isSuccess: true, data: { items: opportunities, total: opportunities.length } }),
  useLogCall: () => mutation(logCall),
  useLogCompanyCall: () => mutation(logCompanyCall),
  useCreateActivity: () => mutation(createActivity),
  useCompleteActivity: () => mutation(vi.fn()),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({ useConfirmV2: () => ({ askConfirm: vi.fn(), confirmDialog: null }) }));
vi.mock("../SalesSelect", () => ({
  SalesSelect: ({
    ariaLabel,
    value,
    onValueChange,
    options,
  }: {
    ariaLabel?: string;
    value: string;
    onValueChange: (value: string) => void;
    options: { value: string; label: string }[];
  }) => (
    <select aria-label={ariaLabel} value={value} onChange={(event) => onValueChange(event.target.value)}>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

import { CompanyCallPanel } from "../CompanyCallPanel";

const contact = (id: number, name: string, phone: string | null, extra: object = {}) => ({
  id,
  full_name: name,
  title: null,
  email: null,
  phone: null,
  mobile_phone: phone,
  do_not_contact_at: null,
  ...extra,
});
const COMPANY = { id: 7, name: "Firma Testowa" };

beforeEach(() => {
  vi.clearAllMocks();
  logCall.mockImplementation((_input, { onSuccess }) => onSuccess());
  logCompanyCall.mockImplementation((_input, { onSuccess }) => onSuccess());
  contacts = [contact(3, "Jan Testowy", "+48 600 100 200")];
  opportunities = [];
});

describe("rozmowa z karty firmy", () => {
  it("firma bez otwartej szansy: rozmowa i krok przy firmie", async () => {
    render(<CompanyCallPanel company={COMPANY} onDone={vi.fn()} />);
    expect(screen.getByText("zapisze się przy firmie")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Nie odebrał" }));
    await waitFor(() => expect(createActivity).toHaveBeenCalled());
    expect(logCompanyCall.mock.calls[0][0]).toEqual({ company_id: 7, outcome: "no_answer", contact_id: 3 });
    expect(createActivity.mock.calls[0][0]).toMatchObject({ company_id: 7, opportunity_id: null, subject: "Zadzwonić ponownie" });
    expect(logCall).not.toHaveBeenCalled();
  });

  it("jedna otwarta szansa: rozmowa zapisuje się przy niej", async () => {
    opportunities = [{ id: 21, title: "Zespół QA", status: "open" }, { id: 22, title: "Stara", status: "lost" }];
    render(<CompanyCallPanel company={COMPANY} onDone={vi.fn()} />);
    expect(screen.getByText("zapisze się przy szansie „Zespół QA”")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dodzwoniłem" }));
    await waitFor(() => expect(logCall).toHaveBeenCalled());
    expect(logCall.mock.calls[0][0]).toMatchObject({ opportunity_id: 21, outcome: "connected", contact_id: 3 });
    expect(logCompanyCall).not.toHaveBeenCalled();
  });

  it("dwie otwarte szanse: rozmowa przy firmie, bo nie wiadomo, której dotyczy", () => {
    opportunities = [{ id: 21, title: "A", status: "open" }, { id: 23, title: "B", status: "open" }];
    render(<CompanyCallPanel company={COMPANY} onDone={vi.fn()} />);
    expect(screen.getByText("zapisze się przy firmie")).toBeTruthy();
  });

  it("osoba ze sprzeciwem i bez numeru nie jest proponowana, a wybór osoby zmienia kontakt", async () => {
    contacts = [
      contact(4, "Bez Numeru", null),
      contact(5, "Ze Sprzeciwem", "+48 600 000 001", { do_not_contact_at: "2026-11-01T00:00:00Z" }),
      contact(3, "Jan Testowy", "+48 600 100 200"),
      contact(6, "Anna Druga", "+48 600 100 300"),
    ];
    render(<CompanyCallPanel company={COMPANY} onDone={vi.fn()} />);
    const select = screen.getByLabelText("Z kim rozmowa") as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.value)).toEqual(["3", "6"]);
    fireEvent.change(select, { target: { value: "6" } });
    fireEvent.click(screen.getByRole("button", { name: "Oddzwonić" }));
    await waitFor(() => expect(logCompanyCall).toHaveBeenCalled());
    expect(logCompanyCall.mock.calls[0][0].contact_id).toBe(6);
  });

  it("bez osoby z numerem mówi, gdzie go dodać, zamiast pustego panelu", () => {
    contacts = [contact(4, "Bez Numeru", null)];
    render(<CompanyCallPanel company={COMPANY} onDone={vi.fn()} />);
    expect(screen.getByText(/Nikt w kontaktach tej firmy nie ma numeru/)).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Wynik rozmowy" })).toBeNull();
  });
});
