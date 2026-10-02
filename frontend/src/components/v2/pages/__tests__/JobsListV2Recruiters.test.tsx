/**
 * Lista rekrutacji po decyzjach z 02.10.2026: zakres „Moja kategoria”, filtry
 * „Priorytet” i „Data otwarcia”, kolumna „Rekruter” i plakietka priorytetu
 * przy tytule. Pozostałe filtry i wiersze pilnuje `JobsListV2QuickFilters`.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobsListV2 } from "@/components/v2/pages/JobsListV2";
import { useAuthStore } from "@/store/auth";
import { useUiStore } from "@/store/ui";

const getMock = vi.fn();
const quickCountsMock = vi.fn();

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
  },
  jobsApi: {
    quickCounts: (...args: unknown[]) => quickCountsMock(...args),
  },
  competenceCategoriesApi: {
    list: () => Promise.resolve([]),
  },
}));

// Adres przy montowaniu — czytany leniwie, więc test może go podmienić.
const navState = { search: "" };

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(navState.search),
}));

vi.mock("@/hooks/useCapability", () => ({
  useCapabilities: () => ({
    "job.create": false,
    "invite_link.create": false,
  }),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showToast: vi.fn(),
    showSuccess: vi.fn(),
    showError: vi.fn(),
    showActionToast: vi.fn(),
  }),
}));

vi.mock("@/components/v2/modals/GenerateInviteLinkV2", () => ({
  GenerateInviteLinkV2: () => null,
}));

vi.mock("@/components/v2/filters/UserMultiSelect", () => ({
  UserMultiSelect: () => null,
}));

vi.mock("@/components/v2/filters/ClientMultiSelect", () => ({
  ClientMultiSelect: () => null,
}));

vi.mock("@/components/v2/filters/CompetenceCategoryMultiSelect", () => ({
  CompetenceCategoryMultiSelect: () => null,
}));

vi.mock("@/components/v2/jobs/JobReadinessDock", () => ({
  JobReadinessDock: () => null,
}));

function signInAs(...roles: string[]) {
  useAuthStore.setState({
    user: { id: 7, name: "Test", email: "t@example.com", role: roles[0], roles } as never,
    hydrated: true,
  });
}

function jobRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 101,
    title: "Senior Java Developer",
    status: "published",
    headcount: 1,
    candidate_count: 0,
    ...overrides,
  };
}

function mockJobsResponse(items: ReturnType<typeof jobRow>[]) {
  getMock.mockResolvedValue({
    data: { items, total: items.length, page: 1, page_size: 20 },
  });
}

function mockQuickCounts(overrides: Record<string, unknown> = {}) {
  quickCountsMock.mockResolvedValue({
    data: {
      all: 4241,
      mine: 12,
      open: 318,
      request_stage: { searching: 210 },
      request_stage_mine: { searching: 7 },
      attention: { overdue: 4, nobody_working: 7, nobody_sent: 11 },
      attention_mine: { overdue: 1, nobody_working: 0, nobody_sent: 2 },
      ...overrides,
    },
  });
}

function renderJobs() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <JobsListV2 />
    </QueryClientProvider>,
  );
}

function jobsCalls() {
  return getMock.mock.calls.filter((call) => call[0] === "/api/jobs");
}

function latestParams(): Record<string, unknown> {
  const call = jobsCalls().at(-1);
  return (call?.[1] as { params?: Record<string, unknown> } | undefined)?.params ?? {};
}

const person = (user_id: number, name: string, extra: Record<string, unknown> = {}) => ({
  user_id,
  name,
  role: "recruiter",
  via: "owner",
  proposed: false,
  assigned_by_name: null,
  ...extra,
});

function setAddress(search: string) {
  navState.search = search;
  window.history.replaceState(null, "", search ? `/jobs?${search}` : "/jobs");
}

beforeEach(() => {
  signInAs("recruiter");
  getMock.mockReset();
  quickCountsMock.mockReset();
  useUiStore.setState({ jobsView: "list" });
  mockJobsResponse([jobRow()]);
  setAddress("");
});

describe("JobsListV2 — zakres „Moja kategoria”", () => {
  it("osoba z kategorią ma zakres na przełączniku, między „Moje” a „Otwarte”, z liczbą", async () => {
    mockQuickCounts({ my_category: 14 });
    renderJobs();
    const scope = within(await screen.findByRole("group", { name: "Zakres rekrutacji" }));
    await waitFor(() =>
      expect(scope.getByRole("button", { name: /Moja kategoria\s*14/ })).toBeInTheDocument(),
    );
    expect(scope.getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Moje12",
      "Moja kategoria14",
      "Otwarte318",
      "Wszystkie4241",
    ]);
  });

  it("osoba bez kategorii (`null` albo starszy backend bez pola) nie widzi zakresu", async () => {
    for (const counts of [{ my_category: null }, {}]) {
      mockQuickCounts(counts);
      const view = renderJobs();
      const scope = within(await screen.findByRole("group", { name: "Zakres rekrutacji" }));
      await waitFor(() => expect(scope.getByRole("button", { name: /Moje\s*12/ })).toBeInTheDocument());
      expect(scope.queryByRole("button", { name: /Moja kategoria/ })).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it("wysyła `my_category=true` SAMO (bez `mine` i `open_only`) i zapisuje `mycat=1`", async () => {
    mockQuickCounts({ my_category: 14 });
    const user = userEvent.setup();
    renderJobs();
    const scope = within(await screen.findByRole("group", { name: "Zakres rekrutacji" }));
    await user.click(await scope.findByRole("button", { name: /Moja kategoria/ }));

    await waitFor(() => expect(latestParams()).toMatchObject({ my_category: true, sort: "newest" }));
    expect(latestParams().mine).toBeUndefined();
    expect(latestParams().open_only).toBeUndefined();
    await waitFor(() => expect(window.location.search).toBe("?mycat=1"));
    expect(scope.getByRole("button", { name: /Moja kategoria/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("nie pokazuje liczb przy pigułkach stanu ani przy przełącznikach — serwer liczy tylko zakres", async () => {
    mockQuickCounts({ my_category: 14 });
    const user = userEvent.setup();
    renderJobs();
    const chips = within(await screen.findByRole("group", { name: "Stan requestu" }));
    await waitFor(() =>
      expect(chips.getByRole("button", { name: /Szukamy\s*7/ })).toBeInTheDocument(),
    );
    const scope = within(screen.getByRole("group", { name: "Zakres rekrutacji" }));
    await user.click(scope.getByRole("button", { name: /Moja kategoria/ }));

    await waitFor(() => expect(chips.getByRole("button", { name: "Szukamy" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Po terminie/ })).toHaveTextContent(/^Po terminie$/);
    expect(screen.getByRole("button", { name: /^Bez rekrutera/ })).toHaveTextContent(
      /^Bez rekrutera$/,
    );
  });

  it("`?mycat=1` u osoby z kategorią: lista czeka na liczniki i pyta raz, od razu o kategorię", async () => {
    setAddress("mycat=1");
    let releaseCounts: (value: unknown) => void = () => undefined;
    quickCountsMock.mockReturnValue(
      new Promise((resolve) => {
        releaseCounts = resolve;
      }),
    );
    renderJobs();
    await new Promise((r) => setTimeout(r, 30));
    expect(jobsCalls()).toHaveLength(0);

    releaseCounts({ data: { all: 10, mine: 1, open: 5, my_category: 3 } });
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ my_category: true });
    expect(latestParams().mine).toBeUndefined();
    expect(window.location.search).toBe("?mycat=1");
  });

  it("`?mycat=1` u osoby bez kategorii wraca do zakresu roli i znika z adresu", async () => {
    setAddress("mycat=1");
    mockQuickCounts({ my_category: null });
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    // Rekruter: zakres domyślny „Moje”.
    expect(latestParams()).toMatchObject({ mine: true, open_only: true, sort: "attention" });
    expect(latestParams().my_category).toBeUndefined();
    await waitFor(() => expect(window.location.search).toBe(""));
    const scope = within(screen.getByRole("group", { name: "Zakres rekrutacji" }));
    expect(scope.getByRole("button", { name: /Moje/ })).toHaveAttribute("aria-pressed", "true");
    // Nic jawnie nie ustawiono — nie ma czego czyścić.
    expect(screen.queryByRole("button", { name: /Wyczyść filtry/ })).not.toBeInTheDocument();
  });

  it("`?mycat=1`, gdy liczniki się nie wczytały: zakres roli zamiast pustej listy", async () => {
    setAddress("mycat=1");
    quickCountsMock.mockRejectedValue(new Error("boom"));
    signInAs("admin");
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ open_only: true });
    expect(latestParams().my_category).toBeUndefined();
  });

  it("pusty zakres mówi o kategorii, nie o pustej bazie", async () => {
    setAddress("mycat=1");
    mockQuickCounts({ my_category: 0 });
    mockJobsResponse([]);
    renderJobs();
    expect(
      await screen.findByText(/W Twojej kategorii nie ma teraz otwartych rekrutacji/),
    ).toBeInTheDocument();
  });
});

describe("JobsListV2 — filtr „Priorytet”", () => {
  beforeEach(() => mockQuickCounts());

  it("wybór poziomów wysyła `priority_level` i zapisuje `prio` w adresie", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: /^Priorytet/ }));
    await user.click(await screen.findByRole("checkbox", { name: "P1 Pilne" }));
    await waitFor(() => expect(latestParams()).toMatchObject({ priority_level: ["p1"] }));
    expect(screen.getByRole("button", { name: /^Priorytet: P1$/ })).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Przyjmujemy kandydatów" }));
    await waitFor(() =>
      expect(latestParams()).toMatchObject({ priority_level: ["p1", "accepting"] }),
    );
    await waitFor(() =>
      expect(new URLSearchParams(window.location.search).get("prio")).toBe("p1,accepting"),
    );
    // Nigdy pod starym kluczem `priority` (dawny filtr Priority Work).
    expect(new URLSearchParams(window.location.search).get("priority")).toBeNull();
    expect(screen.getByRole("button", { name: "Wyczyść filtry (1)" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Wyczyść: Priorytet" }));
    await waitFor(() => expect(latestParams().priority_level).toBeUndefined());
    await waitFor(() => expect(window.location.search).toBe(""));
  });

  it("`?prio=` z adresu idzie do API; śmieci i stary klucz `priority` — nie", async () => {
    setAddress("prio=accepting,p1,cokolwiek&priority=p2");
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ priority_level: ["p1", "accepting"] });
    await waitFor(() => {
      const params = new URLSearchParams(window.location.search);
      expect(params.get("prio")).toBe("p1,accepting");
      expect(params.get("priority")).toBeNull();
    });
    expect(screen.getByRole("button", { name: /^Priorytet: P1, Przyjmujemy$/ })).toBeInTheDocument();
  });
});

describe("JobsListV2 — filtr „Data otwarcia”", () => {
  beforeEach(() => mockQuickCounts());

  it("zakres z adresu idzie do API jako `opened_from` / `opened_to`", async () => {
    setAddress("op_from=2026-09-01&op_to=2026-09-30");
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ opened_from: "2026-09-01", opened_to: "2026-09-30" });
    expect(screen.getByRole("button", { name: "Wyczyść filtry (1)" })).toBeInTheDocument();
    // Wąski pasek (jsdom nie liczy szerokości): filtr siedzi w „Więcej filtrów”
    // i tamten przycisk go pokazuje.
    expect(
      screen.getByRole("button", { name: /Więcej filtrów: otwarta: 01\.09–30\.09/ }),
    ).toBeInTheDocument();
  });

  it("wpisane daty filtrują i trafiają do adresu; odwrócony zakres nie idzie do serwera", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: /Więcej filtrów/ }));
    fireEvent.change(await screen.findByLabelText("Data otwarcia od"), {
      target: { value: "2026-09-10" },
    });
    await waitFor(() => expect(latestParams()).toMatchObject({ opened_from: "2026-09-10" }));
    expect(latestParams().opened_to).toBeUndefined();
    await waitFor(() => expect(window.location.search).toBe("?op_from=2026-09-10"));

    // „Do” wcześniejsze niż „od”: serwer odpowiedziałby 422, więc nie pytamy.
    const callsBefore = jobsCalls().length;
    fireEvent.change(screen.getByLabelText("Data otwarcia do"), {
      target: { value: "2026-09-01" },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(/popraw zakres/);
    await waitFor(() => {
      expect(latestParams().opened_from).toBeUndefined();
      expect(latestParams().opened_to).toBeUndefined();
    });
    expect(jobsCalls().length).toBe(callsBefore + 1);
    expect(screen.getByRole("button", { name: /Więcej filtrów: otwarta: popraw zakres/ })).toBeInTheDocument();

    // Poprawka przywraca filtr.
    fireEvent.change(screen.getByLabelText("Data otwarcia do"), {
      target: { value: "2026-09-30" },
    });
    await waitFor(() =>
      expect(latestParams()).toMatchObject({ opened_from: "2026-09-10", opened_to: "2026-09-30" }),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("rok w trakcie wpisywania nie wywołuje zapytania (pole oddaje „0002-…”)", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    await user.click(screen.getByRole("button", { name: /Więcej filtrów/ }));
    fireEvent.change(await screen.findByLabelText("Data otwarcia od"), {
      target: { value: "0002-09-10" },
    });
    expect(await screen.findByText(/Wpisz pełną datę/)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 30));
    expect(jobsCalls()).toHaveLength(1);
    expect(window.location.search).toBe("");
  });
});

describe("JobsListV2 — kolumna „Rekruter” i priorytet w wierszu", () => {
  beforeEach(() => mockQuickCounts());

  it("jedna osoba, dwie osoby (+1), sama propozycja, nikt — każdy stan w swojej komórce", async () => {
    mockJobsResponse([
      jobRow({ id: 1, title: "Jedna osoba", recruiters: [person(3, "Anna Nowak")] }),
      jobRow({
        id: 2,
        title: "Dwie osoby",
        recruiters: [person(3, "Anna Nowak"), person(4, "Jan Kowalski", { via: "collaborator" })],
      }),
      jobRow({
        id: 3,
        title: "Sama propozycja",
        recruiters: [person(5, "Ewa Proponowana", { via: "assignment", proposed: true })],
      }),
      jobRow({ id: 4, title: "Nikt", recruiters: [] }),
    ]);
    renderJobs();
    await screen.findByText("Jedna osoba");
    const cellOf = (title: string) =>
      within(
        within(screen.getByText(title).closest("tr") as HTMLElement).getByTestId(
          "job-recruiter-cell",
        ),
      );

    expect(screen.getByRole("columnheader", { name: "Rekruter" })).toBeInTheDocument();

    // Komórka niesie dwie postaci naraz (wąska i szeroka tabela) — jsdom nie
    // liczy CSS, więc obie są w DOM i obie mają tę samą podpowiedź.
    const one = cellOf("Jedna osoba");
    const oneTitled = one.getAllByTitle("Rekruter: Anna Nowak");
    expect(oneTitled).toHaveLength(2);
    for (const el of oneTitled) expect(el).toHaveTextContent("Anna N.");
    expect(one.queryByText(/^\+/)).not.toBeInTheDocument();

    const two = cellOf("Dwie osoby");
    expect(two.getByText("+1")).toBeInTheDocument();
    expect(two.getAllByTitle("Rekruterzy: Anna Nowak, Jan Kowalski").length).toBeGreaterThan(0);

    const proposal = cellOf("Sama propozycja");
    expect(proposal.getAllByText("propozycja").length).toBeGreaterThan(0);
    expect(proposal.getAllByTitle("Propozycja automatu: Ewa Proponowana").length).toBeGreaterThan(0);
    // Propozycja to jeszcze nie praca, ale komórka jej nie przykrywa etykietą.
    expect(proposal.queryByTestId("job-no-recruiter")).not.toBeInTheDocument();

    const nobody = cellOf("Nikt");
    const pill = nobody.getByTestId("job-no-recruiter");
    expect(pill).toHaveTextContent("Bez rekrutera");
    expect(pill).toHaveClass("bg-warning-muted", "text-warning-muted-foreground");
    expect(screen.queryByText("Nieprzypisany")).not.toBeInTheDocument();
  });

  it("Delivery Lead stoi drobnym drukiem pod osobami — bez osobnej kolumny", async () => {
    mockJobsResponse([
      jobRow({
        id: 1,
        title: "Z Delivery Leadem",
        recruiters: [],
        delivery_lead_user: { id: 9, name: "Martyna Witkowska" },
      }),
      jobRow({ id: 2, title: "Bez Delivery Leada", recruiters: [person(3, "Anna Nowak")] }),
    ]);
    renderJobs();
    await screen.findByText("Z Delivery Leadem");
    const dl = screen.getByTestId("job-delivery-lead");
    expect(dl).toHaveTextContent("DL: Martyna W.");
    expect(dl).toHaveAttribute("title", "Delivery Lead: Martyna Witkowska");
    expect(screen.getAllByTestId("job-delivery-lead")).toHaveLength(1);
    expect(screen.queryByRole("columnheader", { name: /Delivery Lead/ })).not.toBeInTheDocument();
  });

  it("starszy backend bez `recruiters`: prowadzący i ręczni współpracownicy", async () => {
    mockJobsResponse([
      jobRow({
        primary_owner: { id: 3, name: "Anna Nowak" },
        collaborators: [
          { id: 4, name: "Jan Kowalski", source: "manual" },
          { id: 5, name: "Cała kategoria", source: "auto_cc" },
        ],
      }),
    ]);
    renderJobs();
    const cell = within(await screen.findByTestId("job-recruiter-cell"));
    expect(cell.getByText("+1")).toBeInTheDocument();
    expect(cell.getByTestId("job-recruiter-names")).toHaveTextContent("Anna N., Jan K.");
  });

  it("priorytet przy tytule: P1 i „Przyjmujemy” mają plakietkę, P2 — nie; bez osobnej kolumny", async () => {
    mockJobsResponse([
      jobRow({ id: 1, title: "Pilna", priority_level: "p1" }),
      jobRow({ id: 2, title: "Zwykła", priority_level: "p2" }),
      jobRow({ id: 3, title: "Otwarta na kandydatów", priority_level: "accepting" }),
      // Starszy backend: poziom z surowej kolumny `priority`.
      jobRow({ id: 4, title: "Pilna po staremu", priority: "urgent" }),
    ]);
    renderJobs();
    await screen.findByText("Pilna");
    const chipOf = (title: string) =>
      (screen.getByText(title).closest("td") as HTMLElement).querySelector("[data-priority]");

    expect(chipOf("Pilna")).toHaveAttribute("data-priority", "p1");
    expect(chipOf("Pilna")).toHaveAttribute("title", "P1 Pilne");
    expect(chipOf("Zwykła")).toBeNull();
    expect(chipOf("Otwarta na kandydatów")).toHaveAttribute("data-priority", "accepting");
    expect(chipOf("Pilna po staremu")).toHaveAttribute("data-priority", "p1");
    expect(screen.queryByRole("columnheader", { name: /Priorytet/ })).not.toBeInTheDocument();
  });
});
