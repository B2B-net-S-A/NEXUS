/**
 * Dane firm z umów (E5a, 0755): propozycja z cytatem obok profilu, „Zastosuj”
 * z poprawką, „Sprawdź w rejestrze” z „Weź z rejestru”, „Odrzuć” i awaria,
 * która nie wygląda jak pusta lista. Dane zmyślone.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api", () => {
  const api = {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  };
  return { api, default: api };
});
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: mocks.toastError, showSuccess: vi.fn() }),
}));

import type { PartnerRead } from "@/lib/api/contractPartnerReads";
import { PartnerReadsList } from "../PartnerReadsList";

const NAMES = [
  "gender",
  "partner_name",
  "partner_legal_name",
  "partner_entity_type",
  "partner_nip",
  "partner_regon",
  "partner_business_address",
  "partner_correspondence_address",
  "partner_email",
  "partner_phone",
  "partner_krs",
  "partner_seat",
  "partner_registry_court",
  "partner_share_capital",
  "partner_representative_name",
  "partner_representative_function",
  "partner_representation",
] as const;

const COLUMNS: Record<string, string> = {
  partner_legal_name: "legal_name",
  partner_nip: "nip",
  partner_regon: "regon",
  partner_business_address: "business_address",
  partner_email: "email",
  partner_phone: "phone",
};

const VALUES: Record<string, [string | null, string | null, string | null]> = {
  // pole: [z umowy, cytat, w profilu]
  gender: ["k", "z Panią Anną Testową", null],
  partner_legal_name: [
    "Testowa Consulting Anna Testowa",
    "pod firmą Testowa Consulting Anna Testowa",
    "Stara Firma",
  ],
  partner_nip: ["7770001110", "NIP 7770001110", null],
  partner_business_address: ["ul. Przykładowa 1, 00-001 Testowo", null, null],
};

function read(over: Partial<PartnerRead> = {}): PartnerRead {
  return {
    id: 7,
    contract_id: 41,
    document_id: 91,
    filename: "Umowa 7-2026 podpisana.pdf",
    status: "read",
    mode: "text",
    read_at: "2026-11-22T09:00:00Z",
    document_kind: "contract",
    agreement_number: "7/2026",
    document_date: "2026-03-01",
    contract_variant: "jdg",
    client_name: "Klient Testowy",
    contract_status: "active",
    candidate_id: 501,
    candidate_name: "Anna Testowa",
    fields: NAMES.map((name) => ({
      name,
      value: VALUES[name]?.[0] ?? null,
      quote: VALUES[name]?.[1] ?? null,
      quote_found: VALUES[name]?.[1] ? true : null,
      column: COLUMNS[name] ?? null,
      current: VALUES[name]?.[2] ?? null,
    })),
    issues: [],
    decision: null,
    decided_at: null,
    confirmed: null,
    candidate_changes: null,
    verification: null,
    verified_at: null,
    ...over,
  };
}

const COUNTS = {
  open: 1,
  failed: 0,
  applied: 0,
  dismissed: 0,
  to_read: 12,
  without_file: 3,
  eligible: 16,
};

function listResponse(items: PartnerRead[]) {
  return {
    data: { state: "open", items, total: items.length, counts: COUNTS },
  };
}

function renderList() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <PartnerReadsList />
    </QueryClientProvider>,
  );
}

describe("PartnerReadsList", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.post.mockReset();
    mocks.toastError.mockReset();
  });

  it("pokazuje wartość z umowy, cytat i wartość w profilu, a „Zastosuj” wysyła potwierdzenie", async () => {
    mocks.get.mockResolvedValue(listResponse([read()]));
    mocks.post.mockResolvedValue({ data: read({ decision: "applied" }) });
    renderList();

    expect(
      await screen.findByText("Testowa Consulting Anna Testowa"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("pod firmą Testowa Consulting Anna Testowa"),
    ).toBeInTheDocument();
    expect(screen.getByText("Stara Firma")).toBeInTheDocument();
    expect(screen.getByText("Pani")).toBeInTheDocument();
    expect(screen.getByText(/czeka na odczyt: 12/)).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/api/contract-partner-reads", {
      params: { state: "open", offset: 0, limit: 20 },
    });

    fireEvent.click(screen.getByRole("button", { name: "Zastosuj" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/contract-partner-reads/7/apply",
        { overwrite: false, values: {} },
      ),
    );
  });

  it("poprawka człowieka idzie w „values”", async () => {
    mocks.get.mockResolvedValue(listResponse([read()]));
    mocks.post.mockResolvedValue({ data: read({ decision: "applied" }) });
    renderList();

    fireEvent.click(await screen.findByRole("button", { name: "Popraw dane" }));
    fireEvent.change(screen.getByLabelText("NIP — poprawka"), {
      target: { value: "7770001129" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zastosuj" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/contract-partner-reads/7/apply",
        { overwrite: false, values: { partner_nip: "7770001129" } },
      ),
    );
  });

  it("wynik rejestru pokazuje różnicę, a „Weź z rejestru” wpisuje poprawkę", async () => {
    const verified = read({
      verification: {
        status: "verified",
        registry: "ceidg",
        checked_at: "2026-11-22T10:00:00Z",
        message: null,
        warnings: [],
        comparison: [
          {
            field: "partner_business_address",
            read: "ul. Przykładowa 1, 00-001 Testowo",
            registry: "ul. Przykładowa 2, 00-001 Testowo",
            same: false,
          },
          {
            field: "partner_nip",
            read: "7770001110",
            registry: "7770001110",
            same: true,
          },
        ],
      },
      verified_at: "2026-11-22T10:00:00Z",
    });
    mocks.get.mockResolvedValue(listResponse([verified]));
    mocks.post.mockResolvedValue({ data: verified });
    renderList();

    expect(await screen.findByText("Sprawdzono w CEIDG 22.11.2026")).toBeInTheDocument();
    expect(screen.getByText("zgodne z rejestrem")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Weź z rejestru" }));
    expect(
      screen.getByLabelText("Adres działalności / siedziby — poprawka"),
    ).toHaveValue("ul. Przykładowa 2, 00-001 Testowo");

    fireEvent.click(screen.getByRole("button", { name: /Sprawdź w rejestrze/ }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/contract-partner-reads/7/verify",
        {
          values: {
            partner_business_address: "ul. Przykładowa 2, 00-001 Testowo",
          },
        },
      ),
    );
  });

  it("„Odrzuć” wysyła odrzucenie", async () => {
    mocks.get.mockResolvedValue(listResponse([read()]));
    mocks.post.mockResolvedValue({ data: read({ decision: "dismissed" }) });
    renderList();
    fireEvent.click(await screen.findByRole("button", { name: "Odrzuć" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/contract-partner-reads/7/dismiss",
      ),
    );
  });

  it("uwagi kodu są widoczne przy polu", async () => {
    mocks.get.mockResolvedValue(
      listResponse([
        read({
          issues: [
            {
              field: "partner_regon",
              message: "numer nie ma 9 albo 14 cyfr z poprawną cyfrą kontrolną.",
            },
          ],
        }),
      ]),
    );
    renderList();
    expect(
      await screen.findByText(/REGON: numer nie ma 9 albo 14 cyfr/),
    ).toBeInTheDocument();
  });

  it("zastosowany odczyt pokazuje potwierdzone dane, poprawkę i co trafiło do profilu", async () => {
    mocks.get.mockResolvedValue(
      listResponse([
        read({
          decision: "applied",
          confirmed: {
            fields: { partner_nip: "7770001110", partner_regon: "000000129" },
            corrected: ["partner_regon"],
          },
          candidate_changes: {
            nip: { action: "written" },
            legal_name: { action: "kept" },
            email: { action: "no_value" },
          },
        }),
      ]),
    );
    renderList();
    expect(await screen.findByText("000000129")).toBeInTheDocument();
    expect(screen.getByText("(poprawione)")).toBeInTheDocument();
    expect(
      screen.getByText(
        "NIP: zapisano w profilu · firma: zostawiono wartość z profilu",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zastosuj" })).not.toBeInTheDocument();
  });

  it("awaria zapytania to komunikat, nie pusta lista", async () => {
    mocks.get.mockRejectedValue(new Error("500"));
    renderList();
    expect(
      await screen.findByText("Nie udało się pobrać danych"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Nic do potwierdzenia.")).not.toBeInTheDocument();
  });

  it("pusta lista po udanym zapytaniu mówi, że nic nie czeka", async () => {
    mocks.get.mockResolvedValue(listResponse([]));
    renderList();
    expect(await screen.findByText("Nic do potwierdzenia.")).toBeInTheDocument();
  });
});
