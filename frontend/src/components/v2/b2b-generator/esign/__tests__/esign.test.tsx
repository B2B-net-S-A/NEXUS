import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { B2BGeneratedContractRow } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  defaults: vi.fn(),
  send: vi.fn(),
  mine: vi.fn(),
  companySign: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

vi.mock("@/lib/api/b2bEsign", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/b2bEsign")>();
  return {
    ...actual,
    b2bEsignApi: {
      defaults: (...a: unknown[]) => mocks.defaults(...a),
      send: (...a: unknown[]) => mocks.send(...a),
      mine: (...a: unknown[]) => mocks.mine(...a),
      companySign: (...a: unknown[]) => mocks.companySign(...a),
      companyPdf: vi.fn(),
      withdraw: vi.fn(),
    },
  };
});

import { CompanySignaturesPanel } from "../CompanySignaturesPanel";
import { esignSteps } from "../EsignRowStatus";
import { SendForSignatureDialog } from "../SendForSignatureDialog";

function wrap(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const ROW = {
  id: 5,
  contract_number: "1610/2026",
  partner_name: "Piotr Przykładowy",
  partner_display_name: "Piotr Przykładowy",
  canonical_client_name: "Klient",
  job_title: "DevOps",
} as unknown as B2BGeneratedContractRow;

describe("SendForSignatureDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.defaults.mockResolvedValue({
      contractor_name: "Piotr Przykładowy",
      contractor_email: "piotr@example.com",
      company_signers: [{ id: 9, name: "Olaf Reprezentant" }],
      mailbox_connected: false,
    });
  });

  it("wysyła dopiero po potwierdzeniu treści, z osobą z umowy i reprezentantem z listy", async () => {
    mocks.send.mockResolvedValue({
      request: { contractor_email: "piotr@example.com" },
      sign_url: "https://nexus.example/sign/b2b/abc",
      mail_sent: false,
      mail_problem: "Twoja skrzynka Microsoft 365 nie jest połączona z NEXUSEM.",
    });
    wrap(<SendForSignatureDialog row={ROW} onClose={() => undefined} />);
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Piotr Przykładowy")).toBeInTheDocument();
    expect(within(dialog).getByText("Twoja skrzynka nie jest połączona")).toBeInTheDocument();
    const send = within(dialog).getByRole("button", { name: /Wyślij link do kontraktora/ });
    expect(send).toBeDisabled();
    await userEvent.click(within(dialog).getByLabelText(/Sprawdziłam\/em treść umowy/));
    await userEvent.click(send);
    await waitFor(() =>
      expect(mocks.send).toHaveBeenCalledWith(5, {
        contractor_email: "piotr@example.com",
        company_signer_id: 9,
        days: 14,
      }),
    );
    expect(await within(dialog).findByLabelText("Link do podpisu")).toHaveValue(
      "https://nexus.example/sign/b2b/abc",
    );
  });

  it("droga zwykła niczego nie wysyła", async () => {
    wrap(<SendForSignatureDialog row={ROW} onClose={() => undefined} />);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByLabelText(/Jak dotąd — mail/));
    expect(within(dialog).getByText("Droga zwykła")).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", { name: /Wyślij link do kontraktora/ }),
    ).not.toBeInTheDocument();
    expect(mocks.send).not.toHaveBeenCalled();
  });
});

describe("esignSteps", () => {
  const row = (esign: Partial<NonNullable<B2BGeneratedContractRow["esign"]>>) =>
    ({
      esign: {
        request_id: 1,
        status: "sent",
        contractor_signed_at: null,
        completed_at: null,
        expires_at: "2026-11-04T10:00:00Z",
        company_signer_name: "Olaf",
        ...esign,
      },
    }) as unknown as B2BGeneratedContractRow;

  it("pokazuje, na kim stoi umowa", () => {
    expect(esignSteps(row({ status: "sent" })).map((s) => s.state)).toEqual(["now", "wait"]);
    expect(
      esignSteps(
        row({ status: "contractor_signed", contractor_signed_at: "2026-10-21T10:00:00Z" }),
      ).map((s) => s.state),
    ).toEqual(["done", "now"]);
    expect(esignSteps(row({ status: "withdrawn" }))).toEqual([]);
  });
});

describe("CompanySignaturesPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("nic nie pokazuje, gdy nic nie czeka", async () => {
    mocks.mine.mockResolvedValue([]);
    const { container } = wrap(<CompanySignaturesPanel />);
    await waitFor(() => expect(mocks.mine).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("przyjmuje tylko PDF i wysyła go jako podpis firmy", async () => {
    mocks.mine.mockResolvedValue([
      {
        id: 3,
        contractor_name: "Ewa Przykładowa",
        contractor_signed_at: "2026-10-21T10:14:00Z",
      },
    ]);
    mocks.companySign.mockResolvedValue({ id: 3, status: "completed" });
    wrap(<CompanySignaturesPanel />);
    expect(await screen.findByText("Ewa Przykładowa")).toBeInTheDocument();
    const field = screen.getByLabelText("Plik z oboma podpisami");
    await userEvent.upload(field, new File(["x"], "skan.jpg"), { applyAccept: false });
    expect(screen.getByText("Wgraj podpisany plik PDF.")).toBeInTheDocument();
    const pdf = new File(["%PDF-1.7"], "umowa.pdf", { type: "application/pdf" });
    await userEvent.upload(field, pdf);
    await userEvent.click(screen.getByRole("button", { name: /Wgraj podpisaną za B2B Network/ }));
    await waitFor(() => expect(mocks.companySign).toHaveBeenCalledWith(3, pdf));
    expect(mocks.showSuccess).toHaveBeenCalledWith("Umowa podpisana przez obie strony.");
  });
});
