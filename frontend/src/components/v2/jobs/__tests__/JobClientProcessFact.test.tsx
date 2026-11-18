/**
 * `JobClientProcessFact` — „Proces u klienta” w nagłówku rekrutacji (18.11.2026).
 * Odczyt dla każdego, zapis po fakcie tylko dla osoby edytującej Championa.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { JobClientProcessFact } from "@/components/v2/jobs/JobClientProcessFact";
import type { ClientProcess, ClientProcessHints } from "@/lib/job-client-process";

const getMock = vi.fn();
const putMock = vi.fn();

vi.mock("@/lib/api", () => {
  const client = {
    get: (...args: unknown[]) => getMock(...args),
    put: (...args: unknown[]) => putMock(...args),
  };
  return { api: client, default: client };
});

const PROCESS: ClientProcess = {
  steps: [
    { kind: "tech_interview", format: "remote", duration: "60 min" },
    { kind: "home_task", format: "remote", duration: "ok. 3 h" },
  ],
  decision_workdays: 10,
  set_by_name: "Delivery Lead",
  set_at: "2026-11-12T10:00:00+01:00",
};

const HINTS: ClientProcessHints = {
  client_id: 11,
  suggested: {
    steps: [{ kind: "online_test", format: "remote", duration: "45 min" }],
    decision_workdays: 5,
    from_job_id: 700,
  },
  measured: {
    cv_to_interview_days: 8,
    interview_to_decision_days: 27,
    cv_to_decision_days: 29,
    decisions: 180,
    months: 18,
  },
};

function renderFact(props: Partial<React.ComponentProps<typeof JobClientProcessFact>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <JobClientProcessFact
          jobId={501}
          clientId={11}
          clientName="Nordea"
          process={PROCESS}
          canEdit
          {...props}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { invalidate };
}

beforeEach(() => {
  getMock.mockReset().mockResolvedValue({ data: HINTS });
  putMock.mockReset();
});

describe("JobClientProcessFact", () => {
  it("pokazuje etapy z czasem z historii i pyta o podpowiedź bez tej rekrutacji", async () => {
    renderFact();
    const chip = screen.getByTestId("job-header-fact-process");
    await waitFor(() => expect(chip).toHaveTextContent("2 etapy · ~4 tyg."));
    expect(getMock).toHaveBeenCalledWith("/api/jobs/client-process", {
      params: { client_id: 11, job_id: 501 },
    });
    await userEvent.click(chip);
    expect(screen.getByTestId("client-process-steps")).toHaveTextContent("Rozmowa techniczna");
    expect(screen.getByTestId("client-process-measured")).toHaveTextContent("mediana z 180 decyzji");
    expect(screen.getByText(/Decyzja trwa dłużej, niż klient obiecuje/)).toBeInTheDocument();
    expect(screen.getByTestId("client-process-sentence")).toHaveTextContent(
      "Proces u klienta ma 2 etapy",
    );
  });

  it("bez prawa edycji nie ma „Zmień” ani „Wpisz etapy”", async () => {
    renderFact({ canEdit: false });
    await userEvent.click(screen.getByTestId("job-header-fact-process"));
    expect(screen.queryByRole("button", { name: "Zmień" })).not.toBeInTheDocument();

    renderFact({ canEdit: false, process: null });
    const chips = screen.getAllByTestId("job-header-fact-process");
    await userEvent.click(chips[1]);
    expect(screen.queryByRole("button", { name: "Wpisz etapy" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Użyj" })).not.toBeInTheDocument();
  });

  it("bez procesu mówi „nie podano”, a „Użyj” bierze etapy poprzedniej rekrutacji do zapisu", async () => {
    putMock.mockResolvedValue({ data: { job_id: 501, client_process: HINTS.suggested } });
    const { invalidate } = renderFact({ process: null });
    const chip = screen.getByTestId("job-header-fact-process");
    expect(chip).toHaveTextContent("proces: nie podano");
    await userEvent.click(chip);
    await userEvent.click(await screen.findByRole("button", { name: "Użyj" }));
    expect(screen.getByRole("button", { name: "Test online + rozmowa", pressed: false })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith("/api/jobs/501/client-process", {
        steps: [{ kind: "online_test", format: "remote", duration: "45 min" }],
        decision_workdays: 5,
      }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["job", "501"] });
  });

  it("zmiana gotowym układem i błąd zapisu zostawia edycję z komunikatem", async () => {
    putMock.mockRejectedValue(new Error("boom"));
    renderFact();
    await userEvent.click(screen.getByTestId("job-header-fact-process"));
    await userEvent.click(screen.getByRole("button", { name: "Zmień" }));
    await userEvent.click(screen.getByRole("button", { name: "1 rozmowa" }));
    await userEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(putMock).toHaveBeenCalledWith("/api/jobs/501/client-process", {
        steps: [{ kind: "tech_interview", format: "remote", duration: "60 min" }],
        decision_workdays: 10,
      }),
    );
    expect(await screen.findByText("Nie udało się zapisać procesu u klienta.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeInTheDocument();
  });

  it("zły termin decyzji podświetla pole i nie zmienia wartości", async () => {
    renderFact();
    await userEvent.click(screen.getByTestId("job-header-fact-process"));
    await userEvent.click(screen.getByRole("button", { name: "Zmień" }));
    const days = screen.getByLabelText(/Decyzja klienta w ciągu/);
    await userEvent.clear(days);
    await userEvent.type(days, "99");
    expect(screen.getByText("Wpisz liczbę od 1 do 60 albo zostaw puste.")).toBeInTheDocument();
  });
});
