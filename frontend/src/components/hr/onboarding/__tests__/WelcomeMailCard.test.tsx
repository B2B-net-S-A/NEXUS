import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WelcomeMailState } from "@/lib/api/client-onboarding";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  toast: vi.fn(),
  confirm: vi.fn(async () => true),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, put: mocks.put },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.toast }),
}));

vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.confirm, confirmDialog: null }),
}));

import { WelcomeMailCard, sendBlocker } from "../WelcomeMailCard";

// Dane fikcyjne — repo jest publiczne.
function mailState(overrides: Partial<WelcomeMailState> = {}): WelcomeMailState {
  return {
    contract_id: 42,
    enabled: true,
    mailbox_ready: true,
    transport_ready: true,
    can_toggle: false,
    is_sender: true,
    can_send: true,
    sent: null,
    draft: {
      recipient_email: "marek.przykladowy@example.com",
      recipient_name: "Marek Przykładowy",
      subject: "Twój start w Bank Przykładowy — 02.11.2026",
      body: "Cześć Marek,\n\nw poniedziałek 02.11 o 9:00 zaczynasz w Bank Przykładowy.",
    },
    issues: [],
    ...overrides,
  };
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <WelcomeMailCard contractId={42} />
    </QueryClientProvider>,
  );
}

function apiError(status: number, detail: string) {
  return Object.assign(new Error(detail), {
    isAxiosError: true,
    response: { status, data: { detail } },
  });
}

describe("sendBlocker", () => {
  it("mówi, dlaczego nie da się wysłać", () => {
    expect(sendBlocker(mailState())).toBeNull();
    expect(sendBlocker(mailState({ enabled: false }))).toMatch(/włącza ją administrator/);
    expect(sendBlocker(mailState({ enabled: false, can_toggle: true }))).toMatch(/przełącznikiem/);
    expect(sendBlocker(mailState({ mailbox_ready: false }))).toMatch(/administracja@/);
    expect(sendBlocker(mailState({ transport_ready: false }))).toMatch(/Microsoft 365/);
    expect(sendBlocker(mailState({ is_sender: false }))).toMatch(/opiekun konsultanta/);
    expect(
      sendBlocker(
        mailState({ issues: [{ code: "no_email", message: "Brak adresu.", blocking: true }] }),
      ),
    ).toBe("Brak adresu.");
  });
});

describe("WelcomeMailCard", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.post.mockReset();
    mocks.put.mockReset();
    mocks.toast.mockReset();
    mocks.confirm.mockClear();
  });

  it("wyłączona wysyłka: podgląd jest, „Wyślij” nie wychodzi", async () => {
    mocks.get.mockResolvedValue({ data: mailState({ enabled: false, can_send: false }) });
    renderCard();
    expect(await screen.findByText(/włącza ją administrator/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Podgląd" }));
    expect(await screen.findByLabelText("Treść")).toHaveValue(mailState().draft!.body);
    expect(screen.getByRole("button", { name: "Wyślij" })).toBeDisabled();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("opiekun poprawia treść, potwierdza i wysyła", async () => {
    mocks.get.mockResolvedValue({ data: mailState() });
    mocks.post.mockResolvedValue({
      data: mailState({
        sent: {
          id: 1,
          sent_at: "2026-10-30T09:00:00+00:00",
          sent_by: 3,
          sent_by_name: "Zofia Opiekuńska",
          recipient_email: "marek.przykladowy@example.com",
          subject: "Temat",
          body: "Poprawiona treść",
          delivery: "sent",
        },
        draft: null,
      }),
    });
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Podgląd i wysyłka" }));
    fireEvent.change(screen.getByLabelText("Treść"), { target: { value: "Poprawiona treść" } });
    fireEvent.click(screen.getByRole("button", { name: "Wyślij" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(mocks.confirm).toHaveBeenCalledWith(
      expect.objectContaining({ description: expect.stringContaining("marek.przykladowy@example.com") }),
    );
    expect(mocks.post.mock.calls[0]).toEqual([
      "/api/client-onboarding/contracts/42/welcome-mail",
      { subject: "Twój start w Bank Przykładowy — 02.11.2026", body: "Poprawiona treść" },
    ]);
    expect(await screen.findByText("Poprawiona treść")).toBeInTheDocument();
    expect(screen.getByText(/wysłany 30\.10/)).toBeInTheDocument();
  });

  it("anulowane potwierdzenie niczego nie wysyła", async () => {
    mocks.confirm.mockResolvedValueOnce(false);
    mocks.get.mockResolvedValue({ data: mailState() });
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Podgląd i wysyłka" }));
    fireEvent.click(screen.getByRole("button", { name: "Wyślij" }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalled());
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("odmowa serwera zostaje w oknie", async () => {
    mocks.get.mockResolvedValue({ data: mailState() });
    mocks.post.mockRejectedValue(apiError(502, "Nie udało się wysłać maila — spróbuj ponownie za chwilę."));
    renderCard();
    fireEvent.click(await screen.findByRole("button", { name: "Podgląd i wysyłka" }));
    fireEvent.click(screen.getByRole("button", { name: "Wyślij" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/spróbuj ponownie/);
  });

  it("braki pakietu widać na karcie, blokujący zatrzymuje wysyłkę", async () => {
    mocks.get.mockResolvedValue({
      data: mailState({
        can_send: false,
        issues: [
          { code: "no_email", message: "Kontrakt i profil kandydata nie mają adresu e-mail.", blocking: true },
          { code: "no_pack", message: "Klient nie ma pakietu.", blocking: false },
        ],
      }),
    });
    renderCard();
    const list = await screen.findByRole("list", { name: "Braki w mailu" });
    expect(list).toHaveTextContent("Klient nie ma pakietu.");
    expect(screen.getAllByText(/nie mają adresu e-mail/).length).toBeGreaterThan(0);
  });

  it("admin włącza wysyłkę dopiero po potwierdzeniu", async () => {
    mocks.get.mockResolvedValue({
      data: mailState({ enabled: false, can_send: false, can_toggle: true }),
    });
    mocks.put.mockResolvedValue({ data: { enabled: true } });
    renderCard();
    fireEvent.click(await screen.findByRole("switch"));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith("/api/client-onboarding/welcome-mail/switch", {
        enabled: true,
      }),
    );
    expect(mocks.confirm).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Włączyć wysyłkę maili powitalnych?" }),
    );
  });

  it("wysyłka w trybie symulacji mówi, że nic nie wyszło", async () => {
    mocks.get.mockResolvedValue({
      data: mailState({
        draft: null,
        sent: {
          id: 2,
          sent_at: "2026-10-30T09:00:00+00:00",
          sent_by: 3,
          sent_by_name: "Zofia Opiekuńska",
          recipient_email: "marek.przykladowy@example.com",
          subject: "Temat",
          body: "Treść",
          delivery: "simulated",
        },
      }),
    });
    renderCard();
    expect(await screen.findByText(/mail nie wyszedł do konsultanta/)).toBeInTheDocument();
    expect(screen.getByText(/symulacja 30\.10/)).toBeInTheDocument();
  });

  it("bez dostępu do kontraktu karta znika", async () => {
    mocks.get.mockRejectedValue(apiError(403, "Ten klient jest poza Twoim portfelem."));
    const { container } = renderCard();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
