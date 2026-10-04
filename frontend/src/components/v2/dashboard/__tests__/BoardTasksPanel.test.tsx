import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();
const showInfo = vi.fn();

vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: (...a: unknown[]) => put(...a),
  };
  return { __esModule: true, default: client, api: client };
});
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError, showInfo }),
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

function proposalRow(over: Record<string, unknown> = {}) {
  return {
    job_id: 41,
    title: "Full Stack Java Developer",
    client_name: "Bank Północny",
    category_id: 2,
    category_name: "Development",
    category_slug: "software_development",
    delivery_lead_name: "Anna Lis",
    priority_level: "p1",
    deadline: null,
    sent: 0,
    user_id: 7,
    user_name: "Marek Dąb",
    role: "recruiter",
    fit: "first",
    load: 2,
    leave_until: null,
    base_matches: null,
    proposed_at: since,
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

  it("awaria odczytu kolejki → komunikat z „Spróbuj ponownie”, nie pustka (R8-N14-1)", async () => {
    let calls = 0;
    get.mockImplementation((url: string) => {
      if (url === "/api/board-tasks") {
        calls += 1;
        return calls === 1
          ? Promise.reject(new Error("boom"))
          : Promise.resolve({ data: { window_days: 14, cpro_to_send: [], cpro_sent: [row("cpro_sent")] } });
      }
      return Promise.resolve({ data: [] });
    });
    renderPanel();
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/Nie udało się wczytać listy „Czeka na Ciebie”/)).toBeTruthy();
    await userEvent.click(within(alert).getByRole("button", { name: /Spróbuj ponownie/ }));
    expect(await screen.findByRole("region", { name: "Wysłane do Cpro" })).toBeTruthy();
  });

  it("admin / DL Nordei widzi przełącznik osoby od Cpro także przy pustej kolejce", async () => {
    mockQueue({ can_set_cpro_sender: true });
    renderPanel();
    const bar = await screen.findByRole("region", { name: "Osoba od Cpro" });
    expect(await within(bar).findByText("Do Cpro wrzuca: Kinga Sordyl")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Czeka na Ciebie" })).toBeNull();
  });

  // PR 6 (04.10.2026): to, na co czekasz u innych, stoi osobno od Twojego ruchu.
  it("„Wysłane do Cpro” stoi w grupie „U innych”, oddzielonej od „Twój ruch”", async () => {
    mockQueue({ cpro_sent: [row("cpro_sent")] });
    renderPanel();
    const others = await screen.findByRole("group", { name: "U innych" });
    expect(within(others).getByRole("region", { name: "Wysłane do Cpro" })).toBeTruthy();
    expect(screen.getByText("Twój ruch")).toBeTruthy();
  });

  it("CV, które wróciło do poprawy, jest w „Twój ruch”, nie w „U innych”", async () => {
    mockQueue({
      cpro_sent: [row("cpro_sent")],
      cv_in_transit: {
        returned: [],
        in_review: [],
        sent: [],
        returned_total: 1,
        in_review_total: 0,
        sent_total: 0,
      },
    });
    renderPanel();
    const others = await screen.findByRole("group", { name: "U innych" });
    expect(within(others).queryByText("Twoje CV w drodze")).toBeNull();
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
        row("dl_review", {
          candidate_name: "Ola Przegląd",
          client_name: "PKO BP",
          qc_status: "failed",
          qc_blocking_failed: 2,
          card_status: "partial",
          card_missing: 3,
        }),
        row("dl_review", { stage_id: 18, candidate_id: 28, candidate_name: "Bez Karty", card_status: null }),
      ],
    });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Czeka na Twój przegląd (DL)" });
    expect(within(section).getByText("Java Developer · PKO BP")).toBeTruthy();
    expect(within(section).getByText("QC: 2 do poprawy")).toBeTruthy();
    // Stan karty rekomendacji — ile pól brakuje, zanim DL otworzy przegląd.
    expect(within(section).getByText("Karta: brakuje 3")).toBeTruthy();
    expect(within(section).getByText("Bez karty")).toBeTruthy();
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

  it("propozycje automatu: same wystarczą, żeby panel był widoczny, i stoją pierwsze", async () => {
    mockQueue({
      can_decide_proposals: true,
      allocation_leave_known: false,
      allocation_proposals: [
        proposalRow(),
        proposalRow({ job_id: 42, title: "Tester", user_id: 8, user_name: "Ewa Kalina" }),
      ],
    });
    renderPanel();
    const panel = await screen.findByRole("region", { name: "Czeka na Ciebie" });
    // Kotwica z dzwonka „Propozycje przydziału do akceptacji”.
    expect(panel).toHaveAttribute("id", "czeka-na-ciebie");
    const section = within(panel).getByRole("region", { name: "Propozycje automatu do akceptacji" });
    expect(within(section).getAllByRole("listitem")).toHaveLength(2);
    expect(within(section).getByRole("link", { name: "Full Stack Java Developer" })).toHaveAttribute(
      "href",
      "/jobs/41",
    );
    expect(within(section).getByRole("note")).toHaveTextContent(
      "Brak danych o urlopach — propozycje ich nie uwzględniają.",
    );
    // Na całą szerokość panelu, jak follow-upy.
    expect(section).toHaveClass("lg:col-span-3");
  });

  it("propozycje stoją przed pozostałymi listami, a baneru o urlopach nie ma, gdy dane są świeże", async () => {
    mockQueue({
      can_decide_proposals: true,
      allocation_leave_known: true,
      allocation_proposals: [proposalRow()],
      followups: [followupRow()],
      cpro_sent: [row("cpro_sent")],
    });
    renderPanel();
    const panel = await screen.findByRole("region", { name: "Czeka na Ciebie" });
    const sections = within(panel)
      .getAllByRole("region")
      .map((region) => region.getAttribute("aria-label"));
    expect(sections).toEqual([
      "Propozycje automatu do akceptacji",
      "Follow-up z kandydatami",
      "Wysłane do Cpro",
    ]);
    expect(within(panel).queryByRole("note")).toBeNull();
  });

  it("osoba, która nie decyduje o propozycjach, sekcji nie widzi — nawet gdyby wiersze przyszły", async () => {
    mockQueue({
      can_decide_proposals: false,
      allocation_proposals: [proposalRow()],
      cpro_sent: [row("cpro_sent")],
    });
    renderPanel();
    await screen.findByRole("region", { name: "Wysłane do Cpro" });
    expect(screen.queryByRole("region", { name: "Propozycje automatu do akceptacji" })).toBeNull();
  });

  it("same propozycje bez prawa decyzji nie tworzą pustego panelu", async () => {
    mockQueue({ can_decide_proposals: false, allocation_proposals: [proposalRow()] });
    const { container } = renderPanel();
    await waitFor(() => expect(get).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("akceptacja z panelu: zapis, komunikat i wiersz znika bez czekania na odświeżenie", async () => {
    let accepted = false;
    get.mockImplementation((url: string) => {
      if (url === "/api/board-tasks")
        return Promise.resolve({
          data: {
            window_days: 14,
            cpro_to_send: [],
            cpro_sent: [],
            can_decide_proposals: true,
            allocation_leave_known: true,
            allocation_proposals: accepted
              ? [proposalRow({ job_id: 42, title: "Tester", user_id: 8, user_name: "Ewa Kalina" })]
              : [
                  proposalRow(),
                  proposalRow({ job_id: 42, title: "Tester", user_id: 8, user_name: "Ewa Kalina" }),
                ],
          },
        });
      return Promise.resolve({ data: [] });
    });
    post.mockImplementation(() => {
      accepted = true;
      return Promise.resolve({ data: { decision: "accept", assigned_user_id: 7 } });
    });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Propozycje automatu do akceptacji" });
    await userEvent.click(
      within(section).getByRole("button", { name: "Akceptuj: Marek Dąb — Full Stack Java Developer" }),
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/request-board/jobs/41/proposals/7", { decision: "accept" }),
    );
    await waitFor(() =>
      expect(showSuccess).toHaveBeenCalledWith("Marek Dąb pracuje nad „Full Stack Java Developer”."),
    );
    await waitFor(() => expect(within(section).getAllByRole("listitem")).toHaveLength(1));
    expect(within(section).queryByRole("link", { name: "Full Stack Java Developer" })).toBeNull();
    expect(within(section).getByRole("link", { name: "Tester" })).toBeTruthy();
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

function leadRow(over: Record<string, unknown> = {}) {
  return {
    job_id: 51,
    title: "Analityk biznesowy",
    client_name: "Bank Kappa",
    category_id: 5,
    category_name: "Management & Delivery (PM & BA)",
    category_slug: "management_delivery",
    participants: 4,
    priority_level: "p2",
    delivery_lead_name: "Anna Lis",
    handed_off_at: since,
    lead_user_id: 7,
    lead_name: "Marek Dąb",
    lead_role: "recruiter",
    lead_source: "auto",
    assigned_by_name: null,
    proposed: false,
    pending_reason: null,
    ...over,
  };
}

describe("BoardTasksPanel — „Nowe rekrutacje — kto prowadzi”", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: { id: 1, role: "head_of_recruitment" }, realUser: null } as never);
    post.mockResolvedValue({ data: {} });
  });

  it("same rekrutacje z prowadzącymi: lista jest widoczna, ale nic nie „czeka”", async () => {
    mockQueue({ new_job_leads: [leadRow()] });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Nowe rekrutacje — kto prowadzi" });
    expect(within(section).getByRole("link", { name: "Analityk biznesowy" })).toHaveAttribute(
      "href",
      "/jobs/51",
    );
    expect(within(section).getByTestId("lead-category")).toHaveTextContent("4 uczestnicy");
    expect(within(section).getByTestId("lead-person")).toHaveTextContent("Marek Dąb");
    // Lista informacyjna nie robi z pulpitu „Czeka na Ciebie”.
    expect(screen.queryByRole("region", { name: "Czeka na Ciebie" })).toBeNull();
    expect(screen.queryByText("Czeka na Ciebie")).toBeNull();
  });

  it("obok zadań stoi w panelu zaraz po propozycjach automatu i nie zmienia ich liczników", async () => {
    mockQueue({
      can_decide_proposals: true,
      allocation_leave_known: true,
      allocation_proposals: [proposalRow()],
      new_job_leads: [leadRow(), leadRow({ job_id: 52, title: "Tester" })],
      cpro_sent: [row("cpro_sent")],
    });
    renderPanel();
    const panel = await screen.findByRole("region", { name: "Czeka na Ciebie" });
    const sections = within(panel)
      .getAllByRole("region")
      .map((region) => region.getAttribute("aria-label"));
    expect(sections).toEqual([
      "Propozycje automatu do akceptacji",
      "Nowe rekrutacje — kto prowadzi",
      "Wysłane do Cpro",
    ]);
    const proposals = within(panel).getByRole("region", { name: "Propozycje automatu do akceptacji" });
    expect(within(proposals).getAllByRole("listitem")).toHaveLength(1);
    const sent = within(panel).getByRole("region", { name: "Wysłane do Cpro" });
    expect(within(sent).getByText("1")).toHaveClass("text-primary");
  });

  it("„Zmień” z pulpitu zapisuje prowadzącego przez /owner", async () => {
    get.mockImplementation((url: string) => {
      if (url === "/api/board-tasks")
        return Promise.resolve({
          data: { window_days: 14, cpro_to_send: [], cpro_sent: [], new_job_leads: [leadRow()] },
        });
      if (url === "/api/request-board")
        return Promise.resolve({
          data: {
            mode: "auto",
            availability_known: true,
            groups: [],
            requests: [],
            changes: [],
            load: [
              { user_id: 7, name: "Marek Dąb", count: 3, proposed: 0, leave_until: null, requests: [] },
              { user_id: 9, name: "Ewa Kalina", count: 1, proposed: 0, leave_until: null, requests: [] },
            ],
          },
        });
      return Promise.resolve({ data: [] });
    });
    renderPanel();
    const section = await screen.findByRole("region", { name: "Nowe rekrutacje — kto prowadzi" });
    await userEvent.click(
      within(section).getByRole("button", { name: "Zmień prowadzącego: Analityk biznesowy" }),
    );
    await userEvent.click(await screen.findByRole("option", { name: /Ewa Kalina/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/jobs/51/owner", { user_id: 9 }));
    await waitFor(() =>
      expect(showSuccess).toHaveBeenCalledWith("Ewa Kalina prowadzi „Analityk biznesowy”."),
    );
  });

  it.each([
    ["pole nieobecne (starszy serwer)", {}],
    ["pusta lista (osoba, która nie nadzoruje przydziału)", { new_job_leads: [] }],
  ])("sekcji nie ma: %s", async (_name, queue) => {
    useAuthStore.setState({ user: { id: 1, role: "recruiter" }, realUser: null } as never);
    mockQueue({ ...queue, cpro_sent: [row("cpro_sent")] });
    renderPanel();
    await screen.findByRole("region", { name: "Wysłane do Cpro" });
    expect(screen.queryByRole("region", { name: "Nowe rekrutacje — kto prowadzi" })).toBeNull();
  });

  it("pusta lista bez innych zadań nie zostawia pustej ramki", async () => {
    mockQueue({ new_job_leads: [] });
    const { container } = renderPanel();
    await waitFor(() => expect(get).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});

function transitRow(kind: string, over: Record<string, unknown> = {}) {
  return {
    kind,
    stage_id: 41,
    candidate_id: 51,
    candidate_name: "Adam Wrona",
    job_id: 61,
    job_title: "Java Developer",
    job_working_title: "Java · Spring",
    client_name: "Bank Kappa",
    since,
    actor_name: null,
    holder_name: null,
    reason: null,
    ...over,
  };
}

function transit(over: Record<string, unknown[]> = {}) {
  const lists = { returned: [], in_review: [], sent: [], ...over };
  return {
    ...lists,
    returned_total: lists.returned.length,
    in_review_total: lists.in_review.length,
    sent_total: lists.sent.length,
    returned_window_days: 14,
    sent_window_days: 7,
  };
}

describe("BoardTasksPanel — „Twoje CV w drodze”", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: { id: 1, role: "recruiter" } } as never);
  });

  it("nic nie wróciło i panel jest pusty → wąski pasek z liczbami, „Pokaż” rozwija listę", async () => {
    mockQueue({
      cv_in_transit: transit({
        in_review: [transitRow("in_review", { holder_name: "Marta Kowalczyk" })],
        sent: [
          transitRow("sent", {
            stage_id: 42,
            candidate_id: 52,
            candidate_name: "Anna Sroka",
            actor_name: "Jan Dąb",
          }),
        ],
      }),
    });
    renderPanel();
    const bar = await screen.findByRole("region", { name: "Twoje CV w drodze" });
    expect(within(bar).getByText(/W przeglądzie: 1 · Wysłane do klienta: 1 · nic nie wróciło/)).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Czeka na Ciebie" })).toBeNull();
    expect(within(bar).queryByText("Adam Wrona")).toBeNull();

    await userEvent.click(within(bar).getByRole("button", { name: "Pokaż" }));
    const list = await screen.findByRole("region", { name: "Twoje CV w drodze" });
    expect(within(list).getByText("W przeglądzie · 1")).toBeTruthy();
    expect(within(list).getByText("Przegląda: Marta Kowalczyk")).toBeTruthy();
    expect(within(list).getByText("Wysłane przez: Jan Dąb")).toBeTruthy();
    const link = within(list).getByRole("link", { name: "Adam Wrona" });
    expect(link.getAttribute("href")).toBe("/jobs/61?candidate=51");
  });

  it("nikt nie ma CV w drodze → pasek mówi, co tu będzie (każdy ma listę domyślnie)", async () => {
    mockQueue({ cv_in_transit: transit() });
    renderPanel();
    const bar = await screen.findByRole("region", { name: "Twoje CV w drodze" });
    expect(within(bar).getByText(/Nie masz teraz CV w drodze/)).toBeTruthy();
    expect(within(bar).queryByRole("button", { name: "Pokaż" })).toBeNull();
  });

  it("coś wróciło → panel „Czeka na Ciebie” z plakietką, powodem i licznikiem zwrotów", async () => {
    mockQueue({
      cv_in_transit: transit({
        returned: [
          transitRow("rejected_by_dl", { reason: "stawka ponad budżet", actor_name: "Marta Kowalczyk" }),
          transitRow("sent_back", {
            stage_id: 43,
            candidate_id: 53,
            candidate_name: "Julia Bąk",
            actor_name: "Jan Dąb",
            remark: "Dopisz Spring Boot do ostatniego projektu",
          }),
        ],
        in_review: [transitRow("in_review", { stage_id: 44, candidate_id: 54, candidate_name: "Tomasz Żak" })],
      }),
    });
    renderPanel();
    const panel = await screen.findByRole("region", { name: "Czeka na Ciebie" });
    const section = within(panel).getByRole("region", { name: "Twoje CV w drodze" });
    expect(within(section).getByText("Odrzucone przez DL")).toBeTruthy();
    expect(within(section).getByText("stawka ponad budżet")).toBeTruthy();
    expect(within(section).getByText("Cofnięte do poprawy")).toBeTruthy();
    expect(within(section).getByText("Jan Dąb")).toBeTruthy();
    expect(within(section).getByText("Uwaga: Dopisz Spring Boot do ostatniego projektu")).toBeTruthy();
    // Licznik przy nagłówku = tyle wróciło; reszta jest informacją pod „Pokaż”.
    expect(within(section).getByText("2")).toBeTruthy();
    expect(within(section).queryByText("Tomasz Żak")).toBeNull();
    expect(within(section).getByText(/W przeglądzie: 1 · Wysłane do klienta: 0/)).toBeTruthy();
  });

  it("lista usunięta z pulpitu (`null`) → nic się nie renderuje, jak przed zmianą", async () => {
    mockQueue({ cv_in_transit: null });
    const { container } = renderPanel();
    await waitFor(() => expect(get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("„Usuń z pulpitu” zapisuje wybór na koncie i mówi, jak listę przywrócić", async () => {
    mockQueue({ cv_in_transit: transit() });
    put.mockResolvedValue({
      data: { tiles: [], version: 0, dropped_tiles: [], hidden_panels: ["cv_in_transit"] },
    });
    renderPanel();
    const bar = await screen.findByRole("region", { name: "Twoje CV w drodze" });
    await userEvent.click(within(bar).getByRole("button", { name: "Menu listy Twoje CV w drodze" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Usuń z pulpitu" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/users/me/dashboard/panels/cv_in_transit", { hidden: true }),
    );
    await waitFor(() =>
      expect(showSuccess).toHaveBeenCalledWith("Usunięto z pulpitu. Przywrócisz w „Dodaj kafelek”."),
    );
  });
});

function pendingRow(over: Record<string, unknown> = {}) {
  return {
    job_id: 71,
    title: "Analityk danych",
    client_name: "Bank Kappa",
    kind: "legacy_draft",
    created_at: new Date(Date.now() - 12 * 86_400_000).toISOString(),
    delivery_lead_name: "Anna Lis",
    missing: ["Budżet PLN/h", "Tryb pracy"],
    ...over,
  };
}

describe("BoardTasksPanel — „Rekrutacje do dokończenia albo zamknięcia”", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ user: { id: 1, role: "delivery_lead" }, realUser: null } as never);
    post.mockResolvedValue({ data: {} });
  });

  it("wiersze z tytułem, klientem, stanem, brakami i trzema linkami", async () => {
    mockQueue({
      pending_jobs: {
        autoclose_on: null,
        items: [
          pendingRow(),
          pendingRow({
            job_id: 72,
            title: "Tester",
            client_name: null,
            kind: "published_not_handed_off",
            missing: ["a", "b", "c", "d", "e"],
          }),
        ],
      },
    });
    renderPanel();
    const section = await screen.findByRole("region", {
      name: "Rekrutacje do dokończenia albo zamknięcia",
    });
    expect(within(section).getByRole("heading", { level: 3 })).toHaveTextContent(
      "Rekrutacje do dokończenia albo zamknięcia (2)",
    );
    const [draft, published] = within(section).getAllByRole("listitem");
    expect(draft).toHaveTextContent("Analityk danych · Bank Kappa");
    expect(within(draft).getByTestId("pending-job-meta")).toHaveTextContent(
      "Szkic od 12 dni · brakuje: Budżet PLN/h · Tryb pracy · DL: Anna Lis",
    );
    expect(within(draft).getByRole("link", { name: "Dokończ: Analityk danych" })).toHaveAttribute(
      "href",
      "/jobs/71?reopen=1",
    );
    expect(within(draft).getByRole("link", { name: "Uzupełnij: Analityk danych" })).toHaveAttribute(
      "href",
      "/jobs/71?tab=champion&mode=edit",
    );
    expect(within(draft).getByRole("link", { name: "Zamknij: Analityk danych" })).toHaveAttribute(
      "href",
      "/jobs/71?win=order&wintab=close",
    );
    expect(within(published).getByTestId("pending-job-meta")).toHaveTextContent(
      "W pracy bez przekazania · brakuje: a · b · c · i 2 więcej",
    );
    // Bez ostrzeżenia, gdy automat zamknięcia nie jest zaplanowany.
    expect(within(section).queryByTestId("pending-autoclose")).toBeNull();
    // Zaległość, nie zadanie: nie robi z pulpitu „Czeka na Ciebie”.
    expect(screen.queryByRole("region", { name: "Czeka na Ciebie" })).toBeNull();
  });

  it("zaplanowane zamknięcie szkiców: ostrzeżenie z datą DD.MM i odliczanie w wierszu", async () => {
    mockQueue({
      pending_jobs: { autoclose_on: "2099-03-07", items: [pendingRow()] },
    });
    renderPanel();
    const section = await screen.findByRole("region", {
      name: "Rekrutacje do dokończenia albo zamknięcia",
    });
    expect(within(section).getByTestId("pending-autoclose")).toHaveTextContent(
      "Od 07.03 system zamknie szkice, których nikt nie dokończył. Dane zostają, rekrutację da się otworzyć ponownie.",
    );
    expect(within(section).getByTestId("pending-job-meta")).toHaveTextContent(/zamknięcie za \d+ dni/);
  });

  it("obok zadań stoi w panelu i nie zmienia liczników innych list", async () => {
    mockQueue({
      cpro_sent: [row("cpro_sent")],
      pending_jobs: { autoclose_on: null, items: [pendingRow(), pendingRow({ job_id: 73 })] },
    });
    renderPanel();
    const panel = await screen.findByRole("region", { name: "Czeka na Ciebie" });
    const sections = within(panel)
      .getAllByRole("region")
      .map((region) => region.getAttribute("aria-label"));
    expect(sections).toEqual(["Rekrutacje do dokończenia albo zamknięcia", "Wysłane do Cpro"]);
    const sent = within(panel).getByRole("region", { name: "Wysłane do Cpro" });
    expect(within(sent).getByText("1")).toHaveClass("text-primary");
  });

  it("niedokończone formularze: jedna linia z linkiem do /jobs/new i nazwami (do trzech)", async () => {
    mockQueue({
      pending_jobs: null,
      unfinished_forms: [
        { id: 1, label: "Java Developer", client_name: "Bank Kappa", updated_at: since },
        { id: 2, label: "Tester", client_name: null, updated_at: since },
      ],
    });
    renderPanel();
    const section = await screen.findByRole("region", {
      name: "Niedokończone formularze nowej rekrutacji",
    });
    const line = within(section).getByTestId("unfinished-forms");
    expect(within(line).getByRole("link", { name: "Masz 2 niedokończone formularze nowej rekrutacji" })).toHaveAttribute(
      "href",
      "/jobs/new",
    );
    expect(line).toHaveTextContent("Java Developer · Bank Kappa, Tester");
  });

  it("więcej niż trzy formularze: sama liczba, bez wyliczania", async () => {
    mockQueue({
      unfinished_forms: [1, 2, 3, 4, 5].map((id) => ({
        id,
        label: `Formularz ${id}`,
        client_name: null,
        updated_at: since,
      })),
    });
    renderPanel();
    const line = await screen.findByTestId("unfinished-forms");
    expect(line).toHaveTextContent("Masz 5 niedokończonych formularzy nowej rekrutacji");
    expect(line).not.toHaveTextContent("Formularz 1");
  });

  it.each([
    ["pola nieobecne (starszy serwer)", {}],
    ["`null` i pusta lista", { pending_jobs: null, unfinished_forms: [] }],
    ["puste listy", { pending_jobs: { autoclose_on: "2099-03-07", items: [] }, unfinished_forms: null }],
  ])("bez rekrutacji do dokończenia nic się nie renderuje: %s", async (_name, queue) => {
    mockQueue(queue);
    const { container } = renderPanel();
    await waitFor(() => expect(get).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
