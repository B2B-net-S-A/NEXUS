import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  recordAgreementTermination: vi.fn(),
  uploadDocument: vi.fn(),
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

function renderDialog() {
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
});
