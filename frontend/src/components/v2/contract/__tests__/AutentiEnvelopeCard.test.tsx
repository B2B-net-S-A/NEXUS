import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  withdraw: vi.fn(),
  remind: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  autentiApi: { list: mocks.list, withdraw: mocks.withdraw, remind: mocks.remind },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.success, showError: mocks.error, showToast: vi.fn() }),
}));
vi.mock("../AutentiSendDialog", () => ({
  AutentiSendDialog: ({ open, candidateName }: { open: boolean; candidateName: string }) =>
    open ? <div data-testid="send-dialog">Wysyłka do: {candidateName}</div> : null,
}));

import { AutentiEnvelopeCard } from "../AutentiEnvelopeCard";
import type { DocumentSignature } from "@/lib/api";

function signature(overrides: Partial<DocumentSignature>): DocumentSignature {
  return {
    id: 1,
    contract_id: 11,
    contract_document_id: 5,
    autenti_process_id: "proc-1",
    autenti_signature_type: "SIMPLE" as DocumentSignature["autenti_signature_type"],
    status: "sent",
    sent_at: "2026-11-03T09:00:00Z",
    completed_at: null,
    expires_at: null,
    sender_user_id: 2,
    signer_email: "anna.przykladowa@example.com",
    signer_first_name: "Anna",
    signer_last_name: "Przykładowa",
    signer_phone: null,
    signed_document_id: null,
    signed_document_url: null,
    last_error: null,
    retry_count: 0,
    created_at: "2026-11-03T08:59:00Z",
    updated_at: "2026-11-03T09:00:00Z",
    ...overrides,
  };
}

function httpError(status: number, detail = "błąd") {
  return { isAxiosError: true, response: { status, data: { detail } } };
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AutentiEnvelopeCard contractId={11} candidateName="Anna Przykładowa" candidatePhone={null} />
    </QueryClientProvider>,
  );
}

function rowOf(name: string) {
  return screen.getByText(name).closest("div.rounded-md") as HTMLElement;
}

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset();
});

describe("AutentiEnvelopeCard — stan koperty", () => {
  it.each([404, 503])("wyłączone Autenti (%i) chowa całą kartę", async (status) => {
    mocks.list.mockRejectedValue(httpError(status));
    const { container } = renderCard();
    await waitFor(() => expect(mocks.list).toHaveBeenCalledWith(11));
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("bez wysyłek pokazuje zachętę, a przycisk wysyłki otwiera okno dla kandydata", async () => {
    mocks.list.mockResolvedValue({ data: [] });
    const user = userEvent.setup();
    renderCard();
    expect(await screen.findByText(/Brak wysyłek/)).toBeInTheDocument();
    const send = screen.getByRole("button", { name: /Wyślij do podpisu/ });
    expect(send).toBeEnabled();
    await user.click(send);
    expect(screen.getByTestId("send-dialog")).toHaveTextContent("Wysyłka do: Anna Przykładowa");
  });

  it.todo(
    "awaria listy podpisów (np. 500) pokazuje błąd zamiast „Brak wysyłek” i nie odblokowuje nowej wysyłki — dziś AutentiEnvelopeCard.tsx:300 pokazuje pusty stan przy każdym błędzie innym niż 404/503",
  );

  it("aktywna koperta blokuje drugą wysyłkę i ma „Przypomnij” oraz „Wycofaj”", async () => {
    mocks.list.mockResolvedValue({ data: [signature({ id: 7, status: "in_progress" })] });
    renderCard();
    const row = await waitFor(() => rowOf("Anna Przykładowa"));
    expect(within(row).getByText("W trakcie podpisywania")).toBeInTheDocument();
    expect(within(row).getByText("(anna.przykladowa@example.com)")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: /Przypomnij/ })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: /Wycofaj/ })).toBeInTheDocument();
    const send = screen.getByRole("button", { name: /Wyślij do podpisu/ });
    expect(send).toBeDisabled();
    expect(send).toHaveAttribute("title", "Aktywna wysyłka — wycofaj lub poczekaj na status końcowy.");
  });

  it("„sending” też blokuje wysyłkę, ale nie ma jeszcze akcji na kopercie", async () => {
    mocks.list.mockResolvedValue({ data: [signature({ status: "sending" })] });
    renderCard();
    expect(await screen.findByText("Wysyłanie…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Wyślij do podpisu/ })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Przypomnij/ })).not.toBeInTheDocument();
  });

  it("podpisana: link do Autenti, daty; brak daty wygaśnięcia to „—”, a brak sent_at bierze created_at", async () => {
    mocks.list.mockResolvedValue({
      data: [
        signature({
          status: "completed",
          sent_at: null,
          completed_at: "2026-11-04T12:00:00Z",
          expires_at: null,
          signed_document_url: "https://example.com/podpisany",
        }),
      ],
    });
    renderCard();
    expect(await screen.findByText("Podpisano", { selector: "span" })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Otwórz w Autenti →" });
    expect(link).toHaveAttribute("href", "https://example.com/podpisany");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    const sent = screen.getByText("Wysłano:").parentElement!;
    expect(sent.textContent).not.toContain("—");
    expect(sent.textContent).toMatch(/2026/);
    expect(screen.getByText("Wygasa:").parentElement).toHaveTextContent("Wygasa: —");
    expect(screen.getByText("Podpisano:").parentElement!.textContent).toMatch(/2026/);
    expect(screen.queryByRole("button", { name: /Przypomnij|Wycofaj|Wyślij ponownie/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Wyślij do podpisu/ })).toBeEnabled();
  });

  it("link nie pojawia się, dopóki koperta nie jest podpisana", async () => {
    mocks.list.mockResolvedValue({ data: [signature({ status: "rejected", signed_document_url: "https://example.com/x" })] });
    renderCard();
    expect(await screen.findByText("Odrzucono")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("błąd wysyłki: komunikat z Autenti i „Wyślij ponownie” otwiera okno", async () => {
    mocks.list.mockResolvedValue({ data: [signature({ status: "failed", last_error: "Niepoprawny numer telefonu" })] });
    const user = userEvent.setup();
    renderCard();
    expect(await screen.findByText("Błąd wysyłki")).toBeInTheDocument();
    expect(screen.getByText("Niepoprawny numer telefonu")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Wyślij ponownie/ }));
    expect(screen.getByTestId("send-dialog")).toBeInTheDocument();
  });

  it("last_error przy kopercie, która nie jest w błędzie, się nie pokazuje", async () => {
    mocks.list.mockResolvedValue({ data: [signature({ status: "expired", last_error: "stary błąd" })] });
    renderCard();
    expect(await screen.findByText("Wygasło")).toBeInTheDocument();
    expect(screen.queryByText("stary błąd")).not.toBeInTheDocument();
  });
});

describe("AutentiEnvelopeCard — akcje", () => {
  it("„Przypomnij” woła remind dla tej koperty i odświeża listę", async () => {
    mocks.list.mockResolvedValue({ data: [signature({ id: 7, status: "sent" })] });
    mocks.remind.mockResolvedValue({ data: signature({ id: 7 }) });
    const user = userEvent.setup();
    renderCard();
    await user.click(await screen.findByRole("button", { name: /Przypomnij/ }));
    await waitFor(() => expect(mocks.remind).toHaveBeenCalledWith(7));
    expect(mocks.success).toHaveBeenCalledWith("Wysłano przypomnienie");
    await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
  });

  it("429 przy przypomnieniu mówi o limicie godzinowym, inny błąd — powód z API", async () => {
    mocks.list.mockResolvedValue({ data: [signature({ id: 7, status: "sent" })] });
    mocks.remind
      .mockRejectedValueOnce(httpError(429))
      .mockRejectedValueOnce(httpError(502, "Autenti nie odpowiada."));
    const user = userEvent.setup();
    renderCard();
    await user.click(await screen.findByRole("button", { name: /Przypomnij/ }));
    await waitFor(() =>
      expect(mocks.error).toHaveBeenCalledWith("Przypomnienie zostało już wysłane w ciągu ostatniej godziny."),
    );
    await user.click(screen.getByRole("button", { name: /Przypomnij/ }));
    await waitFor(() => expect(mocks.error).toHaveBeenLastCalledWith("Nie udało się przypomnieć: Autenti nie odpowiada."));
  });

  it("„Wycofaj” woła withdraw; błąd idzie komunikatem", async () => {
    mocks.list.mockResolvedValue({ data: [signature({ id: 8, status: "in_progress" })] });
    mocks.withdraw
      .mockRejectedValueOnce(httpError(409, "Koperta jest już podpisana."))
      .mockResolvedValueOnce({ data: signature({ id: 8, status: "withdrawn" }) });
    const user = userEvent.setup();
    renderCard();
    await user.click(await screen.findByRole("button", { name: /Wycofaj/ }));
    await waitFor(() => expect(mocks.error).toHaveBeenCalledWith("Nie udało się wycofać: Koperta jest już podpisana."));
    await user.click(screen.getByRole("button", { name: /Wycofaj/ }));
    await waitFor(() => expect(mocks.success).toHaveBeenCalledWith("Wycofano wysyłkę"));
    expect(mocks.withdraw).toHaveBeenCalledWith(8);
  });
});
