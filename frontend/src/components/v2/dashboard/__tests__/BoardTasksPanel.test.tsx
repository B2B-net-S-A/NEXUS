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

function followupRow(over: Record<string, unknown> = {}) {
  return {
    candidate_id: 21,
    candidate_name: "Jan Wiśniewski",
    phone: "600 214 390",
    due_on: "2026-09-22",
    state: "overdue",
    overdue_days: 2,
    caller_id: 1,
    caller_name: "Anna Kowalczyk",
    caller_reason: "furthest",
    processes: [
      {
        job_id: 31,
        job_title: "Backend Java",
        client_name: "PKO BP",
        column: "client_interview",
        stage_name: "Po Interview",
        sent_at: "2026-09-01T08:00:00Z",
        silent_since: "2026-09-09T08:00:00Z",
        silent_days: 11,
        owner_id: 1,
        owner_name: "Anna Kowalczyk",
      },
      {
        job_id: 32,
        job_title: "Java Developer",
        client_name: "Nordea",
        column: "cv_sent",
        stage_name: "Wysłany do Klienta",
        sent_at: "2026-09-04T08:00:00Z",
        silent_since: "2026-09-04T08:00:00Z",
        silent_days: 16,
        owner_id: 5,
        owner_name: "Tomasz Lewandowski",
      },
    ],
    last_contact_at: "2026-09-08T10:00:00Z",
    last_contact_by: "Anna Kowalczyk",
    last_contact_kind: "note",
    no_answer_count: 0,
    pending: null,
    ...over,
  };
}

function mockQueue(queue: Record<string, unknown>) {
  get.mockImplementation((url: string) => {
    if (url === "/api/board-tasks")
      return Promise.resolve({ data: { window_days: 14, cpro_to_send: [], cpro_sent: [], ...queue } });
    if (url === "/api/candidate-followups/candidates/21")
      return Promise.resolve({ data: { candidate_id: 21, followup: followupRow(), history: [] } });
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

  it("prepy przed rozmową u klienta: sama lista prepów wystarcza, żeby panel był widoczny", async () => {
    mockQueue({
      prep_attention: [
        {
          reason: "missing",
          prep_no: 1,
          candidate_id: 21,
          candidate_name: "Ewa Prep",
          job_id: 31,
          job_title: "Java Developer",
          interview_event_id: 501,
          interview_start: "2026-09-25T08:00:00Z",
          prep_event_id: null,
          owner_id: 1,
          urgent: true,
        },
        {
          reason: "unrecorded",
          prep_no: 2,
          candidate_id: 22,
          candidate_name: "Jan Nagranie",
          job_id: 32,
          job_title: "Tester",
          interview_event_id: 502,
          interview_start: "2026-09-26T12:30:00Z",
          prep_event_id: 77,
          owner_id: 1,
          urgent: false,
        },
      ],
    });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Prepy przed rozmową u klienta" });
    const items = within(section).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByRole("link", { name: "Ewa Prep" })).toHaveAttribute(
      "href",
      "/calendar?cycle=21-31",
    );
    expect(items[0]).toHaveTextContent("Java Developer · Prep 1");
    expect(items[0]).toHaveTextContent("brak prepu");
    expect(items[0]).toHaveTextContent("pilne");
    // 08:00 UTC = 10:00 w Warszawie (czas letni).
    expect(items[0]).toHaveTextContent("10:00");
    expect(items[1]).toHaveTextContent("Tester · Prep 2");
    expect(items[1]).toHaveTextContent("prep bez nagrania");
    expect(items[1]).not.toHaveTextContent("pilne");
  });

  it("pusta lista prepów nie dokłada sekcji", async () => {
    mockQueue({ cpro_sent: [row("cpro_sent")], prep_attention: [] });
    renderPanel();
    await screen.findByRole("region", { name: "Wysłane do Cpro" });
    expect(screen.queryByRole("region", { name: "Prepy przed rozmową u klienta" })).toBeNull();
  });

  it("follow-up z kandydatami: jedna pozycja na osobę, wszystkie jej procesy, zapis wyniku", async () => {
    mockQueue({
      followups: [followupRow()],
      followups_by_others: [
        followupRow({
          candidate_id: 44,
          candidate_name: "Marek Lis",
          caller_id: 9,
          caller_name: "Ewa Nowak",
          state: "scheduled",
          due_on: "2026-09-29",
        }),
      ],
    });
    post.mockResolvedValue({
      data: { candidate_id: 21, followup: followupRow({ state: "scheduled", due_on: "2026-10-08" }), history: [] },
    });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Follow-up z kandydatami" });
    const [item] = within(section).getAllByRole("listitem");
    expect(item).toHaveTextContent("Jan Wiśniewski");
    expect(item).toHaveTextContent("zaległy 2 dni");
    expect(item).toHaveTextContent("2 procesy");
    expect(item).toHaveTextContent("PKO BP · po rozmowie u klienta, 11 dni");
    expect(item).toHaveTextContent("Nordea · CV wysłane, 16 dni");
    expect(item).toHaveTextContent("Ostatni kontakt 08.09 (Anna K., notatka)");
    expect(section).toHaveTextContent("Z 1 Twoim kandydatem follow-up robi ktoś inny");
    expect(section).toHaveTextContent("Marek Lis: dzwoni Ewa N., termin 29.09");

    await userEvent.click(
      within(item).getByRole("button", { name: "Zapisz wynik telefonu: Jan Wiśniewski" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Czeka na klienta w 2 procesach")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText("Notatka (opcjonalnie)"), "Czeka, dostępny od 01.11.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/candidate-followups/candidates/21/outcome", {
        outcome: "connected",
        note: "Czeka, dostępny od 01.11.",
        callback_on: null,
        processes: {},
      }),
    );
    expect(showSuccess).toHaveBeenCalledWith("Zapisano. Następny follow-up: 08.10.");
  });

  it("„coś się zmieniło” wymaga opisu i wysyła decyzję per proces", async () => {
    mockQueue({ followups: [followupRow()] });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Follow-up z kandydatami" });
    await userEvent.click(
      within(section).getByRole("button", { name: "Zapisz wynik telefonu: Jan Wiśniewski" }),
    );
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByText("Czeka na klienta w 2 procesach");
    await userEvent.click(within(dialog).getByLabelText(/Rozmawialiśmy, coś się zmieniło/));
    const save = within(dialog).getByRole("button", { name: "Zapisz" });
    expect(save).toBeDisabled();
    await userEvent.selectOptions(within(dialog).getByLabelText("Proces Nordea"), "withdrawing");
    await userEvent.type(within(dialog).getByLabelText("Co się zmieniło?"), "Ma inną ofertę.");
    await userEvent.click(save);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/candidate-followups/candidates/21/outcome", {
        outcome: "changed",
        note: "Ma inną ofertę.",
        callback_on: null,
        processes: { 32: "withdrawing" },
      }),
    );
  });
});
