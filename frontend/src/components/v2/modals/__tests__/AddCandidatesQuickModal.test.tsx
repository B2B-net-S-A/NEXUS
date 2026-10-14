import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  search: vi.fn(),
  add: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
  send: vi.fn(),
}));

vi.mock("@/lib/candidate-search-api", () => ({
  candidateSearchApi: { search: mocks.search },
  proposalsBulkApi: { add: mocks.add },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

// Debounce bez zegara — zapytanie idzie od razu.
vi.mock("@/lib/use-debounced-value", () => ({
  useDebouncedValue: (value: string) => value,
}));

vi.mock("@/hooks/usePipelineMoveCore", () => ({
  usePipelineMoveCore: () => ({ send: mocks.send, dialogs: null }),
}));

vi.mock("@/components/v2/candidate-profile/CandidateMergeDialog", () => ({
  CandidateMergeDialog: ({
    candidate,
    initialDuplicateId,
  }: {
    candidate: { id: number };
    initialDuplicateId?: number | null;
  }) => (
    <div data-testid="merge-dialog">
      zostaje {candidate.id}, duplikat {initialDuplicateId}
    </div>
  ),
}));

import { AddCandidatesQuickModal } from "@/components/v2/modals/AddCandidatesQuickModal";
import { useAuthStore, type User } from "@/store/auth";

const NDA = {
  reason_code: "client_nda",
  reason: "Konflikt: NDA z klientem",
  assignment_allowed: true,
  visibility: "warn",
  severity: "warning",
  secondary: [],
};
const VETO = {
  reason_code: "rejected_by_hiring_manager",
  reason: "Hiring manager tej rekrutacji już odrzucił tego kandydata po rozmowie",
  assignment_allowed: false,
  visibility: "warn",
  severity: "hard",
  secondary: [],
};

function item(id: number, eligibility: unknown = null) {
  return {
    id,
    name: "Kandydat",
    lastname: `Nr${id}`,
    location: null,
    source: null,
    competence_category: null,
    is_champion: false,
    eligibility,
  };
}

function renderModal() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <AddCandidatesQuickModal open onClose={vi.fn()} jobId={9} jobTitle="Java" />
    </QueryClientProvider>,
  );
}

describe("AddCandidatesQuickModal — eligibility", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.search.mockResolvedValue({
      items: [item(1, NDA), item(2, VETO), item(3)],
      total: 3,
    });
    mocks.add.mockResolvedValue({
      added: [1, 3],
      skipped: [],
      warnings: [{ candidate_id: 1, reason: "client_nda" }],
      total_added: 2,
      total_skipped: 0,
    });
  });

  it("shows a warning chip for a client conflict and lets the row be selected", async () => {
    renderModal();
    const chip = await screen.findByTestId("add-candidate-eligibility-1");
    expect(chip).toHaveTextContent("Konflikt: NDA z klientem");
    expect(chip.className).toContain("warning");
    expect(screen.getByTestId("add-candidate-row-1")).toBeEnabled();
    expect(mocks.search).toHaveBeenCalledWith(
      expect.objectContaining({ exclude_in_job_id: 9 }),
    );
  });

  it("searches names literally via the shared v2 text rule", async () => {
    renderModal();
    await screen.findByTestId("add-candidate-row-1");
    fireEvent.change(screen.getByPlaceholderText("Imię i nazwisko, telefon albo e-mail…"), {
      target: { value: "TestPipelineD" },
    });
    await waitFor(() =>
      expect(mocks.search).toHaveBeenLastCalledWith(
        expect.objectContaining({
          q: "TestPipelineD",
          semantics_version: 2,
          text_mode: "auto",
        }),
      ),
    );
  });

  it("a hiring-manager veto disables the row with the reason as title", async () => {
    renderModal();
    const row = await screen.findByTestId("add-candidate-row-2");
    expect(row).toBeDisabled();
    expect(row).toHaveAttribute("title", VETO.reason);
    expect(screen.getByTestId("add-candidate-eligibility-2").className).toContain("destructive");
  });

  it("'Zaznacz wszystkich' skips vetoed candidates and adds the rest", async () => {
    renderModal();
    await screen.findByTestId("add-candidate-row-1");
    fireEvent.click(screen.getByRole("button", { name: "Zaznacz wszystkich" }));
    expect(screen.getByText("Zaznaczono 2 kandydatów")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Odznacz wszystkich" })).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("add-candidates-confirm"));
    await waitFor(() => expect(mocks.add).toHaveBeenCalledTimes(1));
    const [jobId, payload] = mocks.add.mock.calls[0];
    expect(jobId).toBe(9);
    expect([...payload.candidate_ids].sort()).toEqual([1, 3]);
  });

  it("pokazuje znacznik „Pracuje u nas”, a po zaznaczeniu ramkę — bez blokady", async () => {
    const working = {
      phase: "working",
      source: "contract",
      elsewhere: true,
      clients: [
        {
          client_id: 4,
          client_name: "Bank Przykładowy",
          contract_id: 40,
          phase: "working",
          order_end_date: "2026-12-31",
          delivery_lead_name: "Karol Wzorcowy",
        },
      ],
    };
    const atThisClient = {
      reason_code: "client_current_employment",
      reason: "Kandydat obecnie pracuje u tego klienta",
      assignment_allowed: true,
      visibility: "warn",
      severity: "warning",
      secondary: [],
    };
    mocks.search.mockResolvedValue({
      items: [
        { ...item(1), employment_marker: working },
        {
          ...item(2, atThisClient),
          employment_marker: { ...working, elsewhere: false },
        },
        item(3),
      ],
      total: 3,
    });
    renderModal();

    const row = await screen.findByTestId("add-candidate-row-1");
    expect(row).toHaveTextContent("Pracuje u nas · Bank Przykładowy · do 31.12.2026");
    expect(row).toBeEnabled();
    // Klient tej rekrutacji: jeden znacznik zamiast znacznika i plakietki.
    expect(screen.getByTestId("add-candidate-row-2")).toHaveTextContent("Pracuje u tego klienta");
    expect(screen.queryByTestId("add-candidate-eligibility-2")).toBeNull();
    expect(screen.queryByRole("note")).toBeNull();

    fireEvent.click(row);
    const notice = screen.getByRole("note");
    expect(notice).toHaveTextContent("Kandydat Nr1 pracuje u nas · Bank Przykładowy");
    expect(notice).toHaveTextContent("Zamówienie do 31.12.2026 · Delivery Lead: Karol Wzorcowy");
    expect(notice).toHaveTextContent("Dodanie jest możliwe.");
    expect(screen.getByTestId("add-candidates-confirm")).toBeEnabled();

    fireEvent.click(row);
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("a failed search is an error, not 'no results'", async () => {
    mocks.search.mockRejectedValue(new Error("down"));
    renderModal();
    expect(await screen.findByText("Błąd wyszukiwania. Spróbuj ponownie.")).toBeInTheDocument();
    expect(screen.queryByText("Wpisz imię lub nazwisko kandydata")).not.toBeInTheDocument();
  });
});

describe("AddCandidatesQuickModal — rama dialogu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.search.mockResolvedValue({ items: [item(1)], total: 1 });
  });

  it("jest dostępnym dialogiem z tytułem, a Escape go zamyka", async () => {
    const onClose = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AddCandidatesQuickModal open onClose={onClose} jobId={9} jobTitle="Java" />
      </QueryClientProvider>,
    );

    const dialog = await screen.findByRole("dialog", { name: "Dodaj kandydatów do pipeline" });
    expect(dialog).toBeInTheDocument();
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });
});

function signIn(role: "admin" | "recruiter") {
  const user = {
    id: role === "admin" ? 1 : 2,
    email: `${role}@example.com`,
    name: role,
    role,
    roles: [role],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
  } as unknown as User;
  act(() => {
    useAuthStore.setState({ user, hydrated: true });
  });
}

function person(id: number, extra: Record<string, unknown> = {}) {
  return {
    ...item(id),
    name: "Anna",
    lastname: "Przykładowa",
    email: `anna${id}@example.com`,
    phone: `+48 000 000 1${String(id).padStart(2, "0")}`,
    location: "Warszawa",
    created_at: "2026-09-02T10:00:00Z",
    last_recruitment: null,
    ...extra,
  };
}

const CLOSED_IN_JOB = {
  id: 30,
  name: "Anna",
  lastname: "Przykładowa",
  email: "anna30@example.com",
  phone: "000 000 101",
  location: null,
  card_label: "Odrzucony 08.10.2026 (Jan Testowy)",
  card_column: "closed",
  closed: {
    candidate_name: "Anna Przykładowa",
    state_version: 4,
    restore_stage: "new",
    restore_stage_def_id: 77,
  },
};

const ACTIVE_IN_JOB = {
  id: 31,
  name: "Anna",
  lastname: "Przykładowa",
  email: null,
  phone: null,
  location: null,
  card_label: "Screening od 09.10.2026",
  card_column: "screening",
  closed: null,
};

describe("AddCandidatesQuickModal — imiennicy (13.10.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.send.mockResolvedValue({ ok: true, data: {} });
  });

  afterEach(() => {
    act(() => {
      useAuthStore.setState({ user: null, hydrated: true });
    });
  });

  it("wiersz pokazuje telefon, e-mail, miasto i ostatnią rekrutację; brak danych jest napisany", async () => {
    mocks.search.mockResolvedValue({
      items: [
        person(1, {
          last_recruitment: {
            job_id: 5,
            job_title: "Administrator Azure",
            stage_label: "Odrzucony",
            column: "closed",
            moved_on: "2026-03-15",
          },
        }),
        person(2, { phone: null, email: null }),
      ],
      total: 2,
    });
    renderModal();

    const first = await screen.findByTestId("add-candidate-row-1");
    expect(first).toHaveTextContent("+48 000 000 101");
    expect(first).toHaveTextContent("anna1@example.com");
    expect(first).toHaveTextContent("Warszawa");
    expect(first).toHaveTextContent("ostatnio 03.2026: Odrzucony · Administrator Azure");

    const second = screen.getByTestId("add-candidate-row-2");
    expect(second).toHaveTextContent("brak telefonu");
    expect(second).toHaveTextContent("brak e-maila");
    expect(second).toHaveTextContent("jeszcze w żadnej rekrutacji, dodany 09.2026");
  });

  it("pasek imienników liczy też osoby już w rekrutacji", async () => {
    mocks.search.mockResolvedValue({
      items: [person(1), person(2)],
      total: 2,
      in_job_matches: [CLOSED_IN_JOB],
    });
    renderModal();

    const banner = await screen.findByTestId("add-candidates-homonyms");
    expect(banner).toHaveTextContent("3 osoby o imieniu i nazwisku Anna Przykładowa.");
    expect(banner).toHaveTextContent("Porównaj telefon i e-mail, zanim zaznaczysz.");
  });

  it("jedna osoba o danym imieniu i nazwisku — bez paska", async () => {
    mocks.search.mockResolvedValue({ items: [person(1), item(2)], total: 2 });
    renderModal();
    await screen.findByTestId("add-candidate-row-1");
    expect(screen.queryByTestId("add-candidates-homonyms")).toBeNull();
  });

  it("szukanie po numerze jest nazwane, a pasujący numer podświetlony", async () => {
    mocks.search.mockResolvedValue({
      items: [person(1)],
      total: 1,
      meta: {
        interpretation: {
          kind: "phone",
          mode: "literal",
          rule: "phone",
          name: [],
          email: null,
          phone: "000000101",
          skills: [],
          locations: [],
          other: [],
        },
      },
    });
    renderModal();
    fireEvent.change(screen.getByPlaceholderText("Imię i nazwisko, telefon albo e-mail…"), {
      target: { value: "000 000 101" },
    });

    expect(await screen.findByText(/Szukam po numerze telefonu · 1 wynik/)).toBeInTheDocument();
    expect(screen.getByText("+48 000 000 101").className).toContain("bg-primary/20");
  });

  it("osoby z kartą w tej rekrutacji są w osobnej sekcji; zamkniętą da się przywrócić", async () => {
    mocks.search.mockResolvedValue({
      items: [person(1)],
      total: 1,
      in_job_matches: [CLOSED_IN_JOB, ACTIVE_IN_JOB],
    });
    renderModal();
    fireEvent.change(screen.getByPlaceholderText("Imię i nazwisko, telefon albo e-mail…"), {
      target: { value: "Anna Przykładowa" },
    });

    const section = await screen.findByTestId("add-candidates-in-job");
    expect(section).toHaveTextContent("Już w tej rekrutacji (2)");
    expect(screen.getByText(/2 osoby są już w tej rekrutacji \(niżej\)/)).toBeInTheDocument();
    expect(screen.getByTestId("add-candidate-in-job-30")).toHaveTextContent(
      "Odrzucony 08.10.2026 (Jan Testowy)",
    );
    // Karta w toku: nic do zrobienia, tylko etap.
    const active = screen.getByTestId("add-candidate-in-job-31");
    expect(active).toHaveTextContent("Screening od 09.10.2026");
    expect(within(active).queryByRole("button")).toBeNull();
    // Osoby z rekrutacji nie da się zaznaczyć do dodania.
    expect(screen.queryByTestId("add-candidate-row-30")).toBeNull();

    fireEvent.click(screen.getByTestId("add-candidate-restore-30"));
    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    expect(mocks.send.mock.calls[0][0]).toEqual({
      candidate_id: 30,
      job_id: 9,
      stage: "new",
      stage_def_id: 77,
      expected_state_version: 4,
    });
    expect(screen.getByTestId("add-candidate-restore-30")).toHaveTextContent("Przywróć do „Nowych”");
    expect(mocks.add).not.toHaveBeenCalled();
  });

  it("ten sam numer co wiersz wyżej albo osoba z rekrutacji — plakietka", async () => {
    mocks.search.mockResolvedValue({
      items: [
        person(1, { phone: "+48 000 000 150" }),
        person(2, { phone: "000-000-150" }),
        person(3, { phone: "+48 000 000 101" }),
      ],
      total: 3,
      in_job_matches: [CLOSED_IN_JOB],
    });
    renderModal();

    await screen.findByTestId("add-candidate-row-1");
    expect(screen.queryByTestId("add-candidate-same-phone-1")).toBeNull();
    expect(screen.getByTestId("add-candidate-same-phone-2")).toHaveTextContent(
      "Ten sam telefon co 1. wiersz",
    );
    expect(screen.getByTestId("add-candidate-same-phone-3")).toHaveTextContent(
      "Ten sam telefon co osoba już w tej rekrutacji",
    );
  });

  it("„Scal…” widzi admin, nie rekruter; otwiera scalanie z wcześniejszym wierszem jako ocalałym", async () => {
    mocks.search.mockResolvedValue({
      items: [person(1, { phone: "000 000 150" }), person(2, { phone: "000000150" })],
      total: 2,
    });

    signIn("recruiter");
    const { unmount } = renderModalWithUnmount();
    await screen.findByTestId("add-candidate-same-phone-2");
    expect(screen.queryByTestId("add-candidate-merge-2")).toBeNull();
    unmount();

    signIn("admin");
    renderModal();
    fireEvent.click(await screen.findByTestId("add-candidate-merge-2"));
    expect(screen.getByTestId("merge-dialog")).toHaveTextContent("zostaje 1, duplikat 2");
  });

  it("„Profil” otwiera nową kartę i nie siedzi w przycisku zaznaczania", async () => {
    mocks.search.mockResolvedValue({ items: [person(1)], total: 1 });
    signIn("admin");
    renderModal();

    const row = await screen.findByTestId("add-candidate-row-1");
    const link = screen.getByRole("link", { name: /Profil: Anna Przykładowa/ });
    expect(link).toHaveAttribute("href", "/candidates/1?from=job&jobId=9");
    expect(link).toHaveAttribute("target", "_blank");
    expect(row.contains(link)).toBe(false);

    fireEvent.click(link);
    expect(screen.getByText("Wybierz kandydatów do dodania")).toBeInTheDocument();
  });
});

function renderModalWithUnmount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AddCandidatesQuickModal open onClose={vi.fn()} jobId={9} jobTitle="Java" />
    </QueryClientProvider>,
  );
}

// Audyt 13.10.2026: zaślepka „000 000 000” dawała „Ten sam telefon” i „Scal…”,
// numer szukany po 6–8 cyfrach nie świecił, a okno dawało się zamknąć w trakcie
// „Przywróć” (ruch karty zostawał bez swoich okien potwierdzeń).
describe("AddCandidatesQuickModal — poprawki po audycie 13.10.2026", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.send.mockResolvedValue({ ok: true, data: {} });
  });

  afterEach(() => {
    act(() => {
      useAuthStore.setState({ user: null, hydrated: true });
    });
  });

  it("dwie osoby z numerem-zaślepką „000 000 000” nie dostają „Ten sam telefon” ani „Scal…”", async () => {
    mocks.search.mockResolvedValue({
      items: [person(1, { phone: "000 000 000" }), person(2, { phone: "+48 000-000-000" })],
      total: 2,
    });
    signIn("admin");
    renderModal();

    await screen.findByTestId("add-candidate-row-2");
    expect(screen.queryByTestId("add-candidate-same-phone-2")).toBeNull();
    expect(screen.queryByTestId("add-candidate-merge-2")).toBeNull();
  });

  it("numer szukany po 6 cyfrach jest podświetlony, jak trafienie z wyszukiwarki", async () => {
    mocks.search.mockResolvedValue({
      items: [person(1, { phone: "+48 601 204 118" })],
      total: 1,
      meta: {
        interpretation: {
          kind: "phone",
          mode: "literal",
          rule: "phone",
          name: [],
          email: null,
          phone: "204118",
          skills: [],
          locations: [],
          other: [],
        },
      },
    });
    renderModal();
    fireEvent.change(screen.getByPlaceholderText("Imię i nazwisko, telefon albo e-mail…"), {
      target: { value: "204 118" },
    });

    expect(await screen.findByText(/Szukam po numerze telefonu/)).toBeInTheDocument();
    expect(screen.getByText("+48 601 204 118").className).toContain("bg-primary/20");
  });

  it("w trakcie „Przywróć” okna nie da się zamknąć; po ruchu znowu się da", async () => {
    let finish: (value: { ok: boolean; data: unknown }) => void = () => {};
    mocks.send.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    mocks.search.mockResolvedValue({ items: [person(1)], total: 1, in_job_matches: [CLOSED_IN_JOB] });
    const onClose = vi.fn();
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <AddCandidatesQuickModal open onClose={onClose} jobId={9} jobTitle="Java" />
      </QueryClientProvider>,
    );
    fireEvent.change(screen.getByPlaceholderText("Imię i nazwisko, telefon albo e-mail…"), {
      target: { value: "Anna Przykładowa" },
    });

    fireEvent.click(await screen.findByTestId("add-candidate-restore-30"));
    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    const dialog = screen.getByRole("dialog", { name: "Dodaj kandydatów do pipeline" });
    fireEvent.keyDown(dialog, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Zamknij" }));
    fireEvent.click(screen.getByRole("button", { name: "Anuluj" }));
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      finish({ ok: true, data: {} });
    });
    await waitFor(() => expect(screen.getByTestId("add-candidate-restore-30")).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Zamknij" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
