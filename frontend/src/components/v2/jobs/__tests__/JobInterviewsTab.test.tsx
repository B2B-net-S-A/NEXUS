/**
 * Krok 07 „Rozmowy i decyzja" — co ta zakładka MUSI mówić prawdę o.
 *
 * Najważniejsze asercje dotyczą weta hiring managera. Weto nie jest wierszem
 * w bazie: `services/hiring_manager_verdicts` wyprowadza je z odrzucenia
 * powodem oznaczonym `disqualifies_person`. Formularz feedbacku ma więc
 * POKAZYWAĆ, czy wybrany powód w ogóle może zablokować — a nie oferować
 * przełącznik, który niczego nie zapisze.
 */

import type { ComponentProps } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listFeedback = vi.fn();
const recordFeedback = vi.fn();
const getForStage = vi.fn();
const createShareToken = vi.fn();
const apiGet = vi.fn();
const apiPost = vi.fn();
const templatesGet = vi.fn();
const templatesList = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => apiGet(...a),
    post: (...a: unknown[]) => apiPost(...a),
  },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
  hiringManagerFeedbackApi: {
    list: (...a: unknown[]) => listFeedback(...a),
    record: (...a: unknown[]) => recordFeedback(...a),
  },
  screeningApi: {
    getForStage: (...a: unknown[]) => getForStage(...a),
    createShareToken: (...a: unknown[]) => createShareToken(...a),
  },
  pipelineTemplatesApi: {
    get: (...a: unknown[]) => templatesGet(...a),
    list: (...a: unknown[]) => templatesList(...a),
  },
  CONTRACT_FIELD_LABELS: {},
}));

const showSuccess = vi.fn();
const showError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));
const copyText = vi.fn(async (..._a: unknown[]) => true);
vi.mock("@/lib/clipboard", () => ({
  copyTextToClipboard: (...a: unknown[]) => copyText(...a),
}));

// Arkusz screeningu i modal odrzucenia mają WŁASNE zapytania — zakładka tylko
// je otwiera, więc do jej testów wystarczy stub.
vi.mock("@/components/v2/modals/ScreeningSheet", () => ({
  ScreeningSheet: () => <div data-testid="screening-sheet-stub" />,
}));
vi.mock("@/components/v2/modals/RejectionV2", () => ({
  RejectionV2: () => <div data-testid="rejection-stub" />,
}));
vi.mock("@/components/v2/modals/CVOriginalPreviewModal", () => ({
  CVOriginalPreviewModal: () => <div data-testid="cv-original-stub" />,
}));
vi.mock("@/components/v2/modals/PrepInviteModal", () => ({
  PrepInviteModal: () => <div data-testid="prep-invite-stub" />,
}));

import { JobInterviewsTab, feedbackStatusLabel } from "@/components/v2/jobs/JobInterviewsTab";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { useAuthStore, type UserRole } from "@/store/auth";

function loginAs(role: UserRole) {
  useAuthStore.setState({
    user: { id: 7, role, roles: [role] } as never,
    realUser: null,
  });
}

function item(overrides: Partial<KanbanItem> = {}): KanbanItem {
  return {
    id: 900,
    candidate_id: 42,
    stage: "client_interview",
    name: "Grzegorz",
    lastname: "Żebrowski",
    days_in_stage: 2,
    verification_status: "active",
    ...overrides,
  };
}

function columns(overrides: Partial<KanbanColumn>[] = []): KanbanColumn[] {
  const base: KanbanColumn[] = [
    {
      stage: "client_interview",
      name: "Interview Klient",
      category: "external",
      count: 1,
      items: [item()],
      stage_def_id: 6,
    },
    {
      stage: "acceptance",
      name: "Akceptacja",
      category: "external",
      count: 0,
      items: [],
      stage_def_id: 7,
    },
    {
      stage: "cv_sent",
      name: "CV Wysłane",
      category: "internal",
      count: 0,
      items: [],
      stage_def_id: 5,
    },
    {
      stage: "rejected",
      name: "Odrzucony",
      category: "terminal",
      count: 0,
      items: [],
      stage_def_id: 11,
      terminal_type: "rejected",
    },
  ];
  return overrides.length > 0
    ? base.map((c, i) => ({ ...c, ...(overrides[i] ?? {}) }))
    : base;
}

type Props = ComponentProps<typeof JobInterviewsTab>;

function renderTab(overrides: Partial<Props> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const props: Props = {
    jobId: 10,
    jobTitle: "Programista Python",
    columns: columns(),
    readOnly: false,
    ...overrides,
  };
  render(
    <QueryClientProvider client={qc}>
      <JobInterviewsTab {...props} />
    </QueryClientProvider>,
  );
  return props;
}

beforeEach(() => {
  vi.clearAllMocks();
  loginAs("recruiter");
  copyText.mockResolvedValue(true);
  listFeedback.mockResolvedValue({ can_record: true, items: [] });
  recordFeedback.mockResolvedValue({
    id: 1,
    job_id: 10,
    candidate_id: 42,
    decision: "reject",
    rejection_reason_id: 3,
    rejection_reason_name: "Nie spełnia wymagań technicznych",
    note: null,
    technical_fit: null,
    soft_fit: null,
    overall_fit: null,
    hiring_manager_contact_id: 5,
    hiring_manager_name: "Anna Nowak",
    blocks_future_proposals: true,
    veto_recorded: false,
    veto_blockers: ["Kandydat nie został jeszcze odrzucony na tej rekrutacji."],
  });
  getForStage.mockResolvedValue({ data: { screening_answers: null } });
  createShareToken.mockResolvedValue({
    data: { token: "t", expires_at: "", share_url_suffix: "/share/x" },
  });
  apiGet.mockResolvedValue({ data: { pipeline_template_id: 1 } });
  apiPost.mockResolvedValue({ data: {} });
  templatesGet.mockResolvedValue({
    data: {
      stages: [],
      rejection_reasons: [
        {
          id: 3,
          template_id: 1,
          stage_def_id: null,
          name: "Nie spełnia wymagań technicznych",
          order: 0,
          category: "rejected",
          active: true,
          disqualifies_person: true,
          created_at: "",
          updated_at: "",
        },
        {
          id: 4,
          template_id: 1,
          stage_def_id: null,
          name: "Za wysokie oczekiwania finansowe",
          order: 1,
          category: "rejected",
          active: true,
          disqualifies_person: false,
          created_at: "",
          updated_at: "",
        },
      ],
    },
  });
  templatesList.mockResolvedValue({ data: [] });
});

describe("JobInterviewsTab", () => {
  it("pokazuje kandydatów z etapów zewnętrznych i wybiera pierwszego", async () => {
    renderTab();
    // Nazwisko pada w trzech miejscach naraz: lewa lista, karta rozmowy i dok.
    expect(
      (await screen.findAllByText("Grzegorz Żebrowski")).length,
    ).toBeGreaterThanOrEqual(2);
    // Nagłówek kroku w języku makiety: „Krok · Nazwisko".
    expect(
      screen.getByRole("heading", {
        name: "Rozmowa u klienta · Grzegorz Żebrowski",
      }),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Feedback klienta po rozmowie" }),
    ).toBeTruthy();
    // Stan weta jako pigułka listwy — widoczny bez rozwijania czegokolwiek.
    expect(screen.getByText("Weto HM: brak")).toBeTruthy();
  });

  /** Słownik powodów dociąga się osobnym zapytaniem — bez tego `select` ma
   *  wyłącznie opcję „Wczytywanie słownika…". */
  async function reasonSelect() {
    const select = await screen.findByLabelText("Powód (gdy odrzuca)");
    await screen.findByRole("option", {
      name: "Nie spełnia wymagań technicznych",
    });
    await editableForm();
    return select;
  }

  it("powód-werdykt o osobie mówi, że weto POWSTANIE — nie że już jest", async () => {
    renderTab();
    await userEvent.selectOptions(await reasonSelect(), "3");

    expect(
      screen.getByText(/weto powstanie, gdy kandydat zostanie odrzucony/i),
    ).toBeTruthy();
  });

  it("powód sytuacyjny mówi wprost, że NIE zablokuje", async () => {
    renderTab();
    await userEvent.selectOptions(await reasonSelect(), "4");

    expect(
      screen.getByText(/opisuje sytuację, nie osobę/i),
    ).toBeTruthy();
  });

  /** Formularz odblokowuje się dopiero po `can_record` z serwera. */
  async function editableForm() {
    await waitFor(() =>
      expect(screen.getByLabelText("Notatka z feedbacku")).not.toBeDisabled(),
    );
  }

  it("zapisuje werdykt przez `POST /jobs/{id}/hiring-manager-feedback`", async () => {
    renderTab();
    await editableForm();
    await userEvent.click(await screen.findByRole("button", { name: "Odrzuca" }));
    await userEvent.selectOptions(await reasonSelect(), "3");
    await userEvent.type(
      screen.getByLabelText("Notatka z feedbacku"),
      "Nie przekonał przy Kafce.",
    );
    await userEvent.click(screen.getByRole("button", { name: /Zapisz feedback/ }));

    await waitFor(() => expect(recordFeedback).toHaveBeenCalledTimes(1));
    expect(recordFeedback).toHaveBeenCalledWith(10, {
      candidate_id: 42,
      decision: "reject",
      rejection_reason_id: 3,
      note: "Nie przekonał przy Kafce.",
    });
  });

  it("readOnly wyłącza formularz i chowa zapis, ale zostawia odczyt", async () => {
    renderTab({ readOnly: true });
    expect(await screen.findByLabelText("Powód (gdy odrzuca)")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Zapisz feedback/ })).toBeNull();
    expect(screen.getByText(/Tylko do odczytu/)).toBeTruthy();
  });

  it("„CV Wysłane” jest wyszarzone z powodem — jego modal mieszka na tablicy", async () => {
    renderTab();
    const pill = await screen.findByRole("button", { name: "CV Wysłane" });
    expect(pill).toBeDisabled();
    expect(pill.getAttribute("title")).toMatch(/stawkę do klienta/);
  });

  it("weto HM blokuje WYŁĄCZNIE „CV Wysłane”/„Interview Klient” — „Akceptacja” i odrzucenie przechodzą, jak na serwerze", async () => {
    const withVeto = columns();
    withVeto[0] = {
      ...withVeto[0],
      items: [
        item({
          hm_veto: {
            hiring_manager_contact_id: 5,
            hiring_manager_name: "Anna Nowak",
            source_job_id: 3,
            source_job_title: "Inny projekt",
            rejected_at: "2026-05-04T10:00:00Z",
            rejection_reason_name: "Nie pasuje kulturowo",
          },
        }),
      ],
    };
    renderTab({ columns: withVeto });

    // `puts_candidate_before_client` egzekwuje weto tylko dla cv_sent
    // i client_interview — do 09.2026 dok wyszarzał każdy ruch, więc
    // „Akceptacja"/„Zatrudniony" były martwe, choć serwer je przepuszcza.
    const acceptance = await screen.findByRole("button", { name: "Akceptacja" });
    expect(acceptance).not.toBeDisabled();

    // „CV Wysłane" — powód weta wygrywa z „ten dialog mieszka na tablicy".
    const cvSent = screen.getByRole("button", { name: "CV Wysłane" });
    expect(cvSent).toBeDisabled();
    expect(cvSent.getAttribute("title")).toMatch(/Hiring manager/);

    // Ruch wypisujący przechodzi zawsze — inaczej kandydata z wetem nie
    // dałoby się domknąć z tej powierzchni.
    const rejected = screen.getByRole("button", { name: "Odrzucony" });
    expect(rejected).not.toBeDisabled();
  });

  it("F05: ruch z doku wysyła wersję procesu z karty", async () => {
    const withVersion = columns();
    withVersion[0] = { ...withVersion[0], items: [item({ process_state_version: 3 })] };
    renderTab({ columns: withVersion });

    await userEvent.click(await screen.findByRole("button", { name: "Akceptacja" }));

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({
          candidate_id: 42,
          stage: "acceptance",
          expected_state_version: 3,
        }),
      ),
    );
  });

  it("F05: 409 PIPELINE_VERSION_CONFLICT — komunikat bez ponowienia", async () => {
    apiPost.mockImplementation((url: string) =>
      url === "/api/pipeline/move"
        ? Promise.reject({
            response: {
              status: 409,
              data: { detail: { code: "PIPELINE_VERSION_CONFLICT", message: "x" } },
            },
          })
        : Promise.resolve({ data: {} }),
    );
    const withVersion = columns();
    withVersion[0] = { ...withVersion[0], items: [item({ process_state_version: 3 })] };
    renderTab({ columns: withVersion });

    await userEvent.click(await screen.findByRole("button", { name: "Akceptacja" }));

    await waitFor(() =>
      expect(showError).toHaveBeenCalledWith(
        "Kandydat został w międzyczasie przesunięty przez kogoś innego — odświeżyłem kartę.",
      ),
    );
    await new Promise((r) => setTimeout(r, 50));
    expect(
      apiPost.mock.calls.filter((c) => c[0] === "/api/pipeline/move"),
    ).toHaveLength(1);
    expect(showSuccess).not.toHaveBeenCalled();
  });

  it("stawka ponad budżet (bramka „Pending” wyłączona) to informacja — ruchy zostają dostępne", async () => {
    const overBudget = columns();
    overBudget[0] = {
      ...overBudget[0],
      items: [item({ verification_status: "pending", budget_exceeded: true })],
    };
    renderTab({ columns: overBudget });

    expect(await screen.findByText("Stawka ponad budżet")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Akceptacja" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Odrzucony" })).not.toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Odrzuć z powodem/ }),
    ).not.toBeDisabled();
  });

  it("Head of Recruitment spoza zespołu (parytet z rekruterem od 17.09.2026) dostaje podgląd, nie „Zapisz” kończące się 403", async () => {
    loginAs("head_of_recruitment");
    listFeedback.mockResolvedValue({ can_record: false, items: [] });
    renderTab();
    expect(await screen.findByText(/nie należysz do niego/)).toBeTruthy();
    expect(screen.getByLabelText("Powód (gdy odrzuca)")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Zapisz feedback/ })).toBeNull();
  });

  it("Finance spoza zespołu rekrutacji dostaje podgląd, nie „Zapisz” kończące się 403 (`can_record=false`)", async () => {
    // Finance ma capability zapisu (tier RecruiterPlus), ale POST sprawdza też
    // członkostwo w zespole — o tym mówi wyłącznie serwer polem `can_record`.
    loginAs("finance");
    listFeedback.mockResolvedValue({ can_record: false, items: [] });
    renderTab();
    expect(await screen.findByText(/nie należysz do niego/)).toBeTruthy();
    expect(screen.getByLabelText("Notatka z feedbacku")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Zapisz feedback/ })).toBeNull();
    expect(recordFeedback).not.toHaveBeenCalled();
  });

  it("zanim serwer powie `can_record`, formularz nie jest edytowalny", async () => {
    listFeedback.mockReturnValue(new Promise(() => {}));
    renderTab();
    expect(await screen.findByLabelText("Notatka z feedbacku")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Zapisz feedback/ })).toBeNull();
  });

  it("cudzy werdykt (can_edit=false) jest zablokowany z imieniem autora — bez cichego nadpisania", async () => {
    listFeedback.mockResolvedValue({
      can_record: true,
      items: [
      {
        id: 55,
        job_id: 10,
        candidate_id: 42,
        decision: "advance",
        rejection_reason_id: null,
        rejection_reason_name: null,
        note: "Klient chce drugą rozmowę.",
        technical_fit: null,
        soft_fit: null,
        overall_fit: null,
        hiring_manager_contact_id: 5,
        hiring_manager_name: "Anna Nowak",
        blocks_future_proposals: false,
        veto_recorded: false,
        veto_blockers: [],
        author_id: 99,
        author_name: "Ewa Kolega",
        can_edit: false,
      },
      ],
    });
    renderTab();
    expect(await screen.findByText(/zapisał\(a\) Ewa Kolega/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Zapisz feedback/ })).toBeNull();
    expect(screen.getByLabelText("Notatka z feedbacku")).toBeDisabled();
    expect(recordFeedback).not.toHaveBeenCalled();
  });

  it("link do karty Championa: adres zostaje na karcie, a „skopiowany” pada tylko po udanym kopiowaniu", async () => {
    copyText.mockResolvedValueOnce(false);
    createShareToken.mockResolvedValueOnce({
      data: { token: "t", expires_at: "", share_url_suffix: "/share/champion-card/k07" },
    });
    renderTab();
    await userEvent.click(
      await screen.findByRole("button", { name: /Karta Championa dla klienta/ }),
    );
    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(showError.mock.calls[0][0]).toContain("nie udało się go skopiować");
    expect(showSuccess).not.toHaveBeenCalledWith(
      expect.stringContaining("skopiowany"),
    );
    const field = await screen.findByLabelText("Link do karty Championa dla klienta");
    expect((field as HTMLInputElement).value).toBe(
      `${window.location.origin}/share/champion-card/k07`,
    );
  });

  it("pusty pipeline mówi „nikt nie jest u klienta”, a nie renderuje pustki", async () => {
    const empty = columns().map((c) => ({ ...c, items: [], count: 0 }));
    renderTab({ columns: empty, columnsSuccess: true });
    expect(
      await screen.findByText("Nikt nie jest jeszcze u klienta"),
    ).toBeTruthy();
  });

  it("awaria kanbana NIE udaje pustego kroku", async () => {
    // Pipeline przychodzi propsem, więc bez jawnego błędu 500 wyglądałoby
    // stąd identycznie jak „nikt nie jest u klienta".
    renderTab({
      columns: [],
      columnsSuccess: false,
      columnsError: { response: { status: 500 } },
    });
    expect(screen.getByText("Nie udało się pobrać danych")).toBeTruthy();
    expect(screen.queryByText("Nikt nie jest jeszcze u klienta")).toBeNull();
  });

  it("403 na kanbanie to brak uprawnień, nie zero kandydatów", async () => {
    renderTab({
      columns: [],
      columnsSuccess: false,
      columnsError: { response: { status: 403 } },
    });
    expect(screen.getByText("Brak uprawnień")).toBeTruthy();
    expect(screen.queryByText("Nikt nie jest jeszcze u klienta")).toBeNull();
  });

  it("awaria pobierania werdyktów renderuje się jako awaria, nie jako brak feedbacku", async () => {
    listFeedback.mockRejectedValue(
      Object.assign(new Error("boom"), { response: { status: 500 } }),
    );
    renderTab();
    expect(
      await screen.findByText("Nie udało się pobrać danych"),
    ).toBeTruthy();
  });

  // ── Parytet z makietą (fala 3) ─────────────────────────────────────────
  it("szyna ma sekcję „Przygotowanie” — trzy wejścia, które dotąd były rozsiane", async () => {
    renderTab();
    await screen.findByRole("heading", { name: /Rozmowa u klienta/ });
    expect(screen.getByText("Przygotowanie")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: /Prep-kit \(AI\)/ }),
    ).toHaveAttribute("href", "/jobs/10/prep/42");
    expect(
      screen.getByRole("button", { name: /Screening Championa dla klienta/ }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /Zaproszenie prep/ }),
    ).toBeTruthy();
  });

  it("„Screening Championa dla klienta” z szyny otwiera TEN SAM arkusz co tablica", async () => {
    renderTab();
    await screen.findByRole("heading", { name: /Rozmowa u klienta/ });
    await userEvent.click(
      screen.getByRole("button", { name: /Screening Championa dla klienta/ }),
    );
    expect(await screen.findByTestId("screening-sheet-stub")).toBeTruthy();
  });

  it("„Zaproszenie prep” otwiera istniejący modal, a nie drugą jego kopię", async () => {
    renderTab();
    await screen.findByRole("heading", { name: /Rozmowa u klienta/ });
    await userEvent.click(
      screen.getByRole("button", { name: /Zaproszenie prep/ }),
    );
    expect(await screen.findByTestId("prep-invite-stub")).toBeTruthy();
  });

  it("dok oferty pokazuje ten sam budżet godzinowy co nagłówek rekrutacji (UAT B72)", async () => {
    renderTab({ budgetHourly: 155 });
    await screen.findByRole("heading", { name: /Rozmowa u klienta/ });
    await userEvent.click(screen.getByRole("tab", { name: "Oferta" }));
    expect(screen.getByText("do 155,00 PLN/h")).toBeTruthy();
  });

  it("bez budżetu godzinowego dok podpisuje migawkę jako miesięczną z chwili ruchu", async () => {
    renderTab({ columns: columns([{ items: [item({ budget_max_at_move: 20000 })] }]) });
    await screen.findByRole("heading", { name: /Rozmowa u klienta/ });
    await userEvent.click(screen.getByRole("tab", { name: "Oferta" }));
    expect(screen.getByText(/PLN\/mies\./)).toBeTruthy();
    expect(screen.getByText("(w chwili przesunięcia)")).toBeTruthy();
  });

  it("dok wypisuje reguły odrzucenia i regułę konfetti, zamiast kazać ich pamiętać", async () => {
    renderTab();
    await screen.findByRole("heading", { name: /Rozmowa u klienta/ });
    expect(screen.getByText("Odrzucenie / wycofanie")).toBeTruthy();
    expect(screen.getByText(/„Wycofany” ZAWSZE ze słownika/)).toBeTruthy();
    expect(screen.getByText(/wysyłka za 15 min/)).toBeTruthy();
    expect(screen.getByText(/konfetti jak dziś/)).toBeTruthy();
  });
});

describe("feedback klienta zapisany z kalendarza (audyt 17.09.2026)", () => {
  it("status nazywa werdykt z rozmowy datą, zamiast „do uzupełnienia”", async () => {
    listFeedback.mockResolvedValue({
      can_record: true,
      items: [
        {
          id: 9,
          job_id: 10,
          candidate_id: 42,
          decision: "on_hold",
          rejection_reason_id: null,
          rejection_reason_name: null,
          note: "Klient chce się zastanowić.",
          technical_fit: null,
          soft_fit: null,
          overall_fit: null,
          hiring_manager_contact_id: null,
          hiring_manager_name: null,
          blocks_future_proposals: false,
          veto_recorded: false,
          veto_blockers: [],
          can_edit: true,
          calendar_event_id: 77,
          event_start_time: "2026-09-15T10:00:00Z",
          event_title: "Rozmowa u klienta",
        },
      ],
    });
    renderTab();
    expect(await screen.findByText(/zapisany · z rozmowy 15\.09/)).toBeTruthy();
    expect(screen.queryByText("do uzupełnienia")).toBeNull();
  });

  it("etykieta statusu bez wydarzenia i bez wpisu", () => {
    expect(feedbackStatusLabel(null)).toBe("do uzupełnienia");
    expect(feedbackStatusLabel({ calendar_event_id: null, event_start_time: null })).toBe(
      "zapisany",
    );
  });
});
