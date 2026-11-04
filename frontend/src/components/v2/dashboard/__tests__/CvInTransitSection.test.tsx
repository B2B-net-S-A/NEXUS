import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

const apiMock = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));

import { CvInTransitSection } from "@/components/v2/dashboard/CvInTransitSection";
import { waitingFor, type CvInTransit, type CvTransitRow } from "@/lib/api/boardTasks";

const DAY_MS = 86_400_000;

function daysAgo(days: number): string {
  return new Date(Date.now() - days * DAY_MS).toISOString();
}

function reviewRow(over: Partial<CvTransitRow> = {}): CvTransitRow {
  return {
    kind: "in_review",
    stage_id: 41,
    candidate_id: 2,
    candidate_name: "Adam Wrona",
    job_id: 3,
    job_title: "ZOB-1 Java Developer",
    job_working_title: "Java · Spring",
    client_name: "Bank Kappa",
    since: daysAgo(12),
    holder_name: "Marta Kowalczyk",
    qc_status: "passed",
    ready_since: daysAgo(5),
    waiting_workdays: 3,
    can_nudge: true,
    ...over,
  };
}

function transit(rows: CvTransitRow[]): CvInTransit {
  return {
    returned: [],
    in_review: rows,
    sent: [],
    returned_total: 0,
    in_review_total: rows.length,
    sent_total: 0,
    returned_window_days: 14,
    sent_window_days: 7,
  };
}

/** Lista „W przeglądzie” jest zwinięta — wiersze widać dopiero po „Pokaż”. */
function renderOpen(rows: CvTransitRow[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CvInTransitSection transit={transit(rows)} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: /Pokaż/ }));
}

function rowOf(name: string): HTMLElement {
  const item = screen.getByRole("link", { name }).closest("li");
  if (!item) throw new Error(`Brak wiersza: ${name}`);
  return item;
}

beforeEach(() => {
  apiMock.post.mockReset();
  toast.showSuccess.mockReset();
  toast.showError.mockReset();
  toast.showInfo.mockReset();
});

describe("CvInTransitSection — „W przeglądzie” po stronie rekrutera", () => {
  it("dopóki QC nie przeszło, wiersz mówi „Twój ruch” zamiast „Przegląda” i nie daje przypomnienia", () => {
    renderOpen([
      reviewRow({
        stage_id: 1,
        candidate_name: "Ewa Lis",
        qc_status: "failed",
        ready_since: null,
        waiting_workdays: 0,
        can_nudge: false,
      }),
      reviewRow({
        stage_id: 2,
        candidate_name: "Jan Dąb",
        qc_status: "unchecked",
        ready_since: null,
        waiting_workdays: 0,
        can_nudge: false,
      }),
    ]);
    const failed = within(rowOf("Ewa Lis"));
    expect(failed.getByText("QC do poprawy — Twój ruch")).toBeInTheDocument();
    expect(failed.queryByText(/Przegląda/)).toBeNull();
    // Czas to „od kiedy karta stoi w kolumnie”, bez czerwieni — nikt nie zwleka.
    expect(failed.getByText(waitingFor(daysAgo(12)))).toHaveClass("text-muted-foreground");
    expect(within(rowOf("Jan Dąb")).getByText("QC nie sprawdzone — Twój ruch")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Przypomnij/ })).toBeNull();
  });

  it("gotowe CV liczy czekanie od gotowości; od 2 dni roboczych czas jest czerwony", () => {
    renderOpen([
      reviewRow({ stage_id: 1, candidate_name: "Adam Wrona" }),
      reviewRow({
        stage_id: 2,
        candidate_name: "Ola Sowa",
        ready_since: daysAgo(1),
        waiting_workdays: 1,
        can_nudge: false,
      }),
    ]);
    const late = within(rowOf("Adam Wrona"));
    expect(waitingFor(daysAgo(5))).not.toBe(waitingFor(daysAgo(12)));
    expect(late.getByText(waitingFor(daysAgo(5)))).toHaveClass("text-destructive");
    expect(late.getByText("Przegląda: Marta Kowalczyk")).toBeInTheDocument();
    expect(late.getByRole("button", { name: "Przypomnij Delivery Leadowi: Adam Wrona" })).toBeEnabled();

    const fresh = within(rowOf("Ola Sowa"));
    expect(fresh.getByText(waitingFor(daysAgo(1)))).toHaveClass("text-muted-foreground");
    // Przycisk tylko tam, gdzie serwer pozwala przypomnieć.
    expect(fresh.queryByRole("button", { name: /Przypomnij/ })).toBeNull();
  });

  it("kolejka Cpro i starszy serwer bez nowych pól zostają przy dotychczasowym wierszu", () => {
    renderOpen([
      reviewRow({ stage_id: 1, candidate_name: "Iga Kos", kind: "cpro_queue", holder_name: "Adam Wzorcowy" }),
      {
        kind: "in_review",
        stage_id: 2,
        candidate_id: 5,
        candidate_name: "Piotr Zając",
        job_id: 3,
        job_title: "ZOB-1 Java Developer",
        since: daysAgo(4),
      },
    ]);
    expect(within(rowOf("Iga Kos")).getByText("Kolejka Cpro: Adam Wzorcowy")).toBeInTheDocument();
    const old = within(rowOf("Piotr Zając"));
    expect(old.getByText("Przegląda: Delivery Lead klienta")).toBeInTheDocument();
    expect(old.getByText(waitingFor(daysAgo(4)))).toHaveClass("text-muted-foreground");
    expect(screen.queryByRole("button", { name: /Przypomnij/ })).toBeNull();
    expect(screen.queryByText(/Twój ruch/)).toBeNull();
  });

  it("„Przypomnij” woła trasę przypomnienia, blokuje się na czas wysyłki i potwierdza", async () => {
    let finish: (value: { data: { sent: boolean; recipients: number } }) => void = () => {};
    apiMock.post.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    renderOpen([reviewRow()]);
    const button = screen.getByRole("button", { name: "Przypomnij Delivery Leadowi: Adam Wrona" });
    fireEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(apiMock.post).toHaveBeenCalledWith("/api/board-tasks/dl-send/41/nudge");

    finish({ data: { sent: true, recipients: 1 } });
    await waitFor(() =>
      expect(toast.showSuccess).toHaveBeenCalledWith("Przypomnienie wysłane do Delivery Leada."),
    );
    await waitFor(() => expect(button).toBeEnabled());
    expect(toast.showInfo).not.toHaveBeenCalled();
    expect(toast.showError).not.toHaveBeenCalled();
  });

  it("drugie przypomnienie tego samego dnia to informacja, nie sukces", async () => {
    apiMock.post.mockResolvedValue({ data: { sent: false, reason: "already_today" } });
    renderOpen([reviewRow()]);
    fireEvent.click(screen.getByRole("button", { name: "Przypomnij Delivery Leadowi: Adam Wrona" }));
    await waitFor(() =>
      expect(toast.showInfo).toHaveBeenCalledWith("Dziś już przypomniano — Delivery Lead ma to w ikonie „CV”."),
    );
    expect(toast.showSuccess).not.toHaveBeenCalled();
    expect(toast.showError).not.toHaveBeenCalled();
  });

  it("odmowa serwera pokazuje jego zdanie", async () => {
    apiMock.post.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: "Ta rekrutacja nie ma Delivery Leada — nie ma komu przypomnieć." },
      },
    });
    renderOpen([reviewRow()]);
    fireEvent.click(screen.getByRole("button", { name: "Przypomnij Delivery Leadowi: Adam Wrona" }));
    await waitFor(() =>
      expect(toast.showError).toHaveBeenCalledWith(
        "Ta rekrutacja nie ma Delivery Leada — nie ma komu przypomnieć.",
      ),
    );
    expect(toast.showSuccess).not.toHaveBeenCalled();
  });
});
