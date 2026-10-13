/**
 * Zakładka „Aneksy” kontraktu jako tabela (13.10.2026): aneks z Generatora
 * aneksów widać od wygenerowania („czeka na podpis”), po podpisie wiadomo,
 * skąd jest i jaki ma plik, a skan da się dołączyć z kontraktu.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  canViewFinance: vi.fn(),
  openDocument: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  },
  CONTRACT_FIELD_LABELS: { rate_candidate: "Stawka kandydata" },
  CONTRACT_TERMINATION_REASONS: [],
}));

vi.mock("@/lib/contract-documents", () => ({
  openContractDocument: (...a: unknown[]) => mocks.openDocument(...a),
}));

vi.mock("@/store/auth", async () => {
  const actual =
    await vi.importActual<typeof import("@/store/auth")>("@/store/auth");
  const state = { user: { id: 1, role: "admin", roles: ["admin"] } };
  return {
    ...actual,
    useAuthStore: (selector: (s: typeof state) => unknown) => selector(state),
    canManageCandidateFinance: () => true,
    canViewClientFinance: () => mocks.canViewFinance(),
  };
});

import { ContractAmendmentsTab } from "@/components/ContractAmendmentsTab";

const WAITING = {
  document_id: 21,
  document_type: "annex_rate_change",
  type_label: "Aneks — zmiana stawki",
  state: "waiting",
  effective_date: "2026-11-01",
  change: {
    kind: "rate",
    hidden: false,
    currency: "PLN",
    items: [{ rate: 150, from: null, to: null }],
    before: [{ rate: 140, from: null, to: null }],
  },
  cancelled_reason: null,
  created_at: "2026-10-10T09:40:00Z",
  created_by_name: "Kamil Dudek",
};

const SIGNED = {
  id: 7,
  contract_id: 5,
  amendment_type: "start_date_change",
  old_values: { start_date: "2026-07-01" },
  new_values: { start_date: "2026-07-06" },
  effective_date: "2026-07-06",
  reason: "Aneks — zmiana daty startu z dnia 28.06.2026 (dokument #3)",
  document_id: 90,
  created_by: 2,
  created_by_email: "joanna@example.com",
  created_by_name: "Joanna Wilk",
  created_at: "2026-06-28T10:00:00Z",
  source: "generator",
  b2b_document_id: 3,
  state: "in_force",
  document: { id: 90, filename: "Aneks start.docx", is_signed_scan: false },
};

const MANUAL = {
  ...SIGNED,
  id: 8,
  amendment_type: "scope_change",
  old_values: { project_name: "Migracja" },
  new_values: { project_name: "Hurtownia danych" },
  effective_date: "2026-08-01",
  reason: "Zmiana projektu",
  document_id: null,
  source: "manual",
  b2b_document_id: null,
  document: null,
};

/** Odpowiedzi obu tras zakładki; `undefined` = awaria tej trasy. */
function serve(amendments: unknown[] | undefined, annexDocuments: unknown[] | undefined) {
  mocks.get.mockImplementation((url: string) => {
    const data = url.endsWith("/annex-documents") ? annexDocuments : amendments;
    return data === undefined
      ? Promise.reject(Object.assign(new Error("HTTP 500"), { response: { status: 500, data: {} } }))
      : Promise.resolve({ data });
  });
}

function renderTab(props: Partial<React.ComponentProps<typeof ContractAmendmentsTab>> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <ContractAmendmentsTab
        contractId={5}
        clientId={2}
        personName="Piotr Zając"
        {...props}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  Object.values(mocks).forEach((m) => m.mockReset());
  mocks.canViewFinance.mockReturnValue(true);
});

describe("Zakładka Aneksy kontraktu", () => {
  it("aneks czekający na podpis jest wierszem i komunikatem z tym, co zmieni", async () => {
    serve([SIGNED, MANUAL], [WAITING]);
    renderTab();

    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent("Aneks „Zmiana stawki” czeka na podpis");
    expect(notice).toHaveTextContent(
      "Po oznaczeniu jako podpisany stawka kosztowa zmieni się na 150,00 zł/h od 01.11.2026.",
    );
    expect(
      within(notice).getByRole("link", { name: "Otwórz w rejestrze aneksów" }),
    ).toHaveAttribute("href", "/contracts/b2b-generator?tab=annexes&q=Piotr+Zaj%C4%85c");

    const rows = screen.getAllByRole("row");
    // Nagłówek, czekający aneks na górze, potem zmiany zapisane w kontrakcie.
    expect(rows).toHaveLength(4);
    expect(within(rows[1]).getByText("Czeka na podpis")).toBeInTheDocument();
    expect(within(rows[1]).getByText("140,00")).toHaveClass("line-through");
    expect(within(rows[1]).getByText("Generator aneksów")).toBeInTheDocument();
    expect(within(rows[1]).getByText("po podpisie")).toBeInTheDocument();

    expect(within(rows[2]).getByText("Zmiana daty startu")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Obowiązuje")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Generator aneksów")).toBeInTheDocument();
    expect(within(rows[2]).getByText("wygenerowany, bez podpisów")).toBeInTheDocument();
    expect(within(rows[2]).getByText("Joanna Wilk")).toBeInTheDocument();

    expect(within(rows[3]).getByText("Zmiana zakresu")).toBeInTheDocument();
    expect(within(rows[3]).getByText("Ręcznie")).toBeInTheDocument();
    expect(within(rows[3]).getByText("brak")).toBeInTheDocument();
    // Skan dołącza się tylko do aneksu z generatora.
    expect(within(rows[3]).queryByRole("button", { name: "Dołącz skan" })).toBeNull();
  });

  it("„Brak aneksów” dopiero, gdy oba odczyty są puste; sam czekający aneks to nie pustka", async () => {
    serve([], [WAITING]);
    renderTab({ readOnly: true });
    expect(await screen.findByText("Czeka na podpis")).toBeInTheDocument();
    expect(screen.queryByText(/Brak aneksów/)).not.toBeInTheDocument();
  });

  it("awaria listy czekających aneksów nie chowa zmian kontraktu i nie udaje pustki", async () => {
    serve([MANUAL], undefined);
    renderTab();
    expect(await screen.findByText("Zmiana zakresu")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Nie udało się wczytać aneksów czekających na podpis",
    );

    // Pusta historia + awaria drugiej trasy to nadal nie „Brak aneksów”.
    serve([], undefined);
    renderTab({ contractId: 6 });
    await waitFor(() => expect(screen.getAllByRole("alert").length).toBeGreaterThan(1));
    expect(screen.queryByText(/Brak aneksów/)).not.toBeInTheDocument();
  });

  it("bez wglądu w stawki aneks stawki nie pokazuje się w kontrakcie", async () => {
    mocks.canViewFinance.mockReturnValue(false);
    serve([MANUAL], [WAITING]);
    renderTab();
    expect(await screen.findByText("Zmiana zakresu")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText("Czeka na podpis")).not.toBeInTheDocument();
  });

  it("„Dołącz skan” wysyła plik do aneksu z generatora, a skan zastępuje dopisek", async () => {
    serve([SIGNED], []);
    mocks.post.mockResolvedValue({ data: {} });
    renderTab();

    await screen.findByRole("button", { name: "Dołącz skan" });
    const file = new File(["%PDF-1.4"], "aneks.pdf", { type: "application/pdf" });
    fireEvent.click(screen.getByRole("button", { name: "Dołącz skan" }));
    fireEvent.change(screen.getByLabelText("Skan podpisanego aneksu"), {
      target: { files: [file] },
    });

    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const [url, body, config] = mocks.post.mock.calls[0];
    expect(url).toBe("/api/contracts/5/amendments/7/document");
    expect((body as FormData).get("file")).toBe(file);
    expect(config).toEqual({ headers: { "Content-Type": "multipart/form-data" } });

    // Plik aneksu otwiera się z Dokumentów kontraktu.
    fireEvent.click(screen.getByRole("button", { name: "Aneks start.docx" }));
    expect(mocks.openDocument).toHaveBeenCalledWith(5, SIGNED.document);
  });

  it("aneks ze skanem nie prosi o skan drugi raz, a tylko-odczyt nie ma przycisku", async () => {
    serve(
      [{ ...SIGNED, document: { id: 91, filename: "Aneks podpisany.pdf", is_signed_scan: true } }],
      [],
    );
    renderTab();
    expect(await screen.findByText("skan podpisany")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dołącz skan" })).toBeNull();
  });

  it("formularz „Zmień stawkę” ostrzega, gdy aneks stawki czeka na podpis", async () => {
    serve([], [WAITING]);
    renderTab();
    fireEvent.click(await screen.findByRole("button", { name: /Zmień stawkę/ }));
    expect(
      screen.getByText(/Aneks zmiany stawki z Generatora aneksów czeka na podpis/),
    ).toBeInTheDocument();
  });
});
