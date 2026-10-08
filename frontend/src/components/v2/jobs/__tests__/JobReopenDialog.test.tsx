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
  apiPatch: vi.fn(),
  apiPut: vi.fn(),
  publish: vi.fn(),
  toast: { showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn() },
}));

vi.mock("@/lib/api", () => {
  const api = {
    get: (...args: unknown[]) => mocks.apiGet(...args),
    patch: (...args: unknown[]) => mocks.apiPatch(...args),
    put: (...args: unknown[]) => mocks.apiPut(...args),
  };
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

function renderDialog(
  mode: JobReopenMode = "reopen",
  { cachedJob }: { cachedJob?: Record<string, unknown> } = {},
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (cachedJob) queryClient.setQueryData(["job", "9"], cachedJob);
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  const onOpenChange = vi.fn();
  const onOpenChampion = vi.fn();
  const onOpenTeam = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <JobReopenDialog
        jobId={9}
        open
        onOpenChange={onOpenChange}
        mode={mode}
        recruiter={null}
        onOpenChampion={onOpenChampion}
        onOpenTeam={onOpenTeam}
      />
    </QueryClientProvider>,
  );
  return {
    onOpenChange,
    onOpenChampion,
    onOpenTeam,
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

describe("JobReopenDialog — braki do ustawienia w oknie (08.10.2026)", () => {
  const HM = { code: "hiring_manager", message: "Wskaż hiring managera albo zaznacz „Klient nie podał”." };
  const DEADLINE = { code: "deadline", message: "Ustaw termin albo zaznacz „Klient nie podał”." };

  it("termin i hiring managera ustawia się w oknie, bez odsyłania do Profilu Championa", async () => {
    mockReadiness({ blocker_items: [HM, DEADLINE] });
    renderDialog("reopen", {
      cachedJob: { client_id: 3, hiring_manager_contact_id: null, deadline: null },
    });

    expect(await screen.findByText(DEADLINE.message)).toBeInTheDocument();
    // Hiring manager: ten sam picker co w zakładce „Zespół i ogłoszenie”.
    expect(screen.getByRole("button", { name: /Przypisz/ })).toBeInTheDocument();
    // Termin: data albo „Klient nie podał”.
    expect(screen.getByLabelText("Termin")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Klient nie podał" })).toBeInTheDocument();
    // Tych pól nie ma w Profilu Championa — link tam byłby ślepym zaułkiem.
    expect(screen.queryByText("Uzupełnij w Profilu Championa")).toBeNull();
    expect(screen.queryByText(/Zespół i ogłoszenie/)).toBeNull();
  });

  it("„Klient nie podał” zapisuje decyzję o terminie i odświeża braki", async () => {
    mockReadiness({ blocker_items: [DEADLINE] });
    mocks.apiPatch.mockResolvedValue({ data: {} });
    const { invalidatedKeys } = renderDialog();

    fireEvent.click(await screen.findByRole("checkbox", { name: "Klient nie podał" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(mocks.apiPatch).toHaveBeenCalledWith("/api/jobs/9", {
        deadline: null,
        deadline_time: null,
        deadline_not_provided: true,
      }),
    );
    await waitFor(() =>
      expect(invalidatedKeys()).toEqual(
        expect.arrayContaining([["job", "9"], ["job-readiness", 9]]),
      ),
    );
  });

  it("pusta data bez „Klient nie podał” nie wysyła zapisu — mówi, czego brakuje", async () => {
    mockReadiness({ blocker_items: [DEADLINE] });
    renderDialog();

    await screen.findByLabelText("Termin");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(
      await screen.findByText("Wybierz datę albo zaznacz „Klient nie podał”."),
    ).toBeInTheDocument();
    expect(mocks.apiPatch).not.toHaveBeenCalled();
  });

  it("kategoria i liczba osób prowadzą do zakładki „Zespół i ogłoszenie”, reszta do Championa", async () => {
    mockReadiness({
      blocker_items: [
        { code: "headcount", message: "Podaj liczbę osób do zatrudnienia (co najmniej 1)." },
        { code: "champion:skill_column_conflict", message: "Profil i pola rekrutacji mają różne wymagania." },
      ],
    });
    const { onOpenTeam, onOpenChampion, onOpenChange } = renderDialog();

    fireEvent.click(await screen.findByRole("button", { name: /Zespół i ogłoszenie/ }));
    expect(onOpenTeam).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);

    fireEvent.click(screen.getByRole("button", { name: "Uzupełnij w Profilu Championa" }));
    expect(onOpenChampion).toHaveBeenCalledTimes(1);
  });

  it("hiring manager bez klienta w rekrutacji prowadzi do zakładki „Zespół i ogłoszenie”", async () => {
    mockReadiness({ blocker_items: [HM] });
    renderDialog();

    expect(
      await screen.findByRole("button", { name: /Zespół i ogłoszenie/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Uzupełnij w Profilu Championa")).toBeNull();
  });
});
