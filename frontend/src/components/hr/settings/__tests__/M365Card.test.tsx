import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
}));

const showToast = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));

import { M365Card } from "@/components/hr/settings/M365Card";
import type { M365Operation, M365Status } from "@/lib/api/hr-m365";

const STATUS: M365Status = {
  mode: "simulate",
  credentials_configured: false,
  allowlist: ["anna.przykladowa@example.com"],
  counts: { pending: 1, running: 0, failed: 1, simulated: 1, skipped: 0, done: 0 },
  deferred: 1,
  last_reconcile: { day: "2026-10-16", status: "done", finished_at: null, counts: {} },
  custom_oof_mailboxes: [{ user_id: 7, name: "Ewa Własna", last_reconciled_at: null }],
  mailbox_errors: [{ user_id: 8, name: "Jan Przykładowy", last_error: "forbidden (403)" }],
};

function operation(overrides: Partial<M365Operation>): M365Operation {
  return {
    id: 1,
    kind: "set_oof",
    status: "pending",
    user_id: 5,
    user_name: "Anna Przykładowa",
    leave_request_id: "3f1c2a9e-1b2c-4d5e-8f90-123456789abc",
    window_start: "2026-11-02",
    window_end: "2026-11-06",
    attempts: 0,
    next_attempt_at: "2026-11-01T23:00:00+00:00",
    last_error: "waiting_for_window",
    deferred: true,
    created_at: null,
    done_at: null,
    simulated_request: null,
    ...overrides,
  };
}

const QUEUES: Record<string, M365Operation[]> = {
  pending: [operation({ id: 1, kind: "forward_rule_open" })],
  failed: [
    operation({
      id: 2,
      status: "failed",
      attempts: 6,
      last_error: "forbidden (403)",
      deferred: false,
    }),
  ],
  simulated: [
    operation({
      id: 3,
      status: "simulated",
      last_error: null,
      deferred: false,
      simulated_request: {
        mailbox: "anna.przykladowa@example.com",
        at: "2026-10-16T10:00:00+00:00",
        requests: [
          {
            method: "GET",
            path: "/users/anna.przykladowa@example.com/mailboxSettings/automaticRepliesSetting",
          },
          {
            method: "PATCH",
            path: "/users/anna.przykladowa@example.com/mailboxSettings",
            body: { automaticRepliesSetting: { status: "scheduled" } },
          },
        ],
      },
    }),
  ],
};

function mockApi({ operationsFail = false } = {}) {
  get.mockImplementation((url: string, config?: { params?: { status?: string } }) => {
    if (url === "/api/hr/admin/m365/status") return Promise.resolve({ data: STATUS });
    if (operationsFail) {
      return Promise.reject({ response: { status: 500, data: { detail: "Błąd" } } });
    }
    const items = QUEUES[config?.params?.status ?? "pending"] ?? [];
    return Promise.resolve({ data: { items, total: items.length } });
  });
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <M365Card />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  showToast.mockReset();
});

describe("M365Card", () => {
  it("shows the mode, the trial list and the waiting queue with its reason", async () => {
    mockApi();
    renderCard();
    expect(await screen.findByLabelText("Tryb: Symulacja")).toBeInTheDocument();
    expect(screen.getByText(/nie trafiają do skrzynek/)).toBeInTheDocument();
    expect(screen.getByText(/Tylko lista próbna: anna.przykladowa@example.com/)).toBeInTheDocument();
    expect(await screen.findByText("Przekierowanie poczty")).toBeInTheDocument();
    expect(screen.getByText("2.11.2026 – 6.11.2026")).toBeInTheDocument();
    expect(screen.getByText(/Czeka na pierwszy dzień urlopu/)).toBeInTheDocument();
    expect(screen.getByText("Ewa Własna")).toBeInTheDocument();
    expect(screen.getByText(/Brak uprawnień aplikacji w Exchange \(403\)/)).toBeInTheDocument();
  });

  it("previews the exact simulated requests", async () => {
    mockApi();
    renderCard();
    await userEvent.click(await screen.findByRole("tab", { name: /Zasymulowane/ }));
    const toggle = await screen.findByRole("button", { name: "Podgląd" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    const preview = screen.getByLabelText("Podgląd żądań");
    expect(preview).toHaveTextContent(
      "PATCH /users/anna.przykladowa@example.com/mailboxSettings",
    );
    expect(preview).toHaveTextContent('"status": "scheduled"');
    expect(get).toHaveBeenCalledWith("/api/hr/admin/m365/operations", {
      params: { status: "simulated", limit: 50 },
    });
  });

  it("retries a failed operation and confirms with a toast", async () => {
    mockApi();
    post.mockResolvedValue({ data: operation({ id: 2, status: "pending", attempts: 0 }) });
    renderCard();
    await userEvent.click(await screen.findByRole("tab", { name: /Nieudane/ }));
    const row = (await screen.findByText(/próba 6 z 6/)).closest("tr") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Ponów" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/hr/admin/m365/operations/2/retry"),
    );
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Operacja wróciła do kolejki", "success"),
    );
  });

  it("shows a failed queue read as an error, not as an empty queue", async () => {
    mockApi({ operationsFail: true });
    renderCard();
    await screen.findByLabelText("Tryb: Symulacja");
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się pobrać danych");
    expect(screen.queryByText("Kolejka jest pusta.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
  });
});
