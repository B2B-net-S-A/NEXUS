/**
 * Nowa firma z NIP-u (⌘K → `/sales/companies?nowa=<NIP>`): dane z rejestru od razu,
 * nazwa bez formy prawnej i dopisanie NIP-u do karty o tej samej nazwie. Dane fikcyjne.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RegistryCompany } from "@/lib/api/sales";
import type { CompanyIdentityMatch } from "@/lib/api/sales-handoffs";

const createCompany = vi.fn();
const patchCompany = vi.fn();
const registryLookup = vi.fn();
const identity = vi.fn();
const companiesByNip = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();

const mutation = (mutate: ReturnType<typeof vi.fn>) => ({ mutate, isPending: false });

vi.mock("@/lib/api/sales-handoffs", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-handoffs")>()),
  useCompanyIdentity: (input: { name?: string }) => identity(input),
}));
vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useCreateSalesCompany: () => mutation(createCompany),
  useUpdateSalesCompany: () => mutation(vi.fn()),
  usePatchSalesCompany: () => mutation(patchCompany),
  useSalesCompanies: (filters: { q?: string }) => companiesByNip(filters),
  useOwnerCandidates: () => ({ data: [] }),
  useRegistryLookup: () => mutation(registryLookup),
}));
vi.mock("@/lib/use-debounced-value", () => ({ useDebouncedValue: <T,>(value: T) => value }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess }) }));
vi.mock("../useOwnerFilterOptions", () => ({ useOwnerFilterOptions: () => [] }));
vi.mock("../CompanyPicker", () => ({ CompanyPicker: () => null }));
vi.mock("../SalesSelect", () => ({ SalesSelect: () => null }));
vi.mock("@/components/ds/AppModal", () => ({
  AppModal: ({ title, children, footer }: { title: string; children: ReactNode; footer?: ReactNode }) => (
    <div role="dialog" aria-label={title}>
      {children}
      {footer}
    </div>
  ),
}));

import { CompanyFormDialog, nameWithoutLegalForm } from "../CompanyFormDialog";

const FOUND: RegistryCompany = {
  name: "FIRMA TESTOWA SPÓŁKA AKCYJNA",
  nip: "1111111111",
  regon: "123456785",
  krs: "0000012345",
  address: "PROSTA 1, 00-001 WARSZAWA",
  hq_city: "Warszawa",
  source: "biala_lista",
};

const SAME_NAME: CompanyIdentityMatch = {
  id: 7,
  name: "FIRMA TESTOWA",
  hq_city: null,
  domain: null,
  open_opportunities: 1,
  reason: "name",
};

beforeEach(() => {
  vi.clearAllMocks();
  companiesByNip.mockReturnValue({ data: { items: [], total: 0 }, isSuccess: true });
  registryLookup.mockImplementation((_nip: string, options: { onSuccess: (found: RegistryCompany) => void }) =>
    options.onSuccess(FOUND),
  );
  identity.mockImplementation((input: { name?: string }) => ({
    data: {
      domain: null,
      domain_source: null,
      matches: input.name === "FIRMA TESTOWA" ? [SAME_NAME] : [],
    },
  }));
});

describe("nameWithoutLegalForm", () => {
  it.each([
    ["FIRMA TESTOWA SPÓŁKA AKCYJNA", "FIRMA TESTOWA"],
    ["FIRMA TESTOWA SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ", "FIRMA TESTOWA"],
    ["Firma Testowa sp. z o.o.", "Firma Testowa"],
    ["FIRMA TESTOWA SPÓŁKA KOMANDYTOWO-AKCYJNA", "FIRMA TESTOWA"],
    ["Spółka Akcyjna Testowa", "Spółka Akcyjna Testowa"],
  ])("%s → %s", (input, expected) => {
    expect(nameWithoutLegalForm(input)).toBe(expected);
  });
});

describe("nowa firma z NIP-u z palety", () => {
  it("pobiera rejestr od razu i proponuje dopisanie NIP-u do karty o tej nazwie", () => {
    const onSaved = vi.fn();
    patchCompany.mockImplementation((_vars, options: { onSuccess: (saved: unknown) => void }) =>
      options.onSuccess({ id: 7, name: "FIRMA TESTOWA" }),
    );
    render(<CompanyFormDialog open onOpenChange={vi.fn()} initialNip="1111111111" onSaved={onSaved} />);

    expect(registryLookup).toHaveBeenCalledTimes(1);
    expect(registryLookup.mock.calls[0][0]).toBe("1111111111");
    expect(screen.getByLabelText("Nazwa")).toHaveValue("FIRMA TESTOWA");
    expect(screen.getByLabelText("Pełna nazwa prawna")).toHaveValue("FIRMA TESTOWA SPÓŁKA AKCYJNA");
    expect(screen.getByTestId("registry-summary").textContent).toContain("KRS 0000012345");
    expect(screen.getByTestId("registry-same-name").textContent).toContain("bez NIP-u 111-111-11-11");

    fireEvent.click(screen.getByRole("button", { name: "Dopisz NIP do tej karty" }));
    // Tylko NIP: resztę dopisze sprawdzenie rejestru po zapisie, bez nadpisywania pól człowieka.
    expect(patchCompany.mock.calls[0][0]).toEqual({ id: 7, payload: { nip: "1111111111" } });
    expect(onSaved).toHaveBeenCalledWith({ id: 7, name: "FIRMA TESTOWA" });
    expect(createCompany).not.toHaveBeenCalled();
  });

  it("nowa karta tylko świadomie i z KRS oraz REGON-em z rejestru", () => {
    render(<CompanyFormDialog open onOpenChange={vi.fn()} initialNip="1111111111" />);
    expect(screen.queryByRole("button", { name: "Dodaj firmę" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "To inna spółka — dodaj nową kartę" }));
    expect(createCompany.mock.calls[0][0]).toMatchObject({
      name: "FIRMA TESTOWA",
      legal_name: "FIRMA TESTOWA SPÓŁKA AKCYJNA",
      nip: "1111111111",
      krs: "0000012345",
      regon: "123456785",
      hq_city: "Warszawa",
      allow_duplicate: true,
    });
  });

  it("bez karty o tej nazwie zostaje zwykłe „Dodaj firmę” z kontrolą dubli serwera", () => {
    identity.mockReturnValue({ data: { domain: null, domain_source: null, matches: [] } });
    render(<CompanyFormDialog open onOpenChange={vi.fn()} initialNip="1111111111" />);
    expect(screen.queryByTestId("registry-same-name")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj firmę" }));
    expect(createCompany.mock.calls[0][0]).toMatchObject({ name: "FIRMA TESTOWA", allow_duplicate: false });
  });

  it("zmiana NIP-u po pobraniu nie wysyła KRS-u innej firmy", () => {
    identity.mockReturnValue({ data: { domain: null, domain_source: null, matches: [] } });
    render(<CompanyFormDialog open onOpenChange={vi.fn()} initialNip="1111111111" />);
    fireEvent.change(screen.getByLabelText("NIP"), { target: { value: "2222222222" } });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj firmę" }));
    const payload = createCompany.mock.calls[0][0];
    expect(payload.nip).toBe("2222222222");
    expect(payload).not.toHaveProperty("krs");
    expect(payload).not.toHaveProperty("regon");
  });

  it("ręczne „Nowa firma” nie pyta rejestru samo i nie pokazuje dopisania", () => {
    render(<CompanyFormDialog open onOpenChange={vi.fn()} />);
    expect(registryLookup).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("NIP"), { target: { value: "1111111111" } });
    fireEvent.click(screen.getByRole("button", { name: "Pobierz z rejestru" }));
    expect(screen.getByLabelText("Nazwa")).toHaveValue("FIRMA TESTOWA");
    expect(screen.queryByTestId("registry-same-name")).toBeNull();
  });
});

describe("okno z przycisku Jarvisa (bez sprawdzenia w palecie)", () => {
  it("NIP na istniejącej karcie: wskazuje kartę zamiast dopisywać NIP do innej", () => {
    companiesByNip.mockReturnValue({
      data: { items: [{ id: 9, name: "Inna Karta", nip: "1111111111" }], total: 1 },
      isSuccess: true,
    });
    render(<CompanyFormDialog open onOpenChange={vi.fn()} initialNip="1111111111" />);
    expect(companiesByNip).toHaveBeenCalledWith({ q: "1111111111" });
    expect(screen.getByTestId("registry-nip-taken").textContent).toContain("Inna Karta");
    expect(screen.queryByTestId("registry-same-name")).toBeNull();
    expect(screen.queryByRole("button", { name: "Dopisz NIP do tej karty" })).toBeNull();
  });

  it("NIP tylko jako fragment innego numeru nie blokuje", () => {
    companiesByNip.mockReturnValue({
      data: { items: [{ id: 9, name: "Inna Karta", nip: "9111111111" }], total: 1 },
      isSuccess: true,
    });
    render(<CompanyFormDialog open onOpenChange={vi.fn()} initialNip="1111111111" />);
    expect(screen.queryByTestId("registry-nip-taken")).toBeNull();
    expect(screen.getByTestId("registry-same-name")).toBeTruthy();
  });
});
