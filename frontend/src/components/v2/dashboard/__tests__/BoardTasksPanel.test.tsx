import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    patch: (...a: unknown[]) => patch(...a),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
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
  get.mockImplementation((url: string) =>
    url === "/api/board-tasks"
      ? Promise.resolve({ data: { window_days: 14, can_approve_dz: true, dz: [], cpro_to_send: [], cpro_sent: [], ...queue } })
      : Promise.resolve({ data: [{ id: 1, name: "Artur" }, { id: 44, name: "Marta" }] }),
  );
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
    patch.mockResolvedValue({ data: { stage_id: 12, assignee_id: 44, assignee_name: "Marta", added_to_team: true } });
  });

  it("nic nie czeka → panelu nie ma (pusta ramka uczyłaby go ignorować)", async () => {
    mockQueue({});
    const { container } = renderPanel();
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("„DZ” to zwykły ruch na etap DZ z wersją procesu", async () => {
    mockQueue({ dz: [row("dz")] });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Czeka na DZ" });
    expect(within(section).getByText("Anna Nowak")).toHaveAttribute("href", "/jobs/31?candidate=21");
    expect(within(section).getByText("od 3 dni")).toBeTruthy();
    await userEvent.click(within(section).getByRole("button", { name: "Zatwierdź przez DZ: Anna Nowak" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/pipeline/move", {
        candidate_id: 21,
        job_id: 31,
        stage_def_id: 303,
        expected_state_version: 4,
      }),
    );
    expect(showSuccess).toHaveBeenCalledWith("Anna Nowak — zatwierdzony przez DZ.");
  });

  it("Cpro: nieprzypisaną osobę typuje się wyborem; „Oznacz wysłanie” tylko dla wytypowanego", async () => {
    mockQueue({
      cpro_to_send: [
        row("cpro_to_send", { stage_id: 12, candidate_name: "Bez Osoby" }),
        row("cpro_to_send", { stage_id: 13, candidate_id: 22, candidate_name: "Moja Osoba", assignee_id: 1, assignee_name: "Artur" }),
      ],
      cpro_sent: [row("cpro_sent", { stage_id: 14, candidate_name: "Już Wysłana" })],
    });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Do wysłania do Cpro" });
    const select = within(section).getByLabelText("Kto wysyła do Cpro: Bez Osoby");
    await waitFor(() => expect(within(select).getByRole("option", { name: "Wysyła: Marta" })).toBeTruthy());
    await userEvent.selectOptions(select, "44");
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/api/board-tasks/cpro/12/assignee", { assignee_id: 44 }));
    expect(showSuccess).toHaveBeenCalledWith("Wysyła: Marta (dodana do zespołu rekrutacji).");

    const links = within(section).getAllByRole("link", { name: /Oznacz wysłanie/ });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/jobs/31?candidate=22");
    expect(within(screen.getByRole("region", { name: "Wysłane do Cpro" })).getByText("Już Wysłana")).toBeTruthy();
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
    await userEvent.click(within(section).getByRole("button", { name: "Pokaż wszystkie (9)" }));
    expect(within(section).getAllByRole("listitem")).toHaveLength(9);
    expect(within(section).getByRole("button", { name: "Zwiń" })).toHaveAttribute("aria-expanded", "true");
  });

  it("recruiter bez prawa DZ nie dostaje przycisku zatwierdzenia", async () => {
    mockQueue({ can_approve_dz: false, dz: [row("dz")] });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Czeka na DZ" });
    expect(within(section).queryByRole("button")).toBeNull();
  });
});
