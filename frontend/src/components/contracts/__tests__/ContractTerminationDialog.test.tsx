import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  terminate: vi.fn(),
  bulkMarkEnded: vi.fn(),
  uploadDocument: vi.fn(),
  get: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  contractsApi: {
    terminate: (...args: unknown[]) => mocks.terminate(...args),
    bulkMarkEnded: (...args: unknown[]) => mocks.bulkMarkEnded(...args),
    uploadDocument: (...args: unknown[]) => mocks.uploadDocument(...args),
    get: (...args: unknown[]) => mocks.get(...args),
  },
  CONTRACT_TERMINATION_REASONS: [
    { value: "project_ended", label: "Projekt zakończony" },
    { value: "client_budget_cut", label: "Klient — brak budżetu" },
  ],
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

import { ContractTerminationDialog } from "@/components/contracts/ContractTerminationDialog";
import { warsawToday } from "@/lib/warsaw-date";

function renderDialog(
  props: Partial<React.ComponentProps<typeof ContractTerminationDialog>> = {},
) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onClose = vi.fn();
  const onSuccess = vi.fn();
  render(
    <QueryClientProvider client={qc}>
      <ContractTerminationDialog
        contractIds={[7]}
        noticePeriodMonths={1}
        orderEndDate="2026-12-31"
        onClose={onClose}
        onSuccess={onSuccess}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onClose, onSuccess };
}

const projectEnd = () =>
  screen.getByLabelText(/Data zakończenia projektu/) as HTMLInputElement;

beforeEach(() => {
  mocks.terminate.mockReset().mockResolvedValue({ data: {} });
  mocks.bulkMarkEnded.mockReset().mockResolvedValue({ data: { changed: 2 } });
  mocks.uploadDocument.mockReset().mockResolvedValue({ data: {} });
  mocks.get.mockReset().mockResolvedValue({
    data: { notice_period_months: 1, client_order_end_date: "2026-12-31" },
  });
});

/**
 * Zgłoszenie: data zakończenia była wpisywana dwa razy — raz w formularzu
 * edycji kontraktu, raz tutaj.
 */
describe("ContractTerminationDialog — data zakończenia projektu", () => {
  it("startuje z datą podaną przez formularz edycji", () => {
    renderDialog({ defaultDate: "2026-11-30" });
    expect(projectEnd().value).toBe("2026-11-30");
  });

  it("pozostawia pole edytowalne", async () => {
    renderDialog({ defaultDate: "2026-11-30" });
    await userEvent.clear(projectEnd());
    await userEvent.type(projectEnd(), "2026-12-15");
    expect(projectEnd().value).toBe("2026-12-15");
  });

  it("bez daty z formularza podstawia dzisiaj (Warszawa)", () => {
    renderDialog();
    expect(projectEnd().value).toBe(warsawToday());
  });
});

describe("ContractTerminationDialog — rozwiązanie umowy", () => {
  it("pola rozwiązania pojawiają się po zaznaczeniu i znikają po odznaczeniu", async () => {
    renderDialog();
    expect(screen.queryByText("Tryb *")).toBeNull();
    const checkbox = screen.getByRole("checkbox", { name: /Rozwiązanie umowy/ });
    await userEvent.click(checkbox);
    expect(screen.getByText("Tryb *")).toBeInTheDocument();
    expect(screen.getByLabelText(/Ostatni dzień umowy/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Załącznik/)).toBeInTheDocument();
    await userEvent.click(checkbox);
    expect(screen.queryByText("Tryb *")).toBeNull();
    expect(screen.queryByLabelText(/Ostatni dzień umowy/)).toBeNull();
  });

  it("wypowiedzenie podpowiada ostatni dzień z okresu wypowiedzenia, a etykieta zależy od trybu", async () => {
    renderDialog();
    await userEvent.click(screen.getByRole("checkbox", { name: /Rozwiązanie umowy/ }));
    await userEvent.click(screen.getByRole("radio", { name: "Wypowiedzenie" }));
    const signed = screen.getByLabelText(/Data złożenia wypowiedzenia/);
    await userEvent.type(signed, "2026-09-10");
    const lastDay = screen.getByLabelText(/Ostatni dzień umowy/) as HTMLInputElement;
    expect(lastDay.value).toBe("2026-10-10");
    // Użytkownik może zmienić podpowiedź.
    await userEvent.clear(lastDay);
    await userEvent.type(lastDay, "2026-10-31");
    expect(lastDay.value).toBe("2026-10-31");

    await userEvent.click(screen.getByRole("radio", { name: "Porozumienie stron" }));
    expect(screen.getByLabelText(/Data zawarcia porozumienia/)).toBeInTheDocument();
  });

  it("bez zapisanego okresu wypowiedzenia pole ostatniego dnia zostaje puste", async () => {
    renderDialog({ noticePeriodMonths: null });
    await userEvent.click(screen.getByRole("checkbox", { name: /Rozwiązanie umowy/ }));
    await userEvent.click(screen.getByRole("radio", { name: "Wypowiedzenie" }));
    await userEvent.type(screen.getByLabelText(/Data złożenia wypowiedzenia/), "2026-09-10");
    expect((screen.getByLabelText(/Ostatni dzień umowy/) as HTMLInputElement).value).toBe("");
    expect(screen.getByText(/nie ma zapisanego okresu wypowiedzenia/)).toBeInTheDocument();
  });

  it("„Zakończ” jest nieaktywne, dopóki pola rozwiązania nie są kompletne", async () => {
    renderDialog();
    const submit = screen.getByRole("button", { name: "Zakończ" });
    expect(submit).toBeEnabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /Rozwiązanie umowy/ }));
    expect(submit).toBeDisabled();
  });

  it("ostrzega o datach, ale pozwala zapisać — i wysyła komplet z załącznikiem", async () => {
    const { onSuccess } = renderDialog({ orderEndDate: "2026-09-20" });
    await userEvent.clear(projectEnd());
    await userEvent.type(projectEnd(), "2026-09-23");
    await userEvent.click(screen.getByRole("checkbox", { name: /Rozwiązanie umowy/ }));
    await userEvent.click(screen.getByRole("radio", { name: "Wypowiedzenie" }));
    await userEvent.click(screen.getByRole("radio", { name: "Konsultant" }));
    await userEvent.type(screen.getByLabelText(/Data złożenia wypowiedzenia/), "2026-08-10");
    const lastDay = screen.getByLabelText(/Ostatni dzień umowy/);
    await userEvent.clear(lastDay);
    await userEvent.type(lastDay, "2026-09-15");
    const file = new File(["%PDF"], "wypowiedzenie.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText(/Załącznik/), file);

    expect(
      screen.getByText("Konsultant pracowałby na projekcie bez obowiązującej umowy."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Data zakończenia projektu wykracza poza okres zamówienia."),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Zakończ" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith({ changed: 1 }));
    expect(mocks.terminate).toHaveBeenCalledWith(7, {
      termination_reason: "project_ended",
      termination_lessons: null,
      terminated_at: "2026-09-23",
      agreement_termination: {
        mode: "notice",
        party: "consultant",
        signed_on: "2026-08-10",
        last_day: "2026-09-15",
      },
    });
    const [id, body] = mocks.uploadDocument.mock.calls[0];
    expect(id).toBe(7);
    expect((body as FormData).get("doc_type")).toBe("termination_notice");
  });

  it("bez rozwiązania umowy nie wysyła danych rozwiązania ani załącznika", async () => {
    const { onSuccess } = renderDialog();
    await userEvent.click(screen.getByRole("button", { name: "Zakończ" }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(mocks.terminate.mock.calls[0][1].agreement_termination).toBeNull();
    expect(mocks.uploadDocument).not.toHaveBeenCalled();
  });

  it("„Anuluj” zamyka bez zapisu", async () => {
    const { onClose } = renderDialog();
    await userEvent.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(onClose).toHaveBeenCalled();
    expect(mocks.terminate).not.toHaveBeenCalled();
  });
});

describe("ContractTerminationDialog — zbiorczo (Oznacz zakończone)", () => {
  it("startuje z pustym powodem i datą, a zapis idzie jednym żądaniem na wszystkie umowy", async () => {
    const { onSuccess } = renderDialog({ contractIds: [3, 4], bulk: true });
    expect(projectEnd().value).toBe("");
    const submit = screen.getByRole("button", { name: "Zakończ" });
    expect(submit).toBeDisabled();
    await userEvent.selectOptions(
      screen.getByRole("combobox"),
      "client_budget_cut",
    );
    await userEvent.type(projectEnd(), "2026-09-23");
    await userEvent.type(
      screen.getByPlaceholderText(/nie kasuje wniosków/),
      "Klient ciął budżet",
    );
    await userEvent.click(submit);
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith({ changed: 2 }));
    expect(mocks.bulkMarkEnded).toHaveBeenCalledWith([3, 4], {
      termination_reason: "client_budget_cut",
      terminated_at: "2026-09-23",
      termination_lessons: "Klient ciął budżet",
      agreement_termination: null,
    });
    expect(mocks.terminate).not.toHaveBeenCalled();
  });

  it("odmowa serwera zostaje w oknie", async () => {
    mocks.bulkMarkEnded.mockRejectedValue(new Error("boom"));
    const { onSuccess } = renderDialog({ contractIds: [3, 4], bulk: true });
    await userEvent.selectOptions(screen.getByRole("combobox"), "project_ended");
    await userEvent.type(projectEnd(), "2026-09-23");
    await userEvent.click(screen.getByRole("button", { name: "Zakończ" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(onSuccess).not.toHaveBeenCalled();
  });
});
