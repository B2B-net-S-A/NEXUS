import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: (...a: unknown[]) => put(...a),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));
vi.mock("@/components/v2/recruitment/DlReviewPanel", () => ({
  DlReviewPanel: ({
    task,
    open,
    canSendToClient,
  }: {
    task: { candidate_name: string } | null;
    open: boolean;
    canSendToClient?: boolean;
  }) =>
    open && task ? (
      <div role="dialog" aria-label="Przegląd DL">
        {task.candidate_name} · wysyłka {canSendToClient ? "tak" : "nie"}
      </div>
    ) : null,
}));
vi.mock("@/components/v2/dashboard/CproQueueDialog", () => ({
  CproQueueDialog: ({ open, initialJobId }: { open: boolean; initialJobId?: number | null }) =>
    open ? <div role="dialog" aria-label="Kolejka Cpro">rekrutacja {String(initialJobId)}</div> : null,
  CproSenderControl: ({ sender }: { sender?: { user_name: string | null } }) => (
    <p>Do Cpro wrzuca: {sender?.user_name ?? "…"}</p>
  ),
}));

import { BoardTasksPanel } from "@/components/v2/dashboard/BoardTasksPanel";
import { useAuthStore } from "@/store/auth";

const since = new Date(Date.now() - 3 * 86_400_000).toISOString();

function row(kind: string, over: Record<string, unknown> = {}) {
  return {
    kind,
    stage_id: 11,
    candidate_id: 21,
    candidate_name: "Anna Nowak",
    job_id: 31,
    job_title: "Java Developer",
    client_id: 5,
    client_name: "Nordea",
    since,
    process_state_version: 4,
    target_stage_def_id: 303,
    assignee_id: null,
    assignee_name: null,
    ...over,
  };
}

function mockQueue(queue: Record<string, unknown>) {
  get.mockImplementation((url: string) => {
    if (url === "/api/board-tasks")
      return Promise.resolve({ data: { window_days: 14, cpro_to_send: [], cpro_sent: [], ...queue } });
    if (url === "/api/board-tasks/cpro/sender")
      return Promise.resolve({ data: { user_id: 5, user_name: "Kinga Sordyl", until: null } });
    return Promise.resolve({ data: [] });
  });
}

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BoardTasksPanel />
    </QueryClientProvider>,
  );
}

describe("BoardTasksPanel — „Czeka na Ciebie” na pulpicie", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: { id: 1, role: "head_of_recruitment" } } as never);
    post.mockResolvedValue({ data: {} });
  });

  it("nic nie czeka → panelu nie ma (pusta ramka uczyłaby go ignorować)", async () => {
    mockQueue({});
    const { container } = renderPanel();
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("nie ma już kolejki „Czeka na DZ” ani przeglądu DZ", async () => {
    mockQueue({ dz: [row("dz")], cpro_sent: [row("cpro_sent")] });
    renderPanel();
    await screen.findByRole("region", { name: "Wysłane do Cpro" });
    expect(screen.queryByRole("region", { name: "Czeka na DZ" })).toBeNull();
    expect(screen.queryByRole("button", { name: /DZ/ })).toBeNull();
  });

  it("„Czeka na Twój przegląd (DL)” pokazuje wynik QC i otwiera panel przeglądu", async () => {
    mockQueue({
      can_send_to_client: true,
      dl_review_window_days: 30,
      dl_review: [
        row("dl_review", { candidate_name: "Ola Przegląd", client_name: "PKO BP", qc_status: "failed", qc_blocking_failed: 2 }),
      ],
    });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Czeka na Twój przegląd (DL)" });
    expect(within(section).getByText("Java Developer · PKO BP")).toBeTruthy();
    expect(within(section).getByText("QC: 2 do poprawy")).toBeTruthy();
    await userEvent.click(within(section).getByRole("button", { name: "Przejrzyj: Ola Przegląd" }));
    expect(screen.getByRole("dialog", { name: "Przegląd DL" })).toHaveTextContent("Ola Przegląd · wysyłka tak");
  });

  it("Cpro: linia per rekrutacja, kto wrzuca i „Wrzucaj po kolei” otwiera kolejkę", async () => {
    mockQueue({
      cpro_to_send: [
        row("cpro_to_send", { stage_id: 12, candidate_name: "Pierwsza" }),
        row("cpro_to_send", { stage_id: 15, candidate_id: 25, candidate_name: "Druga" }),
        row("cpro_to_send", { stage_id: 16, candidate_id: 26, candidate_name: "Trzecia" }),
        row("cpro_to_send", { stage_id: 17, candidate_id: 27, candidate_name: "Czwarta" }),
        row("cpro_to_send", { stage_id: 13, candidate_id: 22, job_id: 32, job_title: "QA Engineer" }),
      ],
    });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Do wrzucenia do Cpro" });
    expect(within(section).getByText("5")).toBeTruthy();
    expect(within(section).getByRole("button", { name: "Java Developer · 4 osoby" })).toBeTruthy();
    expect(within(section).getByRole("button", { name: "QA Engineer · 1 osoba" })).toBeTruthy();
    expect(await within(section).findByText("Do Cpro wrzuca: Kinga Sordyl")).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/api/board-tasks/cpro/sender");

    await userEvent.click(within(section).getByRole("button", { name: "Wrzucaj po kolei" }));
    expect(screen.getByRole("dialog", { name: "Kolejka Cpro" })).toHaveTextContent("rekrutacja null");
    await userEvent.keyboard("{Escape}");
    await userEvent.click(within(section).getByRole("button", { name: "QA Engineer · 1 osoba" }));
    expect(screen.getByRole("dialog", { name: "Kolejka Cpro" })).toHaveTextContent("rekrutacja 32");
  });

  it("długa lista pokazuje najpierw kilka osób i „Pokaż wszystkie (N)”", async () => {
    mockQueue({
      cpro_sent: Array.from({ length: 9 }, (_, i) =>
        row("cpro_sent", { stage_id: 100 + i, candidate_id: 200 + i, candidate_name: `Osoba ${i + 1}` }),
      ),
    });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Wysłane do Cpro" });
    expect(within(section).getAllByRole("listitem")).toHaveLength(6);
    expect(within(section).getByText("Osoba 1")).toHaveAttribute("href", "/jobs/31?candidate=200");
    await userEvent.click(within(section).getByRole("button", { name: "Pokaż wszystkie (9)" }));
    expect(within(section).getAllByRole("listitem")).toHaveLength(9);
    expect(within(section).getByRole("button", { name: "Zwiń" })).toHaveAttribute("aria-expanded", "true");
  });
});
