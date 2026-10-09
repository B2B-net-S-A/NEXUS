import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();
const showInfo = vi.fn();

vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  };
  return { __esModule: true, default: client, api: client };
});
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError, showInfo }),
}));

import {
  NEW_JOB_LEADS_ROWS,
  NewJobLeadsSection,
  handoffWhen,
  leadState,
  participantsLabel,
} from "@/components/v2/dashboard/NewJobLeadsSection";
import {
  BOARD_TASKS_QUERY_KEY,
  type BoardTasksResponse,
  type NewJobLeadRow,
} from "@/lib/api/boardTasks";
import { REQUEST_BOARD_QUERY_KEY, type LoadPerson } from "@/lib/api/requestAllocation";
import { useAuthStore } from "@/store/auth";

function lead(over: Partial<NewJobLeadRow> = {}): NewJobLeadRow {
  return {
    job_id: 11,
    title: "Full Stack Java Developer",
    client_name: "Bank Północny",
    category_id: 2,
    category_name: "Development",
    category_slug: "software_development",
    participants: 5,
    priority_level: "p2",
    delivery_lead_name: "Anna Lis",
    handed_off_at: "2026-10-02T08:42:00Z",
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

const person = (over: Partial<LoadPerson> & Pick<LoadPerson, "user_id" | "name">): LoadPerson => ({
  count: 0,
  proposed: 0,
  leave_until: null,
  requests: [],
  ...over,
});

const LOAD: LoadPerson[] = [
  person({ user_id: 21, name: "Kinga Olcha", count: 4 }),
  person({ user_id: 7, name: "Marek Dąb", count: 2 }),
  person({ user_id: 23, name: "Julia Sosna", count: 0, leave_until: "2026-10-09" }),
  person({ user_id: 22, name: "Maja Cis", count: 0 }),
];

const BOARD = { mode: "auto", availability_known: true, groups: [], requests: [], load: LOAD, changes: [] };

function setUser(role: string, extra: Record<string, unknown> = {}) {
  useAuthStore.setState({ user: { id: 1, role, ...extra }, realUser: null } as never);
}

function renderSection(rows: NewJobLeadRow[], standalone = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData<BoardTasksResponse>(BOARD_TASKS_QUERY_KEY, {
    window_days: 14,
    cpro_to_send: [],
    cpro_sent: [],
    new_job_leads: rows,
  });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const view = render(
    <QueryClientProvider client={client}>
      <NewJobLeadsSection rows={rows} standalone={standalone} />
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

beforeEach(() => {
  vi.clearAllMocks();
  setUser("head_of_recruitment");
  get.mockResolvedValue({ data: BOARD });
  post.mockResolvedValue({ data: {} });
});

describe("participantsLabel — polska liczba mnoga", () => {
  it.each([
    [0, "0 uczestników"],
    [1, "1 uczestnik"],
    [2, "2 uczestnicy"],
    [4, "4 uczestnicy"],
    [5, "5 uczestników"],
    [12, "12 uczestników"],
    [14, "14 uczestników"],
    [22, "22 uczestnicy"],
  ])("%i → %s", (count, text) => {
    expect(participantsLabel(count)).toBe(text);
  });
});

describe("handoffWhen — kiedy przekazano do searchu", () => {
  const now = new Date("2026-10-02T12:00:00Z");

  it("dziś i wczoraj z godziną (czas warszawski), starsze w dniach", () => {
    // 08:42 UTC = 10:42 w Warszawie (czas letni).
    expect(handoffWhen("2026-10-02T08:42:00Z", now)).toBe("dziś, 10:42");
    expect(handoffWhen("2026-10-01T14:05:00Z", now)).toBe("wczoraj, 16:05");
    expect(handoffWhen("2026-09-29T08:00:00Z", now)).toBe("3 dni temu");
  });

  it("nieczytelna data nie wywraca wiersza", () => {
    expect(handoffWhen("", now)).toBe("");
    expect(handoffWhen("nie-data", now)).toBe("");
  });
});

describe("leadState — kto prowadzi i skąd", () => {
  it("prowadzący z automatu", () => {
    expect(leadState(lead())).toEqual({ name: "Marek Dąb", note: "automat", warning: false });
  });

  it("prowadzący wskazany ręcznie — z osobą, która wskazała, gdy ją znamy", () => {
    expect(leadState(lead({ lead_source: "manual", assigned_by_name: "Anna Lis" }))).toEqual({
      name: "Marek Dąb",
      note: "wskazany ręcznie · Anna Lis",
      warning: false,
    });
    expect(leadState(lead({ lead_source: "manual" })).note).toBe("wskazany ręcznie");
  });

  it("propozycja automatu wygrywa ze źródłem — to jeszcze nie przydział", () => {
    expect(leadState(lead({ proposed: true })).note).toBe(
      "propozycja automatu — czeka na akceptację",
    );
  });

  it("bez prowadzącego: automat przydziela, przyjmujemy kandydatów albo brak (ostrzeżenie)", () => {
    const none = { lead_user_id: null, lead_name: null, lead_role: null, lead_source: null };
    expect(leadState(lead({ ...none, pending_reason: "assigning" }))).toEqual({
      name: null,
      note: "Automat przydziela…",
      warning: false,
    });
    expect(leadState(lead({ ...none, pending_reason: "passive" }))).toEqual({
      name: null,
      note: "Przyjmujemy kandydatów — bez prowadzącego",
      warning: false,
    });
    for (const pending_reason of ["none", null] as const) {
      expect(leadState(lead({ ...none, pending_reason }))).toEqual({
        name: null,
        note: "Brak prowadzącego",
        warning: true,
      });
    }
  });

  it("prowadzący bez nazwiska i bez źródła nie zostawia pustego wiersza", () => {
    expect(leadState(lead({ lead_name: null, lead_source: null }))).toEqual({
      name: "#7",
      note: null,
      warning: false,
    });
  });
});

describe("NewJobLeadsSection — „Nowe rekrutacje — kto prowadzi”", () => {
  it("pusta lista nie renderuje nic", () => {
    const { container } = renderSection([]);
    expect(container).toBeEmptyDOMElement();
  });

  it("wiersz: link do rekrutacji, klient i czas przekazania, kategoria z uczestnikami, priorytet, prowadzący", () => {
    renderSection([lead({ priority_level: "p1", participants: 3 })]);
    const section = screen.getByRole("region", { name: "Nowe rekrutacje — kto prowadzi" });
    expect(section).toHaveTextContent(
      "Uczestnikami każdej rekrutacji są wszyscy z jej kategorii. Potwierdź prowadzącego albo go zmień — rekrutacja zniknie z listy.",
    );
    const row = within(rowOf("Full Stack Java Developer"));
    expect(row.getByRole("link", { name: "Full Stack Java Developer" })).toHaveAttribute(
      "href",
      "/jobs/11",
    );
    expect(row.getByTitle("P1 Pilne")).toBeInTheDocument();
    const meta = row.getByTestId("lead-request-meta");
    expect(meta).toHaveTextContent("Bank Północny");
    expect(meta).toHaveTextContent(/przekazano /);
    expect(meta).toHaveTextContent("DL: Anna L.");
    const category = row.getByTestId("lead-category");
    expect(within(category).getByTitle("Development")).toBeInTheDocument();
    expect(category).toHaveTextContent("3 uczestnicy");
    const who = row.getByTestId("lead-person");
    expect(who).toHaveTextContent("Marek Dąb");
    expect(who).toHaveTextContent("rekruter");
    expect(who).toHaveTextContent("automat");
    expect(row.getByRole("button", { name: "Zmień prowadzącego: Full Stack Java Developer" })).toBeEnabled();
  });

  it("stany prowadzącego: ręcznie, propozycja (bez „Zmień”), automat przydziela, bez prowadzącego", () => {
    const none = { lead_user_id: null, lead_name: null, lead_role: null, lead_source: null };
    renderSection([
      lead({ job_id: 1, title: "Ręczna", lead_source: "manual", assigned_by_name: "Anna Lis" }),
      lead({ job_id: 2, title: "Propozycja", proposed: true }),
      lead({ job_id: 3, title: "W przydziale", ...none, pending_reason: "assigning" }),
      lead({ job_id: 4, title: "Pasywna", ...none, pending_reason: "passive", priority_level: "accepting" }),
      lead({ job_id: 5, title: "Bez nikogo", ...none, pending_reason: "none", category_id: null, category_name: null, category_slug: null, participants: 0 }),
    ]);

    expect(within(rowOf("Ręczna")).getByTestId("lead-person")).toHaveTextContent(
      "wskazany ręcznie · Anna Lis",
    );

    const proposed = within(rowOf("Propozycja"));
    expect(proposed.getByTestId("lead-person")).toHaveTextContent(
      "propozycja automatu — czeka na akceptację",
    );
    // Propozycję rozstrzyga sekcja propozycji — tu nie ma przycisku.
    expect(proposed.queryByRole("button")).toBeNull();

    const assigning = within(rowOf("W przydziale"));
    expect(assigning.getByTestId("lead-person")).toHaveTextContent("Automat przydziela…");
    expect(assigning.getByRole("button", { name: "Wybierz prowadzącego: W przydziale" })).toBeInTheDocument();

    expect(within(rowOf("Pasywna")).getByTestId("lead-person")).toHaveTextContent(
      "Przyjmujemy kandydatów — bez prowadzącego",
    );

    const empty = within(rowOf("Bez nikogo"));
    expect(empty.getByText("Brak prowadzącego")).toHaveClass("text-warning");
    expect(empty.getByTestId("lead-category")).toHaveTextContent("bez kategorii");
    expect(empty.getByRole("button", { name: "Wybierz prowadzącego: Bez nikogo" })).toHaveTextContent(
      "Wybierz",
    );
  });

  it("rekrutacja nigdy nieprzekazana do searchu: komunikat zamiast prowadzącego, link „Przekaż do searchu”, data założenia", () => {
    const none = { lead_user_id: null, lead_name: null, lead_role: null, lead_source: null };
    expect(leadState(lead({ ...none, pending_reason: "not_handed_off" }))).toEqual({
      name: null,
      note: "Bez przekazania do searchu",
      warning: true,
    });
    renderSection([
      lead({
        job_id: 7,
        title: "Bez handoffu",
        ...none,
        pending_reason: "not_handed_off",
        handed_off_at: "2026-09-28T08:00:00Z",
      }),
    ]);
    const row = within(rowOf("Bez handoffu"));
    expect(row.getByTestId("lead-person")).toHaveTextContent("Bez przekazania do searchu");
    expect(row.getByRole("link", { name: "Przekaż do searchu: Bez handoffu" })).toHaveAttribute(
      "href",
      "/jobs/7",
    );
    const meta = row.getByTestId("lead-request-meta");
    expect(meta).toHaveTextContent("założona 28.09");
    expect(meta).not.toHaveTextContent("przekazano");
    // Prowadzącego nie wybiera się przed przekazaniem — tylko link.
    expect(row.queryByRole("button")).toBeNull();
  });

  it("lista informacyjna: sama liczba, bez plakietki zadania", () => {
    renderSection([lead(), lead({ job_id: 12, title: "Tester" })]);
    const section = screen.getByRole("region", { name: "Nowe rekrutacje — kto prowadzi" });
    const count = within(section).getByText("2");
    expect(count).toHaveClass("text-muted-foreground");
    expect(count).not.toHaveClass("text-primary");
  });

  it("najwyżej 6 wierszy i „Pokaż wszystkie (N)”", async () => {
    const rows = Array.from({ length: 8 }, (_, i) => lead({ job_id: 100 + i, title: `Rekrutacja ${i + 1}` }));
    renderSection(rows);
    const section = screen.getByRole("region", { name: "Nowe rekrutacje — kto prowadzi" });
    expect(within(section).getAllByRole("listitem")).toHaveLength(NEW_JOB_LEADS_ROWS);
    await userEvent.click(within(section).getByRole("button", { name: "Pokaż wszystkie (8)" }));
    expect(within(section).getAllByRole("listitem")).toHaveLength(8);
    expect(within(section).getByRole("button", { name: "Zwiń" })).toHaveAttribute("aria-expanded", "true");
  });

  describe("filtry", () => {
    // Osiem rekrutacji: trzech klientów, dwie kategorie i jedna bez kategorii,
    // dwóch Delivery Leadów, jedna bez prowadzącego.
    const many: NewJobLeadRow[] = [
      ...Array.from({ length: 5 }, (_, i) => lead({ job_id: 100 + i, title: `Java ${i}` })),
      lead({ job_id: 201, title: "Tester", client_name: "Ubezpieczenia Wzorcowe", category_id: 4, category_name: "QA", category_slug: "security_quality", delivery_lead_name: "Piotr Zieliński", lead_user_id: 21, lead_name: "Kinga Olcha", priority_level: "p1" }),
      lead({ job_id: 202, title: "Tester automatyzujący", client_name: "Ubezpieczenia Wzorcowe", category_id: 4, category_name: "QA", category_slug: "security_quality", delivery_lead_name: "Piotr Zieliński" }),
      lead({ job_id: 203, title: "Administrator sieci", client_name: "Energetyka Wzorcowa", category_id: null, category_name: null, category_slug: null, lead_user_id: null, lead_name: null, lead_role: null, lead_source: null, pending_reason: "none" }),
    ];

    const titles = () =>
      within(screen.getByRole("region", { name: /Nowe rekrutacje/ }))
        .getAllByRole("listitem")
        .map((item) => within(item).getAllByRole("link")[0].textContent);

    it("krótka lista nie ma paska filtrów", () => {
      renderSection(many.slice(0, NEW_JOB_LEADS_ROWS));
      expect(screen.queryByRole("group", { name: "Filtry listy" })).not.toBeInTheDocument();
    });

    it("klient zawęża listę; licznik mówi „N z M”, a „Wyczyść filtry” wraca do całości", async () => {
      renderSection(many);
      const filters = screen.getByRole("group", { name: "Filtry listy" });
      expect(within(filters).queryByRole("button", { name: "Wyczyść filtry" })).not.toBeInTheDocument();

      await userEvent.selectOptions(within(filters).getByRole("combobox", { name: "Klient" }), "Ubezpieczenia Wzorcowe");
      expect(titles()).toEqual(["Tester", "Tester automatyzujący"]);
      expect(screen.getByText("2 z 8")).toBeInTheDocument();
      // Dwa wiersze mieszczą się bez „Pokaż wszystkie”.
      expect(screen.queryByRole("button", { name: /Pokaż wszystkie/ })).not.toBeInTheDocument();

      await userEvent.click(within(filters).getByRole("button", { name: "Wyczyść filtry" }));
      expect(screen.getByRole("button", { name: "Pokaż wszystkie (8)" })).toBeInTheDocument();
    });

    it("kategoria ma krótką nazwę z plakietki i pozycję „Bez kategorii”; prowadzący — „Bez prowadzącego”", async () => {
      renderSection(many);
      const category = screen.getByRole("combobox", { name: "Kategoria" });
      expect(within(category).getAllByRole("option").map((o) => o.textContent)).toEqual([
        "Kategoria: wszystkie",
        "Dev",
        "QA",
        "Bez kategorii",
      ]);
      await userEvent.selectOptions(category, "QA");
      expect(titles()).toEqual(["Tester", "Tester automatyzujący"]);

      await userEvent.selectOptions(category, "");
      await userEvent.selectOptions(screen.getByRole("combobox", { name: "Prowadzący" }), "Bez prowadzącego");
      expect(titles()).toEqual(["Administrator sieci"]);
    });

    it("filtry łączą się; gdy nic nie pasuje — zdanie zamiast pustej ramki", async () => {
      renderSection(many);
      await userEvent.selectOptions(screen.getByRole("combobox", { name: "Delivery Lead" }), "Piotr Zieliński");
      await userEvent.selectOptions(screen.getByRole("combobox", { name: "Priorytet" }), "P1 Pilne");
      expect(titles()).toEqual(["Tester"]);

      await userEvent.selectOptions(screen.getByRole("combobox", { name: "Prowadzący" }), "Marek Dąb");
      expect(screen.getByRole("status")).toHaveTextContent("Żadna rekrutacja nie pasuje do ustawionych filtrów.");
      expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
      expect(screen.getByText("0 z 8")).toBeInTheDocument();
    });

    it("pole z jedną pozycją nie jest pokazywane; bez żadnego pola nie ma paska", () => {
      const same = Array.from({ length: 7 }, (_, i) => lead({ job_id: 300 + i, title: `Java ${i}` }));
      const { unmount } = renderSection(same);
      expect(screen.queryByRole("group", { name: "Filtry listy" })).not.toBeInTheDocument();
      unmount();

      renderSection([...same, lead({ job_id: 399, title: "Tester", client_name: "Ubezpieczenia Wzorcowe" })]);
      const filters = screen.getByRole("group", { name: "Filtry listy" });
      expect(within(filters).getAllByRole("combobox")).toHaveLength(1);
      expect(within(filters).getByRole("combobox", { name: "Klient" })).toBeInTheDocument();
    });

    it("po potwierdzeniu ostatniej rekrutacji wybranego klienta filtr przestaje działać", async () => {
      const { client, rerender } = renderSection(many);
      await userEvent.selectOptions(screen.getByRole("combobox", { name: "Klient" }), "Energetyka Wzorcowa");
      expect(titles()).toEqual(["Administrator sieci"]);

      const left = many.filter((row) => row.job_id !== 203);
      rerender(
        <QueryClientProvider client={client}>
          <NewJobLeadsSection rows={left} />
        </QueryClientProvider>,
      );
      expect(screen.getByRole("combobox", { name: "Klient" })).toHaveValue("");
      expect(screen.getByRole("button", { name: "Pokaż wszystkie (7)" })).toBeInTheDocument();
    });
  });

  it("„Zmień”: osoby wczytane dopiero po otwarciu; wybór zapisuje prowadzącego przez /owner", async () => {
    const user = userEvent.setup();
    const { client, invalidated } = renderSection([lead()]);
    // Pulpitu nie czytamy, dopóki nikt nie otworzy listy.
    expect(get).not.toHaveBeenCalled();

    await user.click(
      screen.getByRole("button", { name: "Zmień prowadzącego: Full Stack Java Developer" }),
    );
    expect(get).toHaveBeenCalledWith("/api/request-board");
    const options = await screen.findAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "Marek Dąbprowadzi teraz2 requesty",
      "Maja Cis0 requestów",
      "Kinga Olcha4 requesty",
      "Julia Sosnaurlop do 09.100 requestów",
    ]);
    // Obecnego prowadzącego nie da się „zmienić na niego samego”.
    expect(options[0]).toHaveAttribute("aria-disabled", "true");
    expect(
      screen.getByText("Wybrana osoba zostaje rekruterem prowadzącym od razu."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("option", { name: /Maja Cis/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/jobs/11/owner", { user_id: 22 }));
    await waitFor(() =>
      expect(showSuccess).toHaveBeenCalledWith("Maja Cis prowadzi „Full Stack Java Developer”."),
    );
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    // Wybór osoby to decyzja — wiersz schodzi z listy od razu.
    const cached = client.getQueryData<BoardTasksResponse>(BOARD_TASKS_QUERY_KEY);
    expect(cached?.new_job_leads).toEqual([]);
    // „Czeka na Ciebie”, pulpit „Requesty i obłożenie” i rekrutacja.
    expect(invalidated()).toEqual(
      expect.arrayContaining([
        JSON.stringify(BOARD_TASKS_QUERY_KEY),
        JSON.stringify(REQUEST_BOARD_QUERY_KEY),
        JSON.stringify(["job", 11]),
      ]),
    );
  });

  it("„Potwierdź” zapisuje zgodę na prowadzącego i zdejmuje wiersz z listy", async () => {
    const user = userEvent.setup();
    const { client, invalidated } = renderSection([lead(), lead({ job_id: 12, title: "Tester" })]);
    await user.click(
      screen.getByRole("button", { name: "Potwierdź prowadzącego: Full Stack Java Developer" }),
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/request-board/jobs/11/lead-confirmation", {
        lead_user_id: lead().lead_user_id,
      }),
    );
    await waitFor(() =>
      expect(showSuccess).toHaveBeenCalledWith(
        "Potwierdzono: Marek Dąb prowadzi „Full Stack Java Developer”.",
      ),
    );
    const cached = client.getQueryData<BoardTasksResponse>(BOARD_TASKS_QUERY_KEY);
    expect(cached?.new_job_leads?.map((row) => row.job_id)).toEqual([12]);
    expect(invalidated()).toContain(JSON.stringify(BOARD_TASKS_QUERY_KEY));
  });

  it("bez prowadzącego i przy propozycji automatu nie ma „Potwierdź”", () => {
    const none = { lead_user_id: null, lead_name: null, lead_role: null, lead_source: null };
    renderSection([
      lead({ ...none, pending_reason: "none" }),
      lead({ job_id: 12, title: "Propozycja", proposed: true }),
    ]);
    expect(screen.queryByRole("button", { name: /^Potwierdź/ })).toBeNull();
  });

  it("„Wybierz” przy rekrutacji bez prowadzącego woła ten sam endpoint", async () => {
    const user = userEvent.setup();
    renderSection([
      lead({ lead_user_id: null, lead_name: null, lead_role: null, lead_source: null, pending_reason: "none" }),
    ]);
    await user.click(
      screen.getByRole("button", { name: "Wybierz prowadzącego: Full Stack Java Developer" }),
    );
    const options = await screen.findAllByRole("option");
    // Nikt nie prowadzi — żadna osoba nie jest wyróżniona ani zablokowana.
    expect(options.map((o) => o.getAttribute("aria-disabled"))).not.toContain("true");
    await user.click(screen.getByRole("option", { name: /Kinga Olcha/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/jobs/11/owner", { user_id: 21 }));
  });

  it("odmowa zapisu: komunikat serwera, bez sukcesu, lista i tak się odświeża", async () => {
    const user = userEvent.setup();
    post.mockRejectedValue({
      response: { status: 409, data: { detail: "Rekrutacja jest zamknięta." } },
    });
    const { invalidated } = renderSection([lead()]);
    await user.click(
      screen.getByRole("button", { name: "Zmień prowadzącego: Full Stack Java Developer" }),
    );
    await user.click(await screen.findByRole("option", { name: /Maja Cis/ }));
    await waitFor(() => expect(showError).toHaveBeenCalledWith("Rekrutacja jest zamknięta."));
    expect(showSuccess).not.toHaveBeenCalled();
    expect(invalidated()).toContain(JSON.stringify(BOARD_TASKS_QUERY_KEY));
  });

  it("awaria odczytu osób to komunikat z „Ponów”, a nie „Brak osób”", async () => {
    const user = userEvent.setup();
    get.mockRejectedValueOnce(new Error("boom"));
    renderSection([lead()]);
    await user.click(
      screen.getByRole("button", { name: "Zmień prowadzącego: Full Stack Java Developer" }),
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nie udało się pobrać listy osób.");
    expect(screen.queryByText("Brak osób.")).not.toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: /Ponów/ }));
    expect(await screen.findAllByRole("option")).toHaveLength(4);
  });

  it("w „podglądzie jako” lista jest, przycisków nie ma", () => {
    useAuthStore.setState({
      user: { id: 2, role: "head_of_recruitment" },
      realUser: { id: 1, role: "admin" },
    } as never);
    renderSection([lead()]);
    const section = screen.getByRole("region", { name: "Nowe rekrutacje — kto prowadzi" });
    expect(within(section).queryByRole("button")).toBeNull();
    expect(section).toHaveTextContent("W tym widoku nie możesz zmieniać rekrutera prowadzącego.");
  });

  it("samodzielnie (panel bez zadań) stoi we własnej ramce, w panelu — na całą szerokość", () => {
    const standalone = renderSection([lead()], true);
    const alone = screen.getByRole("region", { name: "Nowe rekrutacje — kto prowadzi" });
    expect(alone).not.toHaveClass("lg:col-span-3");
    expect(alone.parentElement).toHaveClass("rounded-xl", "border", "bg-card");
    standalone.unmount();

    renderSection([lead()]);
    expect(screen.getByRole("region", { name: "Nowe rekrutacje — kto prowadzi" })).toHaveClass(
      "lg:col-span-3",
    );
  });
});
