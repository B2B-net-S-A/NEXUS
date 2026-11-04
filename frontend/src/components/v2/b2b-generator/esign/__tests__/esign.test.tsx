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
  withdraw: vi.fn(),
  extend: vi.fn(),
  relink: vi.fn(),
  takeOver: vi.fn(),
  signedPdf: vi.fn(),
  downloadBlob: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/lib/cv-generator", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/cv-generator")>()),
  downloadBlob: (...a: unknown[]) => mocks.downloadBlob(...a),
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
      withdraw: (...a: unknown[]) => mocks.withdraw(...a),
      extend: (...a: unknown[]) => mocks.extend(...a),
      relink: (...a: unknown[]) => mocks.relink(...a),
      takeOver: (...a: unknown[]) => mocks.takeOver(...a),
      signedPdf: (...a: unknown[]) => mocks.signedPdf(...a),
    },
  };
});

import { CompanySignaturesPanel } from "../CompanySignaturesPanel";
import { EsignRowStatus, esignSteps } from "../EsignRowStatus";
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
    // 26.10.2026 (Sandra): krótkie terminy, domyślnie 3 dni.
    const term = within(dialog).getByLabelText("Termin na podpis");
    expect(
      Array.from((term as HTMLSelectElement).options).map((o) => o.textContent),
    ).toEqual(["1 dzień", "3 dni", "5 dni", "7 dni"]);
    const send = within(dialog).getByRole("button", { name: /Wyślij link do kontraktora/ });
    expect(send).toBeDisabled();
    await userEvent.click(within(dialog).getByLabelText(/Sprawdziłam\/em treść umowy/));
    await userEvent.click(send);
    await waitFor(() =>
      expect(mocks.send).toHaveBeenCalledWith(5, {
        contractor_email: "piotr@example.com",
        company_signer_id: 9,
        days: 3,
        cc_user_ids: [],
      }),
    );
    expect(await within(dialog).findByLabelText("Link do podpisu")).toHaveValue(
      "https://nexus.example/sign/b2b/abc",
    );
  });

  it("DW: prowadzący rekrutację zaznaczony, inne osoby z zespołu do wyboru (27.10.2026)", async () => {
    mocks.defaults.mockResolvedValue({
      contractor_name: "Piotr Przykładowy",
      contractor_email: "piotr@example.com",
      company_signers: [{ id: 9, name: "Olaf Reprezentant" }],
      mailbox_connected: true,
      cc_candidates: [
        { id: 21, name: "Rita Rekruterka", suggested: true },
        { id: 22, name: "Dawid Delivery", suggested: false },
      ],
    });
    mocks.send.mockResolvedValue({
      request: { contractor_email: "piotr@example.com" },
      sign_url: "https://nexus.example/sign/b2b/abc",
      mail_sent: true,
      mail_problem: null,
    });
    wrap(<SendForSignatureDialog row={ROW} onClose={() => undefined} />);
    const dialog = await screen.findByRole("dialog");
    const cc = await within(dialog).findByRole("group", { name: /Do wiadomości \(DW\)/ });
    expect(within(cc).getByRole("checkbox", { name: /Rita Rekruterka/ })).toBeChecked();
    expect(within(cc).getByRole("checkbox", { name: /Dawid Delivery/ })).not.toBeChecked();
    expect(within(cc).getByText(/Mail wychodzi z Twojej skrzynki/)).toBeInTheDocument();
    await userEvent.click(within(cc).getByRole("checkbox", { name: /Dawid Delivery/ }));
    await userEvent.click(within(dialog).getByLabelText(/Sprawdziłam\/em treść umowy/));
    await userEvent.click(within(dialog).getByRole("button", { name: /Wyślij link do kontraktora/ }));
    await waitFor(() =>
      expect(mocks.send).toHaveBeenCalledWith(5, expect.objectContaining({ cc_user_ids: [21, 22] })),
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

describe("AgreementSignatureAction przy umowie w podpisie w NEXUSIE", () => {
  it("pokazuje kroki zamiast ręcznego „Oznacz jako podpisaną”", async () => {
    const { AgreementSignatureAction } = await import("../../AgreementSignatureAction");
    const row = {
      id: 9,
      contract_number: "1610/2026",
      signature_status: "unsigned",
      contract_status: "in_progress",
      can_confirm_signed: true,
      esign: {
        request_id: 4,
        status: "sent",
        contractor_signed_at: null,
        completed_at: null,
        expires_at: "2026-11-04T10:00:00Z",
        company_signer_name: "Olaf",
      },
    } as unknown as B2BGeneratedContractRow;
    wrap(<AgreementSignatureAction row={row} jobId={20} readOnly={false} />);
    expect(screen.getByText("W NEXUSIE")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Oznacz jako podpisaną/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/NEXUS potwierdzi podpis sam/)).toBeInTheDocument();
  });
});

describe("EsignCompanyBand na pulpicie (etap 1b)", () => {
  beforeEach(() => vi.clearAllMocks());

  async function setUser(access: "view" | "none") {
    const { useAuthStore } = await import("@/store/auth");
    useAuthStore.setState({
      user: {
        id: 1,
        role: "admin",
        roles: [],
        effective_action_access: { b2b_contract_generator: access },
      },
      hydrated: true,
    } as never);
  }

  it("pokazuje umowy czekające na mój podpis z linkiem do rejestru", async () => {
    await setUser("view");
    mocks.mine.mockResolvedValue([
      {
        id: 3,
        generated_contract_id: 9,
        contract_number: "1611/2026",
        client_name: "Bank B",
        contractor_name: "Ewa Przykładowa",
        contractor_signed_at: "2026-10-21T10:14:00Z",
      },
    ]);
    const { EsignCompanyBand } = await import("@/components/v2/dashboard/EsignCompanyBand");
    wrap(<EsignCompanyBand />);
    const band = await screen.findByTestId("esign-company-band");
    expect(within(band).getByText("1611/2026 · Ewa Przykładowa")).toBeInTheDocument();
    expect(within(band).getByText(/Bank B · kontraktor podpisał/)).toBeInTheDocument();
    expect(within(band).getByRole("link", { name: "Podpisz" })).toHaveAttribute(
      "href",
      "/contracts/b2b-generator",
    );
  });

  it("bez dostępu do Generatora nawet nie pyta serwera", async () => {
    await setUser("none");
    const { EsignCompanyBand } = await import("@/components/v2/dashboard/EsignCompanyBand");
    const { container } = wrap(<EsignCompanyBand />);
    expect(container).toBeEmptyDOMElement();
    expect(mocks.mine).not.toHaveBeenCalled();
  });
});

describe("strona kontraktora — instrukcja per narzędzie (etap 1b)", () => {
  it("zakładki zmieniają instrukcję, a PAdES jest zawsze na widoku", async () => {
    const { default: B2BSignForm } = await import("@/app/sign/b2b/[token]/B2BSignForm");
    render(<B2BSignForm token="t" initialState="waiting" />);
    expect(screen.getByRole("tab", { name: "mObywatel" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("numer CAN");
    await userEvent.click(screen.getByRole("tab", { name: "SimplySign" }));
    expect(screen.getByRole("tab", { name: "SimplySign" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("SimplySign na telefonie");
    expect(screen.getByText(/zostanie odrzucony/)).toBeInTheDocument();
  });

  it("po podpisie obu stron kontraktor pobiera swoją kopię z linku (26.10.2026)", async () => {
    const { default: B2BSignForm } = await import("@/app/sign/b2b/[token]/B2BSignForm");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => new Blob(["%PDF"]),
      headers: new Headers({
        "content-disposition": 'attachment; filename="Umowa B2B 1555-2026 Kowalski Jan podpisana.pdf"',
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    const createObjectURL = vi.fn(() => "blob:kopia");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL }));
    render(<B2BSignForm token="t" initialState="completed" signedPdfUntil="25.11.2026" />);
    expect(screen.getByText("Umowa podpisana przez obie strony")).toBeInTheDocument();
    expect(screen.getByText(/Link działa do 25\.11\.2026/)).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Pobierz umowę podpisaną przez obie strony" }),
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/public\/b2b-sign\/t\/signed-pdf$/);
    vi.unstubAllGlobals();
  });

  it("po podpisie obu stron bez kopii w linku (wygasła) nie ma przycisku", async () => {
    const { default: B2BSignForm } = await import("@/app/sign/b2b/[token]/B2BSignForm");
    render(<B2BSignForm token="t" initialState="completed" signedPdfUntil={null} />);
    expect(screen.getByText("Umowa podpisana przez obie strony")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Pobierz umowę podpisaną przez obie strony" }),
    ).toBeNull();
  });

  it("bez myślników „—” w tekście dla konsultanta (Klaudia, 26.10.2026)", async () => {
    const { default: B2BSignForm } = await import("@/app/sign/b2b/[token]/B2BSignForm");
    const { signedPdfProblem } = await import("@/lib/api/b2bEsign");
    const { unmount } = render(<B2BSignForm token="t" initialState="waiting" />);
    for (const tab of ["mObywatel", "SimplySign", "Szafir / karta", "Inny"]) {
      await userEvent.click(screen.getByRole("tab", { name: tab }));
      expect(document.body.textContent).not.toContain("—");
    }
    unmount();
    for (const state of ["signed_by_you", "completed", "expired"] as const) {
      const view = render(<B2BSignForm token="t" initialState={state} />);
      expect(document.body.textContent).not.toContain("—");
      view.unmount();
    }
    const big = new File(["x"], "umowa.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: 21 * 1024 * 1024 });
    expect(signedPdfProblem(big)).not.toContain("—");
  });
});

describe("strona kontraktora po terminie (27.10.2026)", () => {
  it("mówi, kiedy minął termin, i wysyła prośbę o nowy link", async () => {
    const { default: B2BSignForm } = await import("@/app/sign/b2b/[token]/B2BSignForm");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        contract_number: "1555/2026",
        contractor_name: "Jan Przykładowy",
        status: "expired",
        expires_at: "2026-10-30T10:00:00Z",
        renewal_requested_at: "2026-10-31T09:00:00Z",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<B2BSignForm token="t" initialState="expired" expiredOn="30.10.2026" />);
    expect(screen.getByText("Termin na podpis minął 30.10.2026")).toBeInTheDocument();
    expect(screen.getByText(/Nowy link go przyjmie/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Poproś o nowy link" }));
    await waitFor(() => expect(screen.getByText("Prośba wysłana")).toBeInTheDocument());
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/public\/b2b-sign\/t\/renewal$/);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST" });
    expect(screen.queryByRole("button", { name: "Poproś o nowy link" })).toBeNull();
    vi.unstubAllGlobals();
  });

  it("prośba wysłana wcześniej: bez przycisku, z datą", async () => {
    const { default: B2BSignForm } = await import("@/app/sign/b2b/[token]/B2BSignForm");
    render(
      <B2BSignForm
        token="t"
        initialState="expired"
        expiredOn="30.10.2026"
        renewalRequestedOn="31.10.2026"
      />,
    );
    expect(screen.getByText(/dostała Twoją prośbę 31\.10\.2026/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Poproś o nowy link" })).toBeNull();
  });
});

describe("EsignRowStatus (audyt 22.10)", () => {
  beforeEach(() => vi.clearAllMocks());

  const row = (
    esign: Partial<NonNullable<B2BGeneratedContractRow["esign"]>>,
    extra: Record<string, unknown> = {},
  ) =>
    ({
      id: 9,
      contract_number: "1610/2026",
      esign: {
        request_id: 4,
        status: "sent",
        contractor_signed_at: null,
        completed_at: null,
        expires_at: "2026-11-04T10:00:00Z",
        company_signer_name: "Olaf",
        ...esign,
      },
      ...extra,
    }) as unknown as B2BGeneratedContractRow;

  it("F92: wycofanie odświeża też kartę Tablicy i listę na pulpicie", async () => {
    mocks.withdraw.mockResolvedValue({ id: 4, status: "withdrawn" });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    render(
      <QueryClientProvider client={client}>
        <EsignRowStatus row={row({}, { can_withdraw_esign: true })} />
      </QueryClientProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: /Przejdź na zwykłą drogę/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Wycofaj wysyłkę" }));
    await waitFor(() => expect(mocks.withdraw).toHaveBeenCalled());
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban"] }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["board-tasks"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["b2b-generated"] });
  });

  it("F45: podpisaną przez obie strony umowę da się pobrać", async () => {
    const blob = new Blob(["%PDF"]);
    mocks.signedPdf.mockResolvedValue({
      data: blob,
      headers: {
        "content-disposition": 'attachment; filename="Umowa B2B 1555-2026 Przykladowy Piotr podpisana.pdf"',
      },
    });
    wrap(
      <EsignRowStatus
        row={row(
          { status: "completed", completed_at: "2026-10-22T10:00:00Z" },
          { can_download_signed_esign: true },
        )}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Pobierz podpisaną umowę/ }));
    await waitFor(() => expect(mocks.signedPdf).toHaveBeenCalledWith(4));
    // Nazwa z serwera: „Umowa B2B [nr] Nazwisko Imię” (Sandra, 26.10.2026).
    expect(mocks.downloadBlob).toHaveBeenCalledWith(
      blob,
      "Umowa B2B 1555-2026 Przykladowy Piotr podpisana.pdf",
    );
  });

  const dayFromNow = (days: number) =>
    new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString();

  it("wygasły link: „Wyślij nowy link” na tym samym PDF-ie (27.10.2026)", async () => {
    mocks.relink.mockResolvedValue({
      request: { id: 4, status: "sent", contractor_email: "jan@example.com", expires_at: dayFromNow(3) },
      sign_url: "https://nexus.example/sign/b2b/nowy",
      mail_sent: false,
      mail_problem: "Twoja skrzynka Microsoft 365 nie jest połączona z NEXUSEM.",
    });
    wrap(
      <EsignRowStatus
        row={row(
          { status: "expired", expires_at: dayFromNow(-1), renewal_requested_at: dayFromNow(0) },
          { can_relink_esign: true },
        )}
      />,
    );
    expect(screen.getByText(/Link wygasł/)).toBeInTheDocument();
    expect(screen.getByText(/Kontraktor prosi o nowy link/)).toBeInTheDocument();
    expect(screen.getByText(/podpisany już plik przejdzie/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Wyślij nowy link/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /Wyślij nowy link/ }));
    await waitFor(() => expect(mocks.relink).toHaveBeenCalledWith(4, 3));
    expect(await within(dialog).findByLabelText("Nowy link do podpisu")).toHaveValue(
      "https://nexus.example/sign/b2b/nowy",
    );
  });

  it("wygasły link bez prawa albo po poprawce umowy: bez „Wyślij nowy link”", () => {
    wrap(<EsignRowStatus row={row({ status: "expired", expires_at: dayFromNow(-1) })} />);
    expect(screen.getByText(/Link wygasł/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Wyślij nowy link/ })).toBeNull();
  });

  it("termin minął, zanim pętla zamknęła wniosek: już widać „Link wygasł”", () => {
    wrap(<EsignRowStatus row={row({ status: "sent", expires_at: dayFromNow(-0.1) })} />);
    expect(screen.getByText(/Link wygasł/)).toBeInTheDocument();
    expect(screen.queryByText(/Link ważny do/)).toBeNull();
  });

  it("link działa: „Przedłuż termin” wybiera liczbę dni", async () => {
    mocks.extend.mockResolvedValue({ id: 4, status: "sent", expires_at: dayFromNow(8) });
    wrap(
      <EsignRowStatus
        row={row({ status: "sent", expires_at: dayFromNow(1) }, { can_extend_esign: true })}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Przedłuż termin/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.selectOptions(within(dialog).getByLabelText("O ile dni"), "7");
    await userEvent.click(within(dialog).getByRole("button", { name: /Przedłuż termin/ }));
    await waitFor(() => expect(mocks.extend).toHaveBeenCalledWith(4, 7));
    expect(await within(dialog).findByText(/Termin przedłużony do/)).toBeInTheDocument();
  });

  it("pokazuje, kto jest w DW wysyłki", () => {
    wrap(<EsignRowStatus row={row({ expires_at: dayFromNow(2), cc_names: ["Rita Rekruterka"] })} />);
    expect(screen.getByText("Rita Rekruterka")).toBeInTheDocument();
    expect(screen.getByText(/DW:/)).toBeInTheDocument();
  });

  it("zastępstwo: urlop obsługującego i „Przejmij obsługę” z potwierdzeniem", async () => {
    mocks.takeOver.mockResolvedValue({ id: 4, handled_by_id: 21 });
    wrap(
      <EsignRowStatus
        row={row(
          {
            expires_at: dayFromNow(2),
            handled_by_name: "Sara Sprzedawczyni",
            handler_absent_until: "2026-11-04",
            handler_substitute_name: "Rita Rekruterka",
          },
          { can_take_over_esign: true },
        )}
      />,
    );
    expect(screen.getByText(/Obsługuje:/)).toHaveTextContent("Obsługuje: Sara Sprzedawczyni");
    expect(screen.getByText(/urlop do 04\.11, zastępuje Rita Rekruterka/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Przejmij obsługę/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Przejmij obsługę" }));
    await waitFor(() => expect(mocks.takeOver).toHaveBeenCalledWith(4));
    expect(mocks.showSuccess).toHaveBeenCalled();
  });

  it("bez prawa przejęcia nie ma przycisku", () => {
    wrap(<EsignRowStatus row={row({ expires_at: dayFromNow(2), handled_by_name: "Sara" })} />);
    expect(screen.queryByRole("button", { name: /Przejmij obsługę/ })).toBeNull();
  });

  it("F45: bez prawa do pliku nie ma przycisku pobrania", () => {
    wrap(<EsignRowStatus row={row({ status: "completed" })} />);
    expect(
      screen.queryByRole("button", { name: /Pobierz podpisaną umowę/ }),
    ).not.toBeInTheDocument();
  });
});

describe("CompanySignaturesPanel przy błędzie (audyt 22.10, F87)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("awaria listy nie wygląda jak brak umów — komunikat i „Ponów”", async () => {
    mocks.mine.mockRejectedValue(new Error("500"));
    wrap(<CompanySignaturesPanel />);
    expect(
      await screen.findByText(/Nie udało się wczytać umów do podpisu za B2B Network/),
    ).toBeInTheDocument();
    mocks.mine.mockResolvedValue([]);
    await userEvent.click(screen.getByRole("button", { name: "Ponów" }));
    await waitFor(() => expect(mocks.mine).toHaveBeenCalledTimes(2));
  });
});
