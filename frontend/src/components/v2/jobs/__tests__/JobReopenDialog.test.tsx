/**
 * `JobReopenDialog` — „Otwórz ponownie” / „Dokończ i opublikuj” (04.10.2026).
 * Braki z `GET /readiness` (`blocker_items`), wybór rekrutera, powód i
 * `POST /api/jobs/{id}/publish`; odmowa 422 `job_not_ready` pokazuje braki
 * z odpowiedzi w oknie.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { JobReopenDialog, type JobReopenMode } from "@/components/v2/jobs/JobReopenDialog";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  publish: vi.fn(),
  toast: { showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn() },
}));

vi.mock("@/lib/api", () => {
  const api = { get: (...args: unknown[]) => mocks.apiGet(...args) };
  return {
    api,
    default: api,
    jobsApi: { publish: (...args: unknown[]) => mocks.publish(...args) },
  };
});
vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));

const RECRUITERS = [
  { id: 5, name: "Rekruterka Pierwsza", email: "r1@example.com" },
  { id: 6, name: "Rekruter Drugi", email: "r2@example.com" },
];

function mockReadiness(readiness: Record<string, unknown>) {
  mocks.apiGet.mockImplementation((url: unknown) =>
    typeof url === "string" && url.includes("/readiness")
      ? Promise.resolve({
          data: {
            job_id: 9,
            ready: false,
            closed: true,
            already_handed_off: false,
            blockers: [],
            allocation_enabled: true,
            allocation_mode: "shadow",
            ...readiness,
          },
        })
      : Promise.resolve({ data: RECRUITERS }),
  );
}

function renderDialog(mode: JobReopenMode = "reopen") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  const onOpenChange = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <JobReopenDialog jobId={9} open onOpenChange={onOpenChange} mode={mode} recruiter={null} />
    </QueryClientProvider>,
  );
  return {
    onOpenChange,
    invalidatedKeys: () =>
      invalidateSpy.mock.calls.map((call) => (call[0] as { queryKey: unknown[] })?.queryKey),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("JobReopenDialog", () => {
  it("pokazuje braki z `blocker_items` i blokuje publikację, dopóki są", async () => {
    mockReadiness({
      blocker_items: [
        { code: "hiring_manager", message: "Wskaż hiring managera albo zaznacz „Klient nie podał”." },
        { code: "deadline", message: "Podaj termin albo zaznacz „Klient nie podał”." },
      ],
    });
    renderDialog();

    expect(await screen.findByText("Podaj termin albo zaznacz „Klient nie podał”.")).toBeInTheDocument();
    expect(
      screen.getByText("Wskaż hiring managera albo zaznacz „Klient nie podał”."),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Otwórz ponownie" })).toBeInTheDocument();
    expect(screen.getByTestId("job-reopen-submit")).toHaveTextContent("Otwórz i opublikuj");
    expect(screen.getByTestId("job-reopen-submit")).toBeDisabled();
  });

  it("bez braków wysyła POST /publish z automatem, kanałem i powodem", async () => {
    mockReadiness({ ready: true });
    mocks.publish.mockResolvedValue({ data: {} });
    const { onOpenChange, invalidatedKeys } = renderDialog();

    expect(await screen.findByText(/Niczego nie brakuje/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Powód otwarcia (opcjonalnie)"), {
      target: { value: " klient wrócił " },
    });
    await waitFor(() => expect(screen.getByTestId("job-reopen-submit")).toBeEnabled());
    fireEvent.click(screen.getByTestId("job-reopen-submit"));

    await waitFor(() =>
      expect(mocks.publish).toHaveBeenCalledWith(9, {
        assignment_mode: "automatic",
        channel: "linkedin",
        reason: "klient wrócił",
      }),
    );
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.toast.showSuccess).toHaveBeenCalledWith(
      "Rekrutacja otwarta ponownie i opublikowana.",
    );
    expect(invalidatedKeys()).toEqual(
      expect.arrayContaining([["job", "9"], ["job-readiness", 9], ["kanban", "9"]]),
    );
  });

  it("„Dokończ i opublikuj”: wybrana osoba idzie jako recruiter_id, bez powodu", async () => {
    mockReadiness({ ready: true, closed: false, allocation_enabled: false });
    mocks.publish.mockResolvedValue({ data: {} });
    renderDialog("finish");

    expect(await screen.findByRole("heading", { name: "Dokończ i opublikuj" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Powód otwarcia (opcjonalnie)")).toBeNull();
    const select = await screen.findByTestId("job-reopen-recruiter");
    await screen.findByRole("option", { name: "Rekruter Drugi" });
    fireEvent.change(select, { target: { value: "6" } });
    fireEvent.click(screen.getByTestId("job-reopen-submit"));

    await waitFor(() =>
      expect(mocks.publish).toHaveBeenCalledWith(9, { recruiter_id: 6, channel: "linkedin" }),
    );
  });

  it("odmowa 422 `job_not_ready` pokazuje braki z odpowiedzi w oknie", async () => {
    mockReadiness({ ready: true });
    mocks.publish.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: {
            code: "job_not_ready",
            message: "Rekrutacja nie jest gotowa.",
            blockers: [{ code: "headcount", message: "Podaj liczbę osób do zatrudnienia." }],
          },
        },
      },
    });
    const { onOpenChange } = renderDialog();

    await waitFor(() => expect(screen.getByTestId("job-reopen-submit")).toBeEnabled());
    fireEvent.click(screen.getByTestId("job-reopen-submit"));

    expect(await screen.findByText("Podaj liczbę osób do zatrudnienia.")).toBeInTheDocument();
    expect(screen.getByText("Rekrutacja nie jest gotowa.")).toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(mocks.toast.showError).not.toHaveBeenCalled();
  });

  it("inny błąd idzie do toasta zdaniem z serwera", async () => {
    mockReadiness({ ready: true });
    mocks.publish.mockRejectedValue({
      response: { status: 409, data: { detail: "Automat przydziału jest wyłączony." } },
    });
    renderDialog();

    await waitFor(() => expect(screen.getByTestId("job-reopen-submit")).toBeEnabled());
    fireEvent.click(screen.getByTestId("job-reopen-submit"));
    await waitFor(() =>
      expect(mocks.toast.showError).toHaveBeenCalledWith("Automat przydziału jest wyłączony."),
    );
  });
});
