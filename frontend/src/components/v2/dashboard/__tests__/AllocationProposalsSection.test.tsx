import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();
const showInfo = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError, showInfo }),
}));

import {
  AllocationProposalsSection,
  MAX_BULK_ACCEPT,
  bulkAcceptMessage,
  proposalReasons,
  replacementOptions,
} from "@/components/v2/dashboard/AllocationProposalsSection";
import { BOARD_TASKS_QUERY_KEY, type AllocationProposalRow } from "@/lib/api/boardTasks";
import { REQUEST_BOARD_QUERY_KEY, type LoadPerson } from "@/lib/api/requestAllocation";
import { useAuthStore } from "@/store/auth";

function proposal(over: Partial<AllocationProposalRow> = {}): AllocationProposalRow {
  return {
    job_id: 11,
    title: "Full Stack Java Developer",
    client_name: "Bank Północny",
    category_id: 2,
    category_name: "Development",
    category_slug: "software_development",
    delivery_lead_name: "Anna Lis",
    priority_level: "p1",
    deadline: "2026-10-10",
    sent: 0,
    user_id: 7,
    user_name: "Marek Dąb",
    fit: "first",
    load: 2,
    leave_until: null,
    base_matches: null,
    proposed_at: "2026-10-02T06:30:00Z",
    ...over,
  };
}

const ROWS: AllocationProposalRow[] = [
  proposal(),
  proposal({
    job_id: 12,
    title: "Administrator chmury",
    client_name: "Fundusz Publiczny",
    category_name: "Infra & Operations & Security / Data & AI",
    category_slug: "infrastructure_operations",
    delivery_lead_name: null,
    priority_level: "p2",
    deadline: null,
    sent: 1,
    user_id: 8,
    user_name: "Ewa Kalina",
    fit: "second",
    load: 0,
    base_matches: 22,
  }),
  proposal({
    job_id: 13,
    title: "Tester automatyzujący",
    category_name: "QA",
    category_slug: "security_quality",
    priority_level: "accepting",
    user_id: 9,
    user_name: "Tomasz Jawor",
    fit: "other",
    load: 5,
    leave_until: "2026-10-09",
    // Liczby pasujących w bazie nie pokazujemy — próg „sourcer” zniknął (02.10.2026).
    base_matches: 40,
  }),
];

const person = (over: Partial<LoadPerson> & Pick<LoadPerson, "user_id" | "name">): LoadPerson => ({
  count: 0,
  proposed: 0,
  leave_until: null,
  requests: [],
  ...over,
});

const LOAD: LoadPerson[] = [
  person({ user_id: 21, name: "Kinga Olcha", count: 4 }),
  person({ user_id: 7, name: "Marek Dąb", count: 2, proposed: 1 }),
  person({ user_id: 23, name: "Julia Sosna", count: 0, leave_until: "2026-10-09" }),
  person({ user_id: 22, name: "Maja Cis", count: 0, proposed: 1 }),
];

const BOARD = { mode: "shadow", availability_known: true, groups: [], requests: [], load: LOAD, changes: [] };

function setUser(role: string, extra: Record<string, unknown> = {}) {
  useAuthStore.setState({ user: { id: 1, role, ...extra }, realUser: null } as never);
}

function renderSection(rows: AllocationProposalRow[] = ROWS, leaveKnown = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const view = render(
    <QueryClientProvider client={client}>
      <AllocationProposalsSection rows={rows} leaveKnown={leaveKnown} />
    </QueryClientProvider>,
  );
  const invalidated = () => invalidate.mock.calls.map((call) => JSON.stringify(call[0]?.queryKey));
  return { ...view, client, invalidated };
}

function rowOf(title: string): HTMLElement {
  const item = screen.getByRole("link", { name: title }).closest("li");
  if (!item) throw new Error(`brak wiersza: ${title}`);
  return item;
}

describe("proposalReasons — dlaczego automat proponuje tę osobę", () => {
  const texts = (over: Partial<AllocationProposalRow>) => proposalReasons(proposal(over)).map((r) => r.text);

  it("dopasowanie do kategorii", () => {
    expect(texts({ fit: "first" })[0]).toBe("1. priorytet w kategorii");
    expect(texts({ fit: "second" })[0]).toBe("2. priorytet w kategorii");
    expect(texts({ fit: "other" })[0]).toBe("spoza kategorii");
    // Osoba spoza kategorii to fakt do sprawdzenia przed akceptacją.
    expect(proposalReasons(proposal({ fit: "other" }))[0].notable).toBe(true);
    expect(proposalReasons(proposal({ fit: "first" }))[0].notable).toBe(false);
  });

  it("obłożenie w poprawnej polszczyźnie", () => {
    expect(texts({ load: 0 })[1]).toBe("bez requestów");
    expect(texts({ load: 1 })[1]).toBe("ma 1 request");
    expect(texts({ load: 3 })[1]).toBe("ma 3 requesty");
    expect(texts({ load: 5 })[1]).toBe("ma 5 requestów");
    expect(texts({ load: 12 })[1]).toBe("ma 12 requestów");
    expect(texts({ load: 22 })[1]).toBe("ma 22 requesty");
  });

  it("urlop jest powodem; liczba pasujących w bazie już nie (02.10.2026)", () => {
    expect(texts({ leave_until: "2026-10-09" })).toEqual([
      "1. priorytet w kategorii",
      "ma 2 requesty",
      "urlop do 09.10",
    ]);
    // Próg „od N pasujących w bazie → sourcer” zniknął razem z podziałem ról,
    // więc liczba niczego już nie tłumaczy.
    expect(texts({ base_matches: 22 }).join(" ")).not.toMatch(/w bazie/);
    expect(texts({ base_matches: null }).join(" ")).not.toMatch(/w bazie/);
  });
});

describe("replacementOptions i bulkAcceptMessage", () => {
  it("proponowana osoba na górze, potem od najmniej obłożonej, urlop na końcu", () => {
    expect(replacementOptions(LOAD, 7, "").map((p) => p.name)).toEqual([
      "Marek Dąb",
      "Maja Cis",
      "Kinga Olcha",
      "Julia Sosna",
    ]);
    // Szukanie bez polskich znaków i wielkości liter.
    expect(replacementOptions(LOAD, 7, "dab").map((p) => p.name)).toEqual(["Marek Dąb"]);
    expect(replacementOptions(LOAD, 7, "xyz")).toEqual([]);
  });

  it("„Zaakceptowano N z M” i co z resztą", () => {
    expect(bulkAcceptMessage(4, 4)).toBe("Zaakceptowano 4 z 4.");
    expect(bulkAcceptMessage(3, 4)).toBe("Zaakceptowano 3 z 4. Jedna propozycja była już nieaktualna.");
    expect(bulkAcceptMessage(1, 3)).toBe("Zaakceptowano 1 z 3. 2 propozycje były już nieaktualne.");
    expect(bulkAcceptMessage(0, 5)).toBe("Zaakceptowano 0 z 5. 5 propozycji było już nieaktualnych.");
  });
});

describe("AllocationProposalsSection — propozycje automatu do akceptacji", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setUser("head_of_recruitment");
    post.mockResolvedValue({ data: { decision: "accept", assigned_user_id: 7 } });
    get.mockResolvedValue({ data: BOARD });
  });

  it("bez propozycji sekcji nie ma", () => {
    const { container } = renderSection([]);
    expect(container).toBeEmptyDOMElement();
  });

  it("wiersz: request z linkiem, klient, priorytet, kategoria, Delivery Lead, termin, wysłani i osoba z powodami", () => {
    renderSection();
    const section = screen.getByRole("region", { name: "Propozycje automatu do akceptacji" });
    expect(within(section).getByRole("heading", { name: "Propozycje automatu do akceptacji" })).toBeInTheDocument();
    expect(within(section).getAllByRole("listitem")).toHaveLength(3);
    expect(within(section).getByRole("button", { name: "Akceptuj wszystkie (3)" })).toBeEnabled();

    const java = within(rowOf("Full Stack Java Developer"));
    expect(java.getByRole("link", { name: "Full Stack Java Developer" })).toHaveAttribute("href", "/jobs/11");
    expect(java.getByTitle("P1 Pilne")).toBeInTheDocument();
    expect(java.getByTestId("proposal-request-meta")).toHaveTextContent(
      "Bank Północny · Dev · DL: Anna L. · termin 10.10 · wysłani 0",
    );
    // Krótka nazwa kategorii, pełna w podpowiedzi.
    expect(java.getByText("Dev")).toHaveAttribute("title", "Development");
    expect(java.getByText("Marek Dąb")).toBeInTheDocument();
    // Bez dopisku roli przy osobie — każda proponowana osoba to rekruter.
    expect(java.queryByText("rekruter")).not.toBeInTheDocument();
    expect(java.getByTestId("proposal-reasons")).toHaveTextContent("1. priorytet w kategorii · ma 2 requesty");

    const cloud = within(rowOf("Administrator chmury"));
    // Bez Delivery Leada i terminu: brak pozycji albo „bez terminu”, nie puste „DL:”.
    expect(cloud.getByTestId("proposal-request-meta")).toHaveTextContent(
      "Fundusz Publiczny · Infra · bez terminu · wysłani 1",
    );
    expect(cloud.queryByTitle(/P2/)).not.toBeInTheDocument();
    expect(cloud.getByTestId("proposal-reasons")).toHaveTextContent(
      "2. priorytet w kategorii · bez requestów",
    );
    expect(cloud.getByTestId("proposal-reasons")).not.toHaveTextContent("w bazie");

    const tester = within(rowOf("Tester automatyzujący"));
    expect(tester.getByTestId("proposal-reasons")).toHaveTextContent(
      "spoza kategorii · ma 5 requestów · urlop do 09.10",
    );
    expect(tester.getByText("urlop do 09.10")).toHaveClass("text-warning");
    expect(tester.getByText("spoza kategorii")).toHaveClass("text-warning");
  });

  it("baner o braku danych o urlopach — tylko gdy serwer mówi, że ich nie ma", () => {
    const { unmount } = renderSection(ROWS, true);
    expect(screen.queryByText(/Brak danych o urlopach/)).not.toBeInTheDocument();
    unmount();
    renderSection(ROWS, false);
    expect(screen.getByRole("note")).toHaveTextContent(
      "Brak danych o urlopach — propozycje ich nie uwzględniają.",
    );
  });

  it("„Akceptuj” zapisuje decyzję, blokuje wiersz na czas zapisu i odświeża obsadę", async () => {
    const user = userEvent.setup();
    let resolve: (value: unknown) => void = () => undefined;
    post.mockReturnValue(new Promise((r) => (resolve = r)));
    const { invalidated } = renderSection();
    const java = within(rowOf("Full Stack Java Developer"));

    await user.click(java.getByRole("button", { name: "Akceptuj: Marek Dąb — Full Stack Java Developer" }));
    expect(post).toHaveBeenCalledWith("/api/request-board/jobs/11/proposals/7", { decision: "accept" });
    // W trakcie zapisu: ten wiersz zablokowany, pozostałe nie; zbiorcza akceptacja czeka.
    expect(java.getByRole("button", { name: /Akceptuj: Marek Dąb/ })).toBeDisabled();
    expect(java.getByRole("button", { name: "Zmień osobę: Full Stack Java Developer" })).toBeDisabled();
    expect(java.getByRole("button", { name: /Odrzuć: Marek Dąb/ })).toBeDisabled();
    expect(
      within(rowOf("Administrator chmury")).getByRole("button", { name: /Akceptuj: Ewa Kalina/ }),
    ).toBeEnabled();
    expect(screen.getByRole("button", { name: "Akceptuj wszystkie (3)" })).toBeDisabled();
    expect(showSuccess).not.toHaveBeenCalled();

    await act(async () => resolve({ data: { decision: "accept", assigned_user_id: 7 } }));
    expect(showSuccess).toHaveBeenCalledWith("Marek Dąb pracuje nad „Full Stack Java Developer”.");
    expect(post).toHaveBeenCalledTimes(1);
    // Rekrutacja, lista, liczniki, pulpit i „Czeka na Ciebie”.
    expect(invalidated()).toEqual(
      expect.arrayContaining([
        JSON.stringify(["job", 11]),
        JSON.stringify(["jobs-v2"]),
        JSON.stringify(REQUEST_BOARD_QUERY_KEY),
        JSON.stringify(BOARD_TASKS_QUERY_KEY),
      ]),
    );
    expect(java.getByRole("button", { name: /Akceptuj: Marek Dąb/ })).toBeEnabled();
  });

  it("rozstrzygnięta propozycja znika z listy „Czeka na Ciebie” od razu", async () => {
    const user = userEvent.setup();
    const { client } = renderSection();
    client.setQueryData(BOARD_TASKS_QUERY_KEY, {
      window_days: 14,
      cpro_to_send: [],
      cpro_sent: [],
      allocation_proposals: ROWS,
    });
    await user.click(screen.getByRole("button", { name: /Akceptuj: Marek Dąb/ }));
    await waitFor(() => expect(showSuccess).toHaveBeenCalled());
    const cached = client.getQueryData<{ allocation_proposals: AllocationProposalRow[] }>(BOARD_TASKS_QUERY_KEY);
    expect(cached?.allocation_proposals.map((row) => row.job_id)).toEqual([12, 13]);
  });

  it("„Odrzuć” wysyła odrzucenie i mówi, co zrobi automat", async () => {
    const user = userEvent.setup();
    post.mockResolvedValue({ data: { decision: "reject", assigned_user_id: null } });
    renderSection();
    await user.click(screen.getByRole("button", { name: "Odrzuć: Ewa Kalina — Administrator chmury" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/request-board/jobs/12/proposals/8", { decision: "reject" }),
    );
    await waitFor(() =>
      expect(showInfo).toHaveBeenCalledWith(
        "Propozycja odrzucona. Automat nie zaproponuje już tej osoby do tego requestu.",
      ),
    );
    expect(showError).not.toHaveBeenCalled();
  });

  it("„Zmień”: lista osób z obłożeniem wczytana dopiero po otwarciu; wybór przypisuje inną osobę", async () => {
    const user = userEvent.setup();
    post.mockResolvedValue({ data: { decision: "replace", assigned_user_id: 22 } });
    renderSection();
    // Pulpitu nie czytamy, dopóki nikt nie otworzy listy.
    expect(get).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Zmień osobę: Full Stack Java Developer" }));
    expect(get).toHaveBeenCalledWith("/api/request-board");
    const options = await screen.findAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "Marek Dąbpropozycja automatu2 requesty+ 1 do akceptacji",
      "Maja Cis0 requestów+ 1 do akceptacji",
      "Kinga Olcha4 requesty",
      "Julia Sosnaurlop do 09.100 requestów",
    ]);
    // Proponowanej osoby nie da się „zmienić na nią samą”.
    expect(options[0]).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByText("Wybrana osoba jest przypisana od razu.")).toBeInTheDocument();

    await user.click(screen.getByRole("option", { name: /Maja Cis/ }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/request-board/jobs/11/proposals/7", {
        decision: "replace",
        replacement_user_id: 22,
      }),
    );
    await waitFor(() =>
      expect(showSuccess).toHaveBeenCalledWith(
        "Maja Cis pracuje nad „Full Stack Java Developer” zamiast propozycji automatu.",
      ),
    );
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("„Zmień”: awaria odczytu osób to komunikat z „Ponów”, a nie „Brak osób”", async () => {
    const user = userEvent.setup();
    get.mockRejectedValueOnce(new Error("boom"));
    renderSection();
    await user.click(screen.getByRole("button", { name: "Zmień osobę: Full Stack Java Developer" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nie udało się pobrać listy osób.");
    expect(screen.queryByText("Brak osób.")).not.toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: "Ponów" }));
    expect(await screen.findByRole("option", { name: /Kinga Olcha/ })).toBeInTheDocument();
  });

  it("409: propozycja nieaktualna → komunikat serwera i odświeżenie listy", async () => {
    const user = userEvent.setup();
    post.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: "Ta propozycja jest już nieaktualna — request ma obsadę." },
      },
    });
    const { invalidated } = renderSection();
    await user.click(screen.getByRole("button", { name: /Akceptuj: Marek Dąb/ }));
    await waitFor(() =>
      expect(showError).toHaveBeenCalledWith("Ta propozycja jest już nieaktualna — request ma obsadę."),
    );
    expect(showSuccess).not.toHaveBeenCalled();
    expect(invalidated()).toContain(JSON.stringify(BOARD_TASKS_QUERY_KEY));
    // Wiersz nie zostaje zablokowany po odmowie.
    expect(screen.getByRole("button", { name: /Akceptuj: Marek Dąb/ })).toBeEnabled();
  });

  it("„Akceptuj wszystkie”: jedno żądanie, „Zaakceptowano N z M” i informacja o nieaktualnych", async () => {
    const user = userEvent.setup();
    let resolve: (value: unknown) => void = () => undefined;
    post.mockReturnValue(new Promise((r) => (resolve = r)));
    const { invalidated } = renderSection();

    await user.click(screen.getByRole("button", { name: "Akceptuj wszystkie (3)" }));
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith("/api/request-board/proposals/accept", {
      items: [
        { job_id: 11, user_id: 7 },
        { job_id: 12, user_id: 8 },
        { job_id: 13, user_id: 9 },
      ],
    });
    // Czekamy na serwer: nic nie ogłaszamy i niczego nie da się kliknąć.
    expect(showSuccess).not.toHaveBeenCalled();
    expect(showInfo).not.toHaveBeenCalled();
    for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();

    await act(async () =>
      resolve({
        data: {
          results: [
            { job_id: 11, user_id: 7, status: "accepted" },
            { job_id: 12, user_id: 8, status: "gone" },
            { job_id: 13, user_id: 9, status: "accepted" },
          ],
        },
      }),
    );
    expect(showInfo).toHaveBeenCalledWith("Zaakceptowano 2 z 3. Jedna propozycja była już nieaktualna.");
    expect(showSuccess).not.toHaveBeenCalled();
    // Zbiorcza decyzja dotyczy wielu rekrutacji — odświeża każdą wczytaną.
    expect(invalidated()).toEqual(
      expect.arrayContaining([JSON.stringify(["job"]), JSON.stringify(BOARD_TASKS_QUERY_KEY)]),
    );
  });

  it("„Akceptuj wszystkie”: komplet to sukces; awaria to błąd, nie „zaakceptowano”", async () => {
    const user = userEvent.setup();
    post.mockResolvedValueOnce({
      data: { results: ROWS.map((row) => ({ job_id: row.job_id, user_id: row.user_id, status: "accepted" })) },
    });
    renderSection();
    await user.click(screen.getByRole("button", { name: "Akceptuj wszystkie (3)" }));
    await waitFor(() => expect(showSuccess).toHaveBeenCalledWith("Zaakceptowano 3 z 3."));

    post.mockRejectedValueOnce({ response: { status: 500, data: {} } });
    await user.click(screen.getByRole("button", { name: "Akceptuj wszystkie (3)" }));
    await waitFor(() => expect(showError).toHaveBeenCalledWith("Nie udało się zaakceptować propozycji."));
    expect(showSuccess).toHaveBeenCalledTimes(1);
  });

  it("ponad 100 propozycji idzie w paczkach po 100 (limit jednego żądania)", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: MAX_BULK_ACCEPT + 5 }, (_, i) =>
      proposal({ job_id: 1000 + i, user_id: 2000 + i, title: `Request ${i}` }),
    );
    post.mockImplementation((_url: string, body: { items: { job_id: number; user_id: number }[] }) =>
      Promise.resolve({ data: { results: body.items.map((item) => ({ ...item, status: "accepted" })) } }),
    );
    renderSection(many);
    await user.click(screen.getByRole("button", { name: `Akceptuj wszystkie (${many.length})` }));
    await waitFor(() => expect(showSuccess).toHaveBeenCalledWith(`Zaakceptowano ${many.length} z ${many.length}.`));
    expect(post.mock.calls.map((call) => (call[1] as { items: unknown[] }).items.length)).toEqual([100, 5]);
    // 105 wierszy z przyciskami: wyszukanie po roli trwa w jsdom kilka sekund
    // na obciążonej maszynie — domyślne 5 s dawało losowy timeout.
  }, 30_000);

  it("przy jednej propozycji nie ma „Akceptuj wszystkie” — to byłby ten sam przycisk co w wierszu", () => {
    renderSection([ROWS[0]]);
    expect(screen.queryByRole("button", { name: /Akceptuj wszystkie/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Akceptuj: Marek Dąb/ })).toBeInTheDocument();
  });

  it("w „podglądzie jako” (zapis zablokowany) propozycje są tylko do odczytu", () => {
    useAuthStore.setState({
      user: { id: 2, role: "head_of_recruitment" },
      realUser: { id: 1, role: "admin" },
    } as never);
    renderSection();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText(/W tym widoku nie możesz podejmować decyzji o propozycjach\./)).toBeInTheDocument();
  });
});
