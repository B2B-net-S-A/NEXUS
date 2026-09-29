import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DocumentFieldDef, RateItemValue } from "@/lib/api/b2bDocuments";

const companyLookup = vi.fn();
vi.mock("@/lib/api", () => ({
  b2bGeneratorApi: { companyLookup: (...args: unknown[]) => companyLookup(...args) },
  default: { get: vi.fn(() => Promise.resolve({ data: [] })) },
}));

import {
  RateItemsField,
  RegistryLookupButton,
} from "@/components/v2/b2b-generator/documents/AnnexFieldControls";

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

function RateHarness({ onValue }: { onValue: (items: RateItemValue[]) => void }) {
  const [items, setItems] = React.useState<RateItemValue[]>([]);
  return (
    <RateItemsField
      id="rates"
      value={items}
      onChange={(next) => {
        setItems(next);
        onValue(next);
      }}
    />
  );
}

const NIP_FIELD: DocumentFieldDef = {
  key: "new_nip",
  label: "NIP działalności",
  kind: "text",
  required: true,
  sensitive: false,
  help: null,
  options: [],
  show_if: null,
  group: "change",
  lookup: "registry",
  lookup_fills: [
    ["name", "new_legal_name"],
    ["address", "new_business_address"],
    ["regon", "new_regon"],
  ],
};

describe("RateItemsField", () => {
  it("starts with one row and adds a second rate", async () => {
    const onValue = vi.fn();
    render(wrap(<RateHarness onValue={onValue} />));
    expect(screen.getAllByLabelText(/Stawka netto/)).toHaveLength(1);
    // Jedyna pozycja nie da się usunąć — aneks stawki ma co najmniej jedną.
    expect(screen.getByRole("button", { name: "Usuń pozycję stawki 1" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Stawka netto/), "135");
    await userEvent.click(screen.getByRole("button", { name: /Dodaj stawkę/ }));
    expect(screen.getAllByLabelText(/Stawka netto/)).toHaveLength(2);
    const last = onValue.mock.calls.at(-1)?.[0] as RateItemValue[];
    expect(last[0].rate).toBe("135");
    expect(last).toHaveLength(2);
  });
});

describe("RegistryLookupButton", () => {
  it("fills company data from the registry", async () => {
    companyLookup.mockResolvedValueOnce({
      name: "Anna Testowa IT",
      address: "ul. Firmowa 2, Warszawa",
      regon: "012345678",
    });
    const onFill = vi.fn();
    render(<RegistryLookupButton field={NIP_FIELD} nip="527-010-33-91" onFill={onFill} />);
    await userEvent.click(screen.getByRole("button", { name: /Pobierz z CEIDG/ }));
    expect(companyLookup).toHaveBeenCalledWith({ nip: "5270103391" });
    expect(onFill).toHaveBeenCalledWith({
      new_legal_name: "Anna Testowa IT",
      new_business_address: "ul. Firmowa 2, Warszawa",
      new_regon: "012345678",
    });
    expect(await screen.findByText(/Uzupełniono z rejestru/)).toBeInTheDocument();
  });

  it("is disabled until the NIP has 10 digits", () => {
    render(<RegistryLookupButton field={NIP_FIELD} nip="123" onFill={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Pobierz z CEIDG/ })).toBeDisabled();
    expect(screen.getByText("Wpisz 10 cyfr NIP.")).toBeInTheDocument();
  });

  it("says why the registry did not answer", async () => {
    companyLookup.mockRejectedValueOnce({
      response: { status: 404, data: { detail: "Nie znaleziono firmy w rejestrze (sprawdź NIP / KRS)." } },
    });
    render(<RegistryLookupButton field={NIP_FIELD} nip="5270103391" onFill={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /Pobierz z CEIDG/ }));
    expect(await screen.findByText(/Nie znaleziono firmy w rejestrze/)).toBeInTheDocument();
  });
});
