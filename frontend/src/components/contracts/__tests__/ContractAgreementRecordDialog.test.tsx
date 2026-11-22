import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  recordAgreementTermination: vi.fn(),
  uploadDocument: vi.fn(),
  openContractDocument: vi.fn(),
}));

vi.mock("@/lib/contract-documents", () => ({
  openContractDocument: (...args: unknown[]) => mocks.openContractDocument(...args),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  contractsApi: {
    recordAgreementTermination: (...args: unknown[]) =>
      mocks.recordAgreementTermination(...args),
    uploadDocument: (...args: unknown[]) => mocks.uploadDocument(...args),
  },
}));

vi.mock("@/components/ds/AppModal", () => ({
  AppModal: ({
    open,
    title,
    footer,
    children,
  }: {
    open: boolean;
    title: string;
    footer?: React.ReactNode;
    children: React.ReactNode;
  }) =>
    open ? (
      <section aria-label={title}>
        <h1>{title}</h1>
        {children}
        {footer}
      </section>
    ) : null,
}));

import { ContractAgreementRecordDialog } from "@/components/contracts/ContractAgreementRecordDialog";

const NOTICE_DOC = {
  id: 77,
  doc_type: "termination_notice" as const,
  filename: "Wypowiedzenie Kowalski.pdf",
  content_type: "application/pdf",
  source: "sharepoint_import",
  created_at: "2026-09-29T10:15:00Z",
};

function renderDialog(existingDocument: typeof NOTICE_DOC | null = null) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={qc}>
      <ContractAgreementRecordDialog
        contractId={318}
        candidateName="Konsultant Testowy"
        projectEnd="2026-09-30"
        existingDocument={existingDocument}
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return { onClose };
}

const save = () => screen.getByRole("button", { name: "Zapisz rozwiązanie umowy" });
const dateInput = (label: RegExp) => screen.getByLabelText(label) as HTMLInputElement;

beforeEach(() => {
  mocks.recordAgreementTermination.mockReset().mockResolvedValue({ data: {} });
  mocks.uploadDocument.mockReset().mockResolvedValue({ data: {} });
  mocks.openContractDocument.mockReset().mockResolvedValue(undefined);
});

describe("ContractAgreementRecordDialog — umowa rozwiązana poza NEXUSEM", () => {
  it("startuje od porozumienia i ostatniego dnia = koniec projektu, zapis czeka na stronę i datę", () => {
    renderDialog();
    expect(screen.getByLabelText("Porozumienie stron")).toBeChecked();
    expect(dateInput(/Ostatni dzień umowy/).value).toBe("2026-09-30");
    expect(save()).toBeDisabled();
  });

  it("zapisuje komplet danych i skan jako porozumienie", async () => {
    const { onClose } = renderDialog();
    await userEvent.click(screen.getByLabelText("Konsultant"));
    fireEvent.change(dateInput(/Data zawarcia porozumienia/), {
      target: { value: "2026-09-15" },
    });
    const file = new File(["%PDF"], "porozumienie.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText(/Skan porozumienia/), file);
    await userEvent.click(save());

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(mocks.recordAgreementTermination).toHaveBeenCalledWith(318, {
      mode: "mutual_agreement",
      party: "consultant",
      signed_on: "2026-09-15",
      last_day: "2026-09-30",
    });
    const body = mocks.uploadDocument.mock.calls[0][1] as FormData;
    expect(body.get("doc_type")).toBe("termination_agreement");
  });

  it("blokuje ostatni dzień przed datą wypowiedzenia", async () => {
    renderDialog();
    await userEvent.click(screen.getByLabelText("Wypowiedzenie"));
    await userEvent.click(screen.getByLabelText("b2bnetwork"));
    fireEvent.change(dateInput(/Data złożenia wypowiedzenia/), {
      target: { value: "2026-10-05" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "nie może być wcześniejszy niż data złożenia wypowiedzenia",
    );
    expect(save()).toBeDisabled();
  });

  it("odmowa serwera zostaje w oknie, bez wysyłki skanu", async () => {
    mocks.recordAgreementTermination.mockRejectedValue({
      isAxiosError: true,
      response: { status: 409, data: { detail: "Najpierw zakończ współpracę." } },
    });
    const { onClose } = renderDialog();
    await userEvent.click(screen.getByLabelText("Konsultant"));
    fireEvent.change(dateInput(/Data zawarcia porozumienia/), {
      target: { value: "2026-09-15" },
    });
    await userEvent.click(save());
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(mocks.uploadDocument).not.toHaveBeenCalled();
  });

  it("skan, który już jest w Dokumentach kontraktu, nie jest błędem", async () => {
    mocks.uploadDocument.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 409,
        data: {
          detail: {
            code: "document_duplicate",
            message: "Ten plik jest już w Dokumentach kontraktu (dodany 19.11.2026).",
          },
        },
      },
    });
    const { onClose } = renderDialog();
    await userEvent.click(screen.getByLabelText("Konsultant"));
    fireEvent.change(dateInput(/Data zawarcia porozumienia/), {
      target: { value: "2026-09-15" },
    });
    await userEvent.upload(
      screen.getByLabelText(/Skan porozumienia/),
      new File(["%PDF"], "porozumienie.pdf", { type: "application/pdf" }),
    );
    await userEvent.click(save());
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(screen.queryByText(/Rozwiązanie umowy jest zapisane/)).toBeNull();
  });

  it("padnięty skan mówi, że rozwiązanie jest zapisane", async () => {
    mocks.uploadDocument.mockRejectedValue(new Error("upload"));
    const { onClose } = renderDialog();
    await userEvent.click(screen.getByLabelText("Konsultant"));
    fireEvent.change(dateInput(/Data zawarcia porozumienia/), {
      target: { value: "2026-09-15" },
    });
    await userEvent.upload(
      screen.getByLabelText(/Skan porozumienia/),
      new File(["x"], "skan.pdf", { type: "application/pdf" }),
    );
    await userEvent.click(save());
    expect(await screen.findByText(/Rozwiązanie umowy jest zapisane/)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  describe("wypowiedzenie już w Dokumentach (kontrakt #605, 22.11.2026)", () => {
    it("tryb z typu dokumentu, plik wskazany zamiast pola skanu", async () => {
      renderDialog(NOTICE_DOC);
      expect(screen.getByLabelText("Wypowiedzenie")).toBeChecked();
      const box = screen.getByTestId("agreement-record-existing-document");
      expect(box).toHaveTextContent("W Dokumentach jest już wypowiedzenie");
      expect(box).toHaveTextContent("„Wypowiedzenie Kowalski.pdf”, dodane 29.09.2026 z SharePointa");
      expect(screen.queryByLabelText(/Skan porozumienia/)).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole("button", { name: "Otwórz dokument" }));
      expect(mocks.openContractDocument).toHaveBeenCalledWith(318, NOTICE_DOC);

      await userEvent.click(screen.getByRole("button", { name: "Dodaj inny skan" }));
      expect(screen.getByLabelText(/Skan porozumienia/)).toBeInTheDocument();
    });

    it("porozumienie w Dokumentach zaznacza porozumienie stron", () => {
      renderDialog({ ...NOTICE_DOC, doc_type: "termination_agreement" } as unknown as typeof NOTICE_DOC);
      expect(screen.getByLabelText("Porozumienie stron")).toBeChecked();
    });

    it("zapis wysyła dane wpisane przez człowieka i nie wgrywa pliku drugi raz", async () => {
      const { onClose } = renderDialog(NOTICE_DOC);
      await userEvent.click(screen.getByLabelText("Konsultant"));
      fireEvent.change(dateInput(/Data złożenia wypowiedzenia/), {
        target: { value: "2026-08-29" },
      });
      expect(save()).toBeEnabled();
      await userEvent.click(save());
      await waitFor(() => expect(onClose).toHaveBeenCalled());
      expect(mocks.recordAgreementTermination).toHaveBeenCalledWith(318, {
        mode: "notice",
        party: "consultant",
        signed_on: "2026-08-29",
        last_day: "2026-09-30",
      });
      expect(mocks.uploadDocument).not.toHaveBeenCalled();
    });

    it("dokument nie wypełnia daty złożenia — zapis czeka na człowieka", async () => {
      renderDialog(NOTICE_DOC);
      await userEvent.click(screen.getByLabelText("Konsultant"));
      expect(dateInput(/Data złożenia wypowiedzenia/).value).toBe("");
      expect(save()).toBeDisabled();
    });

    it("błąd otwarcia pliku pokazuje komunikat", async () => {
      mocks.openContractDocument.mockRejectedValue(new Error("HTTP 404"));
      renderDialog(NOTICE_DOC);
      await userEvent.click(screen.getByRole("button", { name: "Otwórz dokument" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się otworzyć dokumentu.");
    });
  });
});
