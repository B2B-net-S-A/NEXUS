/**
 * Menu „Nowy dokument” w wierszu rejestru (26.10.2026): umowa zlecenia
 * dostaje tylko dokumenty zlecenia, umowa B2B — tylko B2B.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/url-selection", () => ({
  useUrlWriter: () => ({ pushUrl: vi.fn(), replaceUrl: vi.fn() }),
}));

vi.mock("@/lib/api/b2bDocuments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/b2bDocuments")>();
  const type = (key: string, label: string, family: string, parent: string) => ({
    key,
    label,
    family,
    parent,
    languages: ["pl"],
    fields: [],
  });
  return {
    ...actual,
    b2bDocumentsApi: {
      ...actual.b2bDocumentsApi,
      types: async () => ({
        types: [
          type("annex_rate_change", "Aneks — zmiana stawki", "annex", "b2b"),
          type("annex_mandate", "Aneks do umowy zlecenie", "annex", "mandate"),
          type(
            "termination_agreement_mandate",
            "Porozumienie o rozwiązaniu umowy zlecenie",
            "termination",
            "mandate",
          ),
          type("preliminary_cez", "Umowa przedwstępna", "preliminary", "none"),
        ],
        mandate_forms: [],
      }),
    },
  };
});

import { RegisterNewDocumentMenu } from "@/components/v2/b2b-generator/documents/RegisterNewDocumentMenu";

async function openMenu(contractKind: string | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <RegisterNewDocumentMenu
        row={{
          id: 1,
          contract_number: "Zlecenie z dnia 26.10.2026",
          partner_name: "Anna Testowa",
          contract_kind: contractKind,
        }}
      />
    </QueryClientProvider>,
  );
  await userEvent.setup().click(screen.getByRole("button", { name: /Nowy dokument/ }));
  await screen.findByText("Zarejestruj wypowiedzenie Partnera");
}

describe("RegisterNewDocumentMenu", () => {
  it("umowa zlecenia: tylko aneks i porozumienie zlecenia", async () => {
    await openMenu("mandate");
    expect(await screen.findByText("Aneks do umowy zlecenie")).toBeInTheDocument();
    expect(
      screen.getByText("Porozumienie o rozwiązaniu umowy zlecenie"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Aneks — zmiana stawki")).not.toBeInTheDocument();
    expect(screen.queryByText("Umowa przedwstępna")).not.toBeInTheDocument();
  });

  it("umowa B2B: bez dokumentów zlecenia", async () => {
    await openMenu(null);
    expect(await screen.findByText("Aneks — zmiana stawki")).toBeInTheDocument();
    expect(screen.queryByText("Aneks do umowy zlecenie")).not.toBeInTheDocument();
  });
});
