/**
 * „Zamknięcia i hit ratio” (21.10.2026): lista kontrolna wyłączeń z hit ratio
 * i zamknięć do przeglądu, „Zmień powód” z tego samego okna co rekrutacja.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ closures: vi.fn(), listJobs: vi.fn() }));

vi.mock("@/lib/insights-api", async (orig) => ({
  ...(await orig<typeof import("@/lib/insights-api")>()),
  insightsBoardApi: { hitRatioClosures: () => mocks.closures() },
}));
vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: vi.fn() },
  extractErrorMsg: () => "Błąd",
  jobsApi: { changeCloseReason: vi.fn(), close: vi.fn(), list: (...args: unknown[]) => mocks.listJobs(...args) },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { HitRatioClosures } from "@/components/insights/sections/HitRatioClosures";
import { useAuthStore } from "@/store/auth";

function signInAs(role: string) {
  useAuthStore.setState({ user: { id: 7, role, roles: [role] } } as never);
}

const ROW = {
  title: "Analityk",
  client_name: "Klient A",
  client_id: 5,
  duplicate_of_job_id: null,
  closed_at: "2026-10-20T10:00:00+00:00",
  closed_by_name: "DL Przykładowy",
  delivery_lead_name: null,
};

function renderReport() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <HitRatioClosures />
    </QueryClientProvider>,
  );
}

describe("HitRatioClosures", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listJobs.mockResolvedValue({ data: { items: [] } });
    signInAs("delivery_lead");
  });

  it("pokazuje grupy, wyłączenia z uzasadnieniem i zamknięcia do przeglądu", async () => {
    mocks.closures.mockResolvedValue({
      since: "2026-10-11T22:00:00+00:00",
      counts: { won: 10, lost: 25, neutral: 1, unreviewed: 18 },
      hit_ratio: 18.9,
      neutral: [{ ...ROW, job_id: 1, close_reason: "duplicate", close_notes: "Ten sam request" }],
      unreviewed: [{ ...ROW, job_id: 2, close_reason: "other", close_notes: null }],
    });
    renderReport();
    expect(await screen.findByText("18,9%")).toBeInTheDocument();
    expect(screen.getByText("43")).toBeInTheDocument();
    expect(screen.getByText("w tym 18 do przejrzenia")).toBeInTheDocument();
    const neutral = screen.getByTestId("closures-neutral");
    expect(within(neutral).getByText("Duplikat albo założona przez pomyłkę")).toBeInTheDocument();
    expect(within(neutral).getByText("Ten sam request")).toBeInTheDocument();
    const unreviewed = screen.getByTestId("closures-unreviewed");
    expect(within(unreviewed).getByText("Inny (do przejrzenia)")).toBeInTheDocument();

    fireEvent.click(within(unreviewed).getByRole("button", { name: "Zmień powód" }));
    expect(await screen.findByRole("heading", { name: "Zmień powód zamknięcia" })).toBeInTheDocument();
  });

  // Audyt 22.10.2026 (F59): PATCH /close-reason wymaga „recruitment_manage” —
  // Rada nadzorcza i Finanse widzą raport tylko do odczytu, bez przycisku na 403.
  it("bez uprawnienia do zarządzania rekrutacją nie ma „Zmień powód”", async () => {
    signInAs("board");
    mocks.closures.mockResolvedValue({
      since: "2026-10-11T22:00:00+00:00",
      counts: { won: 0, lost: 0, neutral: 0, unreviewed: 1 },
      hit_ratio: 0,
      neutral: [],
      unreviewed: [{ ...ROW, job_id: 2, close_reason: "other", close_notes: null }],
    });
    renderReport();
    expect(await screen.findByText("Analityk")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zmień powód" })).not.toBeInTheDocument();
  });

  // Audyt 22.10.2026 (F61): okno zna klienta, a zapisana rekrutacja, która
  // zostaje, jest widoczna w polu, nawet gdy nie ma jej na liście otwartych.
  it("„Zmień powód” przy duplikacie pokazuje zapisaną rekrutację, która zostaje", async () => {
    mocks.listJobs.mockResolvedValue({ data: { items: [{ id: 9002, title: "Analityk 2" }] } });
    mocks.closures.mockResolvedValue({
      since: "2026-10-11T22:00:00+00:00",
      counts: { won: 0, lost: 0, neutral: 1, unreviewed: 0 },
      hit_ratio: null,
      neutral: [
        { ...ROW, job_id: 9104, close_reason: "duplicate", close_notes: "Ten sam", duplicate_of_job_id: 9001 },
      ],
      unreviewed: [],
    });
    renderReport();
    fireEvent.click(await screen.findByRole("button", { name: "Zmień powód" }));
    const select = await screen.findByLabelText(/Która rekrutacja zostaje/);
    expect(select).toHaveValue("9001");
    expect(await screen.findByRole("option", { name: "Analityk 2 · #9002" })).toBeInTheDocument();
    expect(mocks.listJobs).toHaveBeenCalledWith(expect.objectContaining({ client_id: 5 }));
  });

  it("awaria nie udaje pustej listy", async () => {
    mocks.closures.mockRejectedValue(Object.assign(new Error("HTTP 500"), { response: { status: 500 } }));
    renderReport();
    expect(await screen.findByText(/Zamknięcia i hit ratio/)).toBeInTheDocument();
    expect(screen.queryByText("Nic nie czeka na przegląd.")).not.toBeInTheDocument();
  });
});
