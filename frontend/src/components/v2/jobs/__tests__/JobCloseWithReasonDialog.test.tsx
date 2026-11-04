/**
 * Zamknięcie rekrutacji z osobami w toku (13.10.2026).
 *
 * Zamknięcie nie rusza kart. 12.10.2026 duplikat requestu zamknięto z pięcioma
 * kartami w toku i okno nic o nich nie mówiło — serwer zatrzymuje teraz
 * pierwsze zamknięcie ostrzeżeniem, a okno pokazuje liczby i pyta drugi raz.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  close: vi.fn(),
  changeCloseReason: vi.fn(),
  list: vi.fn(),
  showError: vi.fn(),
  showSuccess: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: vi.fn(), post: vi.fn() },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
  jobsApi: {
    close: (...a: unknown[]) => mocks.close(...a),
    changeCloseReason: (...a: unknown[]) => mocks.changeCloseReason(...a),
    list: (...a: unknown[]) => mocks.list(...a),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

import {
  JobCloseWithReasonDialog,
  type JobCloseWithReasonDialogProps,
} from "@/components/v2/jobs/JobCloseWithReasonDialog";

const WARNING = Object.assign(new Error("HTTP 409"), {
  response: {
    status: 409,
    data: {
      detail: {
        code: "active_cards_warning",
        message:
          "W tej rekrutacji jest 5 osób w toku (ostatni ruch karty 12.10.2026). Zamknięcie nie zamyka kart — zostaną w zamkniętej rekrutacji.",
        active_cards: 5,
        columns: { screening: 2, new: 3 },
        last_moved_at: "2026-10-12T12:05:25+00:00",
      },
    },
  },
});

function renderDialog(props: Partial<JobCloseWithReasonDialogProps> = {}) {
  const onOpenChange = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <JobCloseWithReasonDialog
        open
        onOpenChange={onOpenChange}
        jobId={7}
        jobTitle="Analityk"
        clientId={3}
        defaultReason="competitor"
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onOpenChange };
}

describe("JobCloseWithReasonDialog — osoby w toku", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("ostrzeżenie zostawia okno otwarte z liczbami, a drugie kliknięcie zamyka z potwierdzeniem", async () => {
    mocks.close.mockRejectedValueOnce(WARNING).mockResolvedValueOnce({ data: {} });
    const { onOpenChange } = renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Zamknij rekrutację" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("W tej rekrutacji jest 5 osób w toku");
    // Kolejność kolumn Tablicy, nie kolejność z odpowiedzi.
    expect(alert).toHaveTextContent("Nowi 3 · Screening 2");
    expect(mocks.close).toHaveBeenCalledWith(7, "competitor", "", false, null);
    expect(mocks.showError).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);

    fireEvent.click(screen.getByRole("button", { name: "Zamknij mimo to" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.close).toHaveBeenLastCalledWith(7, "competitor", "", true, null);
  });

  it("mówi, którzy rekruterzy dostaną wiadomość, i przycisk to zapowiada (28.10.2026)", async () => {
    const withRecipients = Object.assign(new Error("HTTP 409"), {
      response: {
        status: 409,
        data: {
          detail: {
            ...WARNING.response.data.detail,
            columns: { new: 1, cv_sent: 10 },
            recipients: [
              { user_id: 26, name: "Rekruterka A", people: 8, columns: { cv_sent: 8 } },
              { user_id: 31, name: "Rekruter B", people: 2, columns: { client_interview: 1, cv_sent: 1 } },
            ],
          },
        },
      },
    });
    mocks.close.mockRejectedValueOnce(withRecipients).mockResolvedValueOnce({ data: {} });
    const { onOpenChange } = renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Zamknij rekrutację" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Po zamknięciu damy znać rekruterom");
    expect(alert).toHaveTextContent("Rekruterka A— CV wysłane 8");
    // Kolejność kolumn Tablicy w wierszu osoby.
    expect(alert).toHaveTextContent("Rekruter B— CV wysłane 1 · Rozmowa u klienta 1");

    fireEvent.click(screen.getByRole("button", { name: "Zamknij i powiadom 2 osoby" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.close).toHaveBeenLastCalledWith(7, "competitor", "", true, null);
  });

  it("bez osób w toku zamyka od razu", async () => {
    mocks.close.mockResolvedValue({ data: {} });
    const { onOpenChange } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Zamknij rekrutację" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.close).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("inna odmowa idzie toastem z treścią serwera", async () => {
    mocks.close.mockRejectedValue(new Error("Rekrutacja jest już zamknięta."));
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Zamknij rekrutację" }));
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Rekrutacja jest już zamknięta."));
    expect(screen.queryByRole("button", { name: "Zamknij mimo to" })).not.toBeInTheDocument();
  });
});

describe("JobCloseWithReasonDialog — trzy grupy powodów (21.10.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({ data: { items: [{ id: 8, title: "Analityk (drugi)" }] } });
  });

  it("bez podpowiedzi nic nie jest wybrane i nie da się zamknąć", () => {
    renderDialog({ defaultReason: null });
    expect(screen.getByRole("button", { name: "Zamknij rekrutację" })).toBeDisabled();
    for (const name of ["Wygraliśmy", "Przegraliśmy", "Nie liczy się"]) {
      expect(screen.getByRole("button", { name: new RegExp(name) })).toHaveAttribute(
        "aria-pressed",
        "false",
      );
    }
  });

  it("przegrana to tylko kandydat innej firmy", () => {
    renderDialog({ defaultReason: null });
    fireEvent.click(screen.getByTestId("close-group-lost"));
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(1);
    expect(radios[0]).toBeChecked();
    expect(screen.getByLabelText(/Klient wybrał kandydata innej firmy/)).toBeChecked();
    expect(screen.getByTestId("close-reason-effect")).toHaveTextContent("jako przegrana");
  });

  it("„Nie liczy się” wymaga uzasadnienia i wysyła rekrutację, która zostaje", async () => {
    mocks.close.mockResolvedValue({ data: {} });
    const { onOpenChange } = renderDialog({ defaultReason: null });
    fireEvent.click(screen.getByTestId("close-group-neutral"));
    expect(screen.getByLabelText(/Duplikat albo założona przez pomyłkę/)).toBeChecked();
    expect(screen.getByTestId("close-reason-effect")).toHaveTextContent("Nie wchodzi do hit ratio");
    const submit = screen.getByRole("button", { name: "Zamknij rekrutację" });
    expect(submit).toBeDisabled();

    const keep = await screen.findByRole("option", { name: /Analityk \(drugi\) · #8/ });
    fireEvent.change(screen.getByLabelText(/Która rekrutacja zostaje/), {
      target: { value: (keep as HTMLOptionElement).value },
    });
    fireEvent.change(screen.getByLabelText("Uzasadnienie *"), {
      target: { value: "Ten sam request z maila klienta" },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.close).toHaveBeenCalledWith(
      7,
      "duplicate",
      "Ten sam request z maila klienta",
      false,
      8,
    );
  });

  it("„Inny” nie jest do wyboru", () => {
    renderDialog({ defaultReason: null });
    fireEvent.click(screen.getByTestId("close-group-neutral"));
    expect(screen.queryByLabelText(/^Inny/)).not.toBeInTheDocument();
  });

  it("„Zmień powód” zapisuje przez PATCH; stary „Inny” startuje bez wyboru", async () => {
    mocks.changeCloseReason.mockResolvedValue({ data: {} });
    const { onOpenChange } = renderDialog({
      mode: "change",
      initial: { reason: "other", notes: "stara notatka", duplicateOfJobId: null },
    });
    expect(screen.getByRole("heading", { name: "Zmień powód zamknięcia" })).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Zapisz powód" });
    expect(save).toBeDisabled();
    fireEvent.click(screen.getByTestId("close-group-neutral"));
    fireEvent.click(screen.getByLabelText(/Klient zatrudnił kogoś wewnętrznie/));
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.changeCloseReason).toHaveBeenCalledWith(7, {
      reason: "internal_hire",
      notes: "stara notatka",
      duplicateOfJobId: null,
    });
    expect(mocks.close).not.toHaveBeenCalled();
  });
});
