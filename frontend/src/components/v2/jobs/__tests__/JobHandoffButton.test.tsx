import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { JobHandoffButton } from "@/components/v2/jobs/JobHandoffButton";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  handoff: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  jobsApi: { handoff: (...args: unknown[]) => mocks.handoff(...args) },
}));

function renderButton() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <JobHandoffButton jobId={7} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // Komponent wykonuje DWA różne zapytania GET: listę rekruterów i gotowość
  // rekrutacji (0270). Jeden wspólny `mockResolvedValue` podawał listę
  // rekruterów także jako odpowiedź gotowości, więc `blockers` było
  // `undefined` — komponent jest na to odporny, ale test przestawał opisywać
  // cokolwiek prawdziwego.
  mocks.apiGet.mockImplementation((url: unknown) =>
    typeof url === "string" && url.includes("/readiness")
      ? Promise.resolve({
          data: {
            job_id: 1,
            ready: true,
            blockers: [],
            closed: false,
            already_handed_off: false,
          },
        })
      : Promise.resolve({
          data: [{ id: 5, name: "Rec One", email: "r@example.com" }],
        }),
  );
});

describe("JobHandoffButton", () => {
  it("assigns the chosen recruiter and starts the search", async () => {
    mocks.handoff.mockResolvedValue({ data: { status: "handed_off" } });

    renderButton();
    fireEvent.click(screen.getByTestId("handoff-open"));
    await screen.findByText("Rec One");
    fireEvent.change(screen.getByTestId("handoff-recruiter-select"), {
      target: { value: "5" },
    });
    fireEvent.click(screen.getByTestId("handoff-submit"));

    await waitFor(() => expect(mocks.handoff).toHaveBeenCalledWith(7, 5));
    expect(await screen.findByTestId("handoff-done")).toBeInTheDocument();
  });

  it("shows readiness blockers on a 422 instead of starting the search", async () => {
    mocks.handoff.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: {
            message: "Rekrutacja nie jest gotowa.",
            blockers: ["Dodaj co najmniej 2 pytania screeningowe w Profilu Championa."],
          },
        },
      },
    });

    renderButton();
    fireEvent.click(screen.getByTestId("handoff-open"));
    await screen.findByText("Rec One");
    fireEvent.change(screen.getByTestId("handoff-recruiter-select"), {
      target: { value: "5" },
    });
    fireEvent.click(screen.getByTestId("handoff-submit"));

    expect(await screen.findByTestId("handoff-blockers")).toHaveTextContent(
      "pytania screeningowe",
    );
    expect(screen.queryByTestId("handoff-done")).not.toBeInTheDocument();
  });

  it("pokazuje braki gotowości bez klikania i blokuje przycisk", async () => {
    // Sedno zmiany 0270: na próbce 100 rekrutacji z produkcji bramkę
    // przechodzą 23, więc trzy na cztery kliknięcia kończyły się 422 z listą,
    // którą dało się pokazać od razu.
    mocks.apiGet.mockImplementation((url: unknown) =>
      typeof url === "string" && url.includes("/readiness")
        ? Promise.resolve({
            data: {
              job_id: 1,
              ready: false,
              blockers: ["Dodaj co najmniej 2 pytania screeningowe."],
              closed: false,
              already_handed_off: false,
            },
          })
        : Promise.resolve({ data: [] }),
    );

    renderButton();

    await screen.findByTestId("handoff-readiness-blockers");
    expect(
      screen.getByText("Dodaj co najmniej 2 pytania screeningowe."),
    ).toBeInTheDocument();
    expect(screen.getByTestId("handoff-open")).toBeDisabled();
  });
});

